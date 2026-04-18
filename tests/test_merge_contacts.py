"""POST /contacts/merge — merge two duplicates into one."""

from __future__ import annotations

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Deal, Note, Relationship, Task


def _mk_contact(client, h, **kw) -> dict:
    return client.post("/contacts", headers=h, json=kw).json()


def test_merge_scalar_fields_winner_wins_unless_null(client, workspace):
    h = workspace["headers"]
    winner = _mk_contact(client, h, first_name="Ada", email="ada@example.com")
    loser = _mk_contact(
        client,
        h,
        first_name="Ada",
        last_name="Lovelace",  # winner had no last_name → inherit
        email="ada2@example.com",  # winner has email → keep winner's
        title="Countess of Lovelace",
    )

    r = client.post(
        "/contacts/merge",
        headers=h,
        json={"winner_id": winner["id"], "loser_id": loser["id"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is False
    assert body["changes"]["last_name"] == {"from": None, "to": "Lovelace"}
    assert body["changes"]["title"] == {"from": None, "to": "Countess of Lovelace"}
    # email NOT changed — winner had a non-null value.
    assert "email" not in body["changes"]

    # Winner row matches.
    refreshed = client.get(f"/contacts/{winner['id']}", headers=h).json()
    assert refreshed["last_name"] == "Lovelace"
    assert refreshed["email"] == "ada@example.com"

    # Loser soft-deleted with pointer.
    r = client.get(f"/contacts/{loser['id']}?", headers=h)
    # Default list excludes deleted.
    r = client.get("/contacts?include_deleted=true", headers=h)
    loser_row = next(c for c in r.json()["items"] if c["id"] == loser["id"])
    assert loser_row["data"]["merged_into"] == winner["id"]


def test_merge_rewrites_foreign_keys(client, workspace):
    h = workspace["headers"]

    # Deals need a pipeline; make a minimal default one up front.
    client.post(
        "/pipelines",
        headers=h,
        json={
            "name": "Sales",
            "slug": "sales",
            "is_default": True,
            "stages": [{"name": "Lead", "slug": "lead", "position": 0}],
        },
    )

    winner = _mk_contact(client, h, first_name="Ada", email="ada@example.com")
    loser = _mk_contact(client, h, first_name="Ada L.", email="ada@old.example")
    co = client.post("/companies", headers=h, json={"name": "Acme"}).json()

    # Wire every kind of reference to the loser.
    deal_resp = client.post(
        "/deals",
        headers=h,
        json={
            "name": "Big",
            "primary_contact_id": loser["id"],
            "company_id": co["id"],
        },
    )
    assert deal_resp.status_code == 201, deal_resp.text
    deal = deal_resp.json()
    client.post(
        "/notes",
        headers=h,
        json={"entity_type": "contact", "entity_id": loser["id"], "body": "met for coffee"},
    )
    client.post(
        "/tasks",
        headers=h,
        json={"title": "follow up", "entity_type": "contact", "entity_id": loser["id"]},
    )
    client.post(
        "/activities",
        headers=h,
        json={"kind": "call", "entity_type": "contact", "entity_id": loser["id"]},
    )
    client.post(
        "/relationships",
        headers=h,
        json={
            "source_type": "contact",
            "source_id": loser["id"],
            "target_type": "company",
            "target_id": co["id"],
            "relation_type": "works_at",
        },
    )
    client.post(
        "/memory/link",
        headers=h,
        json={
            "connector": "docdeploy",
            "external_id": "mem_abc",
            "crm_entity_type": "contact",
            "crm_entity_id": loser["id"],
        },
    )

    r = client.post(
        "/contacts/merge",
        headers=h,
        json={"winner_id": winner["id"], "loser_id": loser["id"]},
    )
    assert r.status_code == 200, r.text
    counts = r.json()["references_rewritten"]
    assert counts["deals.primary_contact_id"] == 1
    assert counts["notes"] == 1
    assert counts["tasks"] == 1
    assert counts["activities"] == 1
    assert counts["relationships"] == 1
    assert counts["memory_links"] == 1

    # Everything now points at winner.
    db = SessionLocal()
    try:
        d = db.scalars(select(Deal).where(Deal.id == deal["id"])).one()
        assert d.primary_contact_id == winner["id"]

        n = db.scalars(select(Note).where(Note.body == "met for coffee")).one()
        assert n.entity_id == winner["id"]

        t = db.scalars(select(Task).where(Task.title == "follow up")).one()
        assert t.entity_id == winner["id"]

        edge = db.scalars(select(Relationship).where(Relationship.relation_type == "works_at")).one()
        assert edge.source_id == winner["id"]
    finally:
        db.close()

    # Timeline on the winner carries the merge event.
    events = client.get(f"/timeline/contact/{winner['id']}", headers=h).json()["items"]
    merged = next(e for e in events if e["event_type"] == "contact.merged")
    assert merged["payload"]["loser_id"] == loser["id"]
    assert merged["payload"]["references_rewritten"]["notes"] == 1


def test_tags_union_and_data_shallow_merge(client, workspace):
    h = workspace["headers"]
    winner = _mk_contact(
        client,
        h,
        first_name="Ada",
        tags=["vip", "researcher"],
        data={"source": "apollo", "score": 0.8},
    )
    loser = _mk_contact(
        client,
        h,
        first_name="Ada",
        tags=["alumni", "vip"],  # "vip" dedupes
        data={"score": 0.5, "company_size": 500},  # "score" conflicts; "company_size" merges in
    )

    r = client.post(
        "/contacts/merge",
        headers=h,
        json={"winner_id": winner["id"], "loser_id": loser["id"]},
    )
    assert r.status_code == 200
    refreshed = client.get(f"/contacts/{winner['id']}", headers=h).json()
    assert set(refreshed["tags"]) == {"vip", "researcher", "alumni"}
    assert refreshed["data"]["source"] == "apollo"
    assert refreshed["data"]["score"] == 0.8  # winner wins on conflict
    assert refreshed["data"]["company_size"] == 500


def test_field_preferences_override(client, workspace):
    h = workspace["headers"]
    winner = _mk_contact(client, h, first_name="Ada", title="Mathematician")
    loser = _mk_contact(client, h, first_name="Ada", title="Countess")

    r = client.post(
        "/contacts/merge",
        headers=h,
        json={
            "winner_id": winner["id"],
            "loser_id": loser["id"],
            "field_preferences": {"title": "loser"},  # force loser's value
        },
    )
    assert r.status_code == 200
    assert r.json()["changes"]["title"] == {"from": "Mathematician", "to": "Countess"}
    refreshed = client.get(f"/contacts/{winner['id']}", headers=h).json()
    assert refreshed["title"] == "Countess"


def test_dry_run_reports_changes_without_persisting(client, workspace):
    h = workspace["headers"]
    winner = _mk_contact(client, h, first_name="Ada")
    loser = _mk_contact(client, h, first_name="Ada", last_name="Lovelace")

    r = client.post(
        "/contacts/merge",
        headers=h,
        json={"winner_id": winner["id"], "loser_id": loser["id"], "dry_run": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["changes"]["last_name"]["to"] == "Lovelace"

    # DB unchanged.
    w = client.get(f"/contacts/{winner['id']}", headers=h).json()
    assert w["last_name"] is None
    listing = client.get("/contacts?include_deleted=true", headers=h).json()
    loser_row = next(c for c in listing["items"] if c["id"] == loser["id"])
    assert loser_row["data"].get("merged_into") is None  # not merged


def test_same_id_is_rejected(client, workspace):
    h = workspace["headers"]
    c = _mk_contact(client, h, first_name="Ada")
    r = client.post(
        "/contacts/merge",
        headers=h,
        json={"winner_id": c["id"], "loser_id": c["id"]},
    )
    assert r.status_code == 400


def test_missing_contacts_rejected(client, workspace):
    h = workspace["headers"]
    c = _mk_contact(client, h, first_name="Ada")
    r = client.post(
        "/contacts/merge",
        headers=h,
        json={"winner_id": c["id"], "loser_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 400


def test_members_cannot_merge(client, workspace):
    h = workspace["headers"]
    winner = _mk_contact(client, h, first_name="Ada")
    loser = _mk_contact(client, h, first_name="Ada")

    member_key = client.post(
        "/workspace/api-keys",
        headers=h,
        json={"name": "m", "role": "member"},
    ).json()["key"]
    member_h = {"Authorization": f"Bearer {member_key}"}

    r = client.post(
        "/contacts/merge",
        headers=member_h,
        json={"winner_id": winner["id"], "loser_id": loser["id"]},
    )
    assert r.status_code == 403
