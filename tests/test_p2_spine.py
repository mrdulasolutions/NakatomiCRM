"""P2 CRM spine: leads, participants, views, quotes, company hierarchy/merge."""

from __future__ import annotations


def _pipeline(client, h):
    r = client.post(
        "/pipelines",
        headers=h,
        json={
            "name": "Sales",
            "slug": "sales-p2",
            "is_default": True,
            "stages": [
                {"name": "Lead", "slug": "lead", "position": 0, "probability": 10},
                {"name": "Won", "slug": "won", "position": 1, "probability": 100, "is_won": True},
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_lead_create_convert_with_deal(client, workspace):
    h = workspace["headers"]
    _pipeline(client, h)
    r = client.post(
        "/leads",
        headers=h,
        json={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@analytical.engine",
            "company_name": "Analytical Engines",
            "company_domain": "analytical.engine",
            "source": "inbound",
        },
    )
    assert r.status_code == 201, r.text
    lead_id = r.json()["id"]
    assert r.json()["status"] == "new"

    r = client.get(f"/leads/{lead_id}/duplicates", headers=h)
    assert r.status_code == 200
    assert r.json()["count"] == 0

    r = client.post(
        f"/leads/{lead_id}/convert",
        headers=h,
        json={"create_company": True, "create_deal": True, "amount": 5000},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["contact_id"]
    assert body["company_id"]
    assert body["deal_id"]
    assert body["already_converted"] is False

    r = client.get(f"/leads/{lead_id}", headers=h)
    assert r.json()["status"] == "converted"
    assert r.json()["converted_contact_id"] == body["contact_id"]

    # idempotent re-convert
    r = client.post(f"/leads/{lead_id}/convert", headers=h, json={})
    assert r.status_code == 200
    assert r.json()["already_converted"] is True


def test_deal_participants(client, workspace):
    h = workspace["headers"]
    _pipeline(client, h)
    c = client.post("/contacts", headers=h, json={"first_name": "Champ", "email": "c@x.com"}).json()
    d = client.post("/deals", headers=h, json={"name": "Big deal"}).json()
    r = client.post(
        f"/deals/{d['id']}/participants",
        headers=h,
        json={"contact_id": c["id"], "role": "champion", "is_primary": True},
    )
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "champion"
    r = client.get(f"/deals/{d['id']}/participants", headers=h)
    assert len(r.json()) == 1
    # primary contact updated
    r = client.get(f"/deals/{d['id']}", headers=h)
    assert r.json()["primary_contact_id"] == c["id"]


def test_company_parent_and_merge(client, workspace):
    h = workspace["headers"]
    parent = client.post("/companies", headers=h, json={"name": "Parent Co", "domain": "parent.test"}).json()
    child = client.post(
        "/companies",
        headers=h,
        json={"name": "Child Co", "domain": "child.test", "parent_company_id": parent["id"]},
    ).json()
    assert child["parent_company_id"] == parent["id"]

    loser = client.post("/companies", headers=h, json={"name": "Dup Parent", "domain": "parent2.test"}).json()
    client.post("/contacts", headers=h, json={"first_name": "X", "email": "x@y.com", "company_id": loser["id"]})
    r = client.post(
        "/companies/merge",
        headers=h,
        json={"winner_id": parent["id"], "loser_id": loser["id"], "dry_run": True},
    )
    assert r.status_code == 200
    assert r.json()["references_rewritten"]["contacts"] == 1
    r = client.post(
        "/companies/merge",
        headers=h,
        json={"winner_id": parent["id"], "loser_id": loser["id"]},
    )
    assert r.status_code == 200
    assert r.json()["dry_run"] is False


def test_saved_views_seed_and_run(client, workspace):
    h = workspace["headers"]
    _pipeline(client, h)
    client.post("/deals", headers=h, json={"name": "Open A", "amount": 100})
    r = client.get("/views", headers=h)
    assert r.status_code == 200
    slugs = {v["slug"] for v in r.json()}
    assert "open_deals" in slugs
    assert "new_leads" in slugs
    r = client.post("/views/open_deals/run", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["count"] >= 1
    assert r.json()["view"]["slug"] == "open_deals"


def test_quotes_versioned(client, workspace):
    h = workspace["headers"]
    _pipeline(client, h)
    d = client.post("/deals", headers=h, json={"name": "Quote deal"}).json()
    r = client.post(
        "/quotes",
        headers=h,
        json={
            "deal_id": d["id"],
            "name": "Q1",
            "lines": [{"name": "Seats", "unit_price": 100, "quantity": 3}],
        },
    )
    assert r.status_code == 201, r.text
    q1 = r.json()
    assert q1["version"] == 1
    assert q1["total"] == 300
    assert len(q1["lines"]) == 1

    r = client.post(
        "/quotes",
        headers=h,
        json={"deal_id": d["id"], "name": "Q2", "lines": [{"name": "Seats", "unit_price": 90, "quantity": 5}]},
    )
    assert r.json()["version"] == 2

    r = client.post(
        f"/quotes/{q1['id']}/status",
        headers=h,
        json={"status": "accepted", "sync_deal_amount": True},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
    r = client.get(f"/deals/{d['id']}", headers=h)
    assert r.json()["amount"] == 300


def test_contact_channels(client, workspace):
    h = workspace["headers"]
    c = client.post("/contacts", headers=h, json={"first_name": "Multi", "email": "a@b.com"}).json()
    r = client.post(
        f"/contacts/{c['id']}/channels",
        headers=h,
        json={"channel_type": "email", "value": "work@b.com", "is_primary": True},
    )
    assert r.status_code == 201
    r = client.get(f"/contacts/{c['id']}/channels", headers=h)
    assert len(r.json()) == 1
    r = client.get(f"/contacts/{c['id']}", headers=h)
    assert r.json()["email"] == "work@b.com"
