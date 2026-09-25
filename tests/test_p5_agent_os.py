"""P5 Agent OS — entity_context, actor labels, agent_activity, explain_change."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import ApiKey


def test_entity_context_by_company_name(client, workspace):
    h = workspace["headers"]
    co = client.post(
        "/companies",
        headers=h,
        json={"name": "Acme Corp", "domain": "acme.com"},
    )
    assert co.status_code == 201, co.text
    cid = co.json()["id"]

    r = client.get(
        "/agent/entity-context",
        headers=h,
        params={"entity_type": "company", "entity_ref": "Acme Corp"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["protocol"] == "nakatomi.entity_context/v1"
    assert body["entity_id"] == cid
    assert body["entity"]["name"] == "Acme Corp"
    assert isinstance(body["timeline"], list)


def test_timeline_actor_label(client, workspace):
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        key = db.scalars(select(ApiKey).where(ApiKey.workspace_id == workspace["workspace_id"])).first()
        key.name = "research-agent"
        key.data = {"display_name": "Research Agent", "agent_role": "research"}
        db.commit()
    finally:
        db.close()

    h = workspace["headers"]
    co = client.post("/companies", headers=h, json={"name": "Label Co"})
    assert co.status_code == 201, co.text
    cid = co.json()["id"]
    r = client.get(f"/timeline/company/{cid}", headers=h)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items, "expected company.created timeline event"
    assert items[0].get("actor_label") == "Research Agent"


def test_agent_activity_counts(client, workspace):
    h = workspace["headers"]
    since = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    client.post("/companies", headers=h, json={"name": "Activity Co"})
    r = client.get("/agent/activity", headers=h, params={"since": since})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["protocol"] == "nakatomi.agent_activity/v1"
    assert body["timeline_events"] >= 1
    assert body["companies_created"] >= 1


def test_list_agents_roster(client, workspace):
    h = workspace["headers"]
    r = client.get("/agent/agents", headers=h)
    assert r.status_code == 200, r.text
    agents = r.json()["agents"]
    assert len(agents) >= 1


def test_explain_change(client, workspace):
    h = workspace["headers"]
    co = client.post("/companies", headers=h, json={"name": "Explain Co"})
    cid = co.json()["id"]
    r = client.get(
        "/agent/explain-change",
        headers=h,
        params={"entity_type": "company", "entity_id": cid},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["protocol"] == "nakatomi.explain_change/v1"
    assert body["timeline"]


def test_handoff_includes_entity_context(client, workspace):
    h = workspace["headers"]
    co = client.post("/companies", headers=h, json={"name": "Handoff Co"})
    cid = co.json()["id"]
    r = client.post(
        "/agent/handoff",
        headers=h,
        json={
            "entity_type": "company",
            "entity_ref": cid,
            "summary": "SDR done — AE please continue",
            "next_steps": ["Review timeline", "Advance deal"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["protocol"] == "nakatomi.handoff/v1"
    assert body["entity_context"]["entity_id"] == cid
