"""Pipelines + deals: creation, default stage pick, update, timeline events."""

from __future__ import annotations


def _make_pipeline(client, h):
    r = client.post(
        "/pipelines",
        headers=h,
        json={
            "name": "Sales",
            "slug": "sales",
            "is_default": True,
            "stages": [
                {"name": "Lead", "slug": "lead", "position": 0, "probability": 10},
                {"name": "Qualified", "slug": "qualified", "position": 1, "probability": 50},
                {"name": "Won", "slug": "won", "position": 2, "probability": 100, "is_won": True},
                {"name": "Lost", "slug": "lost", "position": 3, "probability": 0, "is_lost": True},
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_deal_lifecycle(client, workspace):
    h = workspace["headers"]
    pipe = _make_pipeline(client, h)
    lead_stage = next(s for s in pipe["stages"] if s["slug"] == "lead")
    won_stage = next(s for s in pipe["stages"] if s["slug"] == "won")

    r = client.post(
        "/deals",
        headers=h,
        json={"name": "Acme Big Deal", "amount": 12345.67, "currency": "USD"},
    )
    assert r.status_code == 201, r.text
    deal = r.json()
    assert deal["stage_id"] == lead_stage["id"]
    assert deal["status"] == "open"

    # Move to Won — status should flip via PATCH on stage_id + status.
    r = client.patch(
        f"/deals/{deal['id']}",
        headers=h,
        json={"stage_id": won_stage["id"], "status": "won"},
    )
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["status"] == "won"
    assert updated["closed_at"] is not None

    # Timeline for this deal should include the creation + stage change.
    r = client.get(f"/timeline/deal/{deal['id']}", headers=h)
    assert r.status_code == 200
    events = [e["event_type"] for e in r.json()["items"]]
    assert "deal.created" in events
    assert "deal.stage_changed" in events
