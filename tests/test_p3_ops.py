"""P3: policies, jobs, dead-letters, forensics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def test_policies_required_fields_block_deal(client, workspace):
    h = workspace["headers"]
    client.post(
        "/pipelines",
        headers=h,
        json={
            "name": "S",
            "slug": "s-p3",
            "is_default": True,
            "stages": [{"name": "L", "slug": "lead", "position": 0, "probability": 10}],
        },
    )
    # set policy: deal.won requires primary_contact_id
    r = client.put(
        "/policies",
        headers=h,
        json={
            "policies": {
                "block": [
                    {
                        "action": "deal.won",
                        "when": {"missing": ["primary_contact_id"]},
                        "message": "cannot win without primary contact",
                        "suggestion": "set primary_contact_id first",
                    }
                ]
            }
        },
    )
    assert r.status_code == 200, r.text
    d = client.post("/deals", headers=h, json={"name": "No contact"}).json()
    r = client.patch(f"/deals/{d['id']}", headers=h, json={"status": "won"})
    assert r.status_code == 422
    assert "policy" in r.json()["detail"].lower() or "primary" in r.json()["detail"].lower()


def test_policies_auto_task_on_lead(client, workspace):
    h = workspace["headers"]
    r = client.put(
        "/policies",
        headers=h,
        json={
            "policies": {
                "auto_tasks": [{"on": "lead.created", "title": "Qualify this lead"}],
            }
        },
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/leads",
        headers=h,
        json={"email": "auto@example.com", "first_name": "Auto"},
    )
    assert r.status_code == 201, r.text
    r = client.get("/tasks", headers=h)
    assert r.status_code == 200
    titles = [t["title"] for t in r.json()["items"]]
    assert any("Qualify" in t for t in titles)


def test_job_export_sync(client, workspace):
    h = workspace["headers"]
    r = client.post(
        "/jobs",
        headers=h,
        json={"job_type": "export", "input": {"include_timeline": False}, "run_async": False},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert "export_keys" in body["result"] or body["result"]


def test_job_poll(client, workspace):
    h = workspace["headers"]
    r = client.post(
        "/jobs",
        headers=h,
        json={"job_type": "custom", "input": {"hello": "world"}, "run_async": False},
    )
    jid = r.json()["id"]
    r = client.get(f"/jobs/{jid}", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "completed"


def test_dead_letters_empty(client, workspace):
    r = client.get("/webhooks/dead-letters", headers=workspace["headers"])
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_audit_and_as_of(client, workspace):
    h = workspace["headers"]
    c = client.post(
        "/contacts",
        headers=h,
        json={"first_name": "Time", "last_name": "Travel", "email": "tt@x.com"},
    ).json()
    # mutate
    client.patch(f"/contacts/{c['id']}", headers=h, json={"title": "Engineer"})
    r = client.get("/audit", headers=h, params={"entity_type": "contact", "entity_id": c["id"]})
    assert r.status_code == 200
    assert len(r.json()["items"]) >= 1

    # as-of: slightly in the future still has title; far past may reverse
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    r = client.get(
        f"/entities/contact/{c['id']}/as-of",
        headers=h,
        params={"ts": future},
    )
    assert r.status_code == 200
    assert r.json()["exists"] is True
    assert r.json()["state"]["first_name"] == "Time"

    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    r = client.get(
        f"/entities/contact/{c['id']}/as-of",
        headers=h,
        params={"ts": past},
    )
    # created after past → does not exist yet
    assert r.status_code == 200
    assert r.json()["exists"] is False
