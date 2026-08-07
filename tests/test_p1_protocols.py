"""P1: A2A agent card, ACP context, A2A tasks, discovery."""

from __future__ import annotations


def test_discovery_index(client, workspace):
    r = client.get("/discovery")
    assert r.status_code == 200
    body = r.json()
    assert body["version"]
    links = body["links"]
    for key in ("schema", "mcp", "agent_card", "acp_context", "a2a_tasks", "openapi"):
        assert key in links


def test_agent_card_dynamic(client, workspace):
    r = client.get("/.well-known/agent-card.json")
    assert r.status_code == 200
    card = r.json()
    assert card["name"] == "Nakatomi CRM"
    assert "skills" in card and len(card["skills"]) >= 4
    assert "securitySchemes" in card
    assert card["nakatomi"]["transports"]
    # legacy path
    r2 = client.get("/.well-known/agent.json")
    assert r2.status_code == 200
    assert r2.json()["name"] == card["name"]


def test_agent_card_extended_with_auth(client, workspace):
    r = client.get("/.well-known/agent-card.json", headers=workspace["headers"])
    assert r.status_code == 200
    assert r.json()["nakatomi"].get("extended") is True


def test_acp_context_pack(client, workspace):
    r = client.get("/acp/context", headers=workspace["headers"])
    assert r.status_code == 200, r.text
    pack = r.json()
    assert pack["protocol"] == "nakatomi.acp/v1"
    assert pack["workspace"]["id"] == workspace["workspace_id"]
    assert "entities" in pack
    assert "pipelines" in pack
    assert "policies" in pack
    assert "scopes_on_this_key" in pack["policies"]
    assert "*" in pack["policies"]["scopes_on_this_key"] or "contacts:read" in pack["policies"]["scopes_on_this_key"]
    assert "hints" in pack and pack["hints"]
    assert "etag" in pack
    etag = pack["etag"]
    r2 = client.get(
        "/acp/context",
        headers={**workspace["headers"], "If-None-Match": f'"{etag}"'},
    )
    assert r2.status_code == 304


def test_acp_context_sections(client, workspace):
    r = client.get("/acp/context?sections=hints,policies", headers=workspace["headers"])
    assert r.status_code == 200
    pack = r.json()
    assert "hints" in pack
    assert "policies" in pack
    assert "pipelines" not in pack  # filtered out


def test_a2a_task_lifecycle(client, workspace):
    h = workspace["headers"]
    r = client.post(
        "/a2a/tasks",
        headers=h,
        json={"title": "Enrich Acme", "skill": "contact-hygiene", "input": {"domain": "acme.com"}},
    )
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["status"] == "working"
    tid = task["id"]
    assert task["context_url"] == "/acp/context"

    r = client.post(
        f"/a2a/tasks/{tid}/messages",
        headers=h,
        json={"role": "agent", "text": "looking up domain"},
    )
    assert r.status_code == 200
    assert len(r.json()["messages"]) >= 2

    r = client.post(
        f"/a2a/tasks/{tid}/complete",
        headers=h,
        json={"result": {"company_id": "x"}, "artifact": {"name": "notes", "data": {"ok": True}}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"
    assert r.json()["result"]["company_id"] == "x"
    assert len(r.json()["artifacts"]) == 1


def test_a2a_task_hitl_approval(client, workspace):
    h = workspace["headers"]
    r = client.post(
        "/a2a/tasks",
        headers=h,
        json={
            "title": "Send risky email",
            "skill": "approvals-hitl",
            "require_approval": True,
            "input": {"to": ["x@y.com"]},
        },
    )
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["status"] == "input_required"
    assert task["linked_approval_id"]

    # approve → task resumes to working
    r = client.post(
        f"/approvals/{task['linked_approval_id']}/decide",
        headers=h,
        json={"approve": True, "execute": False},
    )
    assert r.status_code == 200
    r = client.get(f"/a2a/tasks/{task['id']}", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "working"


def test_a2a_cancel(client, workspace):
    h = workspace["headers"]
    r = client.post("/a2a/tasks", headers=h, json={"title": "temp"})
    tid = r.json()["id"]
    r = client.post(f"/a2a/tasks/{tid}/cancel", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "canceled"
