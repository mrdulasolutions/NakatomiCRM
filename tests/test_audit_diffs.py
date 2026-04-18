"""Row-level audit diffs: timeline events carry before/after per field."""

from __future__ import annotations


def _latest_event(client, h, entity_type: str, entity_id: str, event_type: str) -> dict:
    r = client.get(f"/timeline/{entity_type}/{entity_id}?limit=20", headers=h)
    for e in r.json()["items"]:
        if e["event_type"] == event_type:
            return e
    raise AssertionError(f"no {event_type} event on {entity_type}:{entity_id}")


def test_contact_update_records_field_diff(client, workspace):
    h = workspace["headers"]
    c = client.post("/contacts", headers=h, json={"first_name": "Ada", "title": "mathematician"}).json()

    r = client.patch(
        f"/contacts/{c['id']}",
        headers=h,
        json={"title": "Rear Admiral"},
    )
    assert r.status_code == 200

    ev = _latest_event(client, h, "contact", c["id"], "contact.updated")
    changes = ev["payload"]["changes"]
    assert changes == {"title": {"from": "mathematician", "to": "Rear Admiral"}}


def test_no_op_patch_produces_empty_changes(client, workspace):
    h = workspace["headers"]
    c = client.post("/contacts", headers=h, json={"first_name": "Ada", "title": "x"}).json()

    client.patch(f"/contacts/{c['id']}", headers=h, json={"title": "x"})

    ev = _latest_event(client, h, "contact", c["id"], "contact.updated")
    # Same value in and out — SA history reports no change, so the dict is empty.
    assert ev["payload"]["changes"] == {}


def test_multi_field_patch_captures_every_diff(client, workspace):
    h = workspace["headers"]
    c = client.post(
        "/contacts",
        headers=h,
        json={"first_name": "Grace", "last_name": "Hopper", "title": "lieutenant"},
    ).json()

    client.patch(
        f"/contacts/{c['id']}",
        headers=h,
        json={"last_name": "Hopper-USN", "title": "Rear Admiral"},
    )

    ev = _latest_event(client, h, "contact", c["id"], "contact.updated")
    changes = ev["payload"]["changes"]
    assert changes["last_name"] == {"from": "Hopper", "to": "Hopper-USN"}
    assert changes["title"] == {"from": "lieutenant", "to": "Rear Admiral"}
    # first_name wasn't touched — not in the diff.
    assert "first_name" not in changes


def test_deal_patch_captures_amount_and_stage_changes(client, workspace):
    h = workspace["headers"]
    pipe = client.post(
        "/pipelines",
        headers=h,
        json={
            "name": "Sales",
            "slug": "sales",
            "is_default": True,
            "stages": [
                {"name": "Lead", "slug": "lead", "position": 0, "probability": 10},
                {"name": "Won", "slug": "won", "position": 1, "probability": 100, "is_won": True},
            ],
        },
    ).json()
    won = next(s for s in pipe["stages"] if s["slug"] == "won")

    deal = client.post(
        "/deals",
        headers=h,
        json={"name": "Big", "amount": 1000.0, "currency": "USD"},
    ).json()

    client.patch(
        f"/deals/{deal['id']}",
        headers=h,
        json={"amount": 2500.0, "stage_id": won["id"], "status": "won"},
    )

    ev = _latest_event(client, h, "deal", deal["id"], "deal.updated")
    changes = ev["payload"]["changes"]
    # Decimals coerce to float in the diff payload.
    assert changes["amount"] == {"from": 1000.0, "to": 2500.0}
    assert changes["stage_id"]["from"] != changes["stage_id"]["to"]
    assert changes["status"] == {"from": "open", "to": "won"}


def test_null_to_value_and_value_to_null(client, workspace):
    h = workspace["headers"]
    c = client.post("/contacts", headers=h, json={"first_name": "X"}).json()

    # Null → value.
    client.patch(f"/contacts/{c['id']}", headers=h, json={"title": "CEO"})
    ev1 = _latest_event(client, h, "contact", c["id"], "contact.updated")
    assert ev1["payload"]["changes"]["title"] == {"from": None, "to": "CEO"}

    # Value → null.
    client.patch(f"/contacts/{c['id']}", headers=h, json={"title": None})
    ev2 = _latest_event(client, h, "contact", c["id"], "contact.updated")
    assert ev2["payload"]["changes"]["title"] == {"from": "CEO", "to": None}
