"""HITL approval requests."""

from __future__ import annotations


def test_propose_and_list(client, workspace):
    r = client.post(
        "/approvals",
        headers=workspace["headers"],
        json={
            "action": "email.send",
            "payload": {"to": ["a@example.com"], "subject": "hi", "body": "hello"},
            "reason": "agent wants to send",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["action"] == "email.send"
    aid = body["id"]

    r = client.get("/approvals?status=pending", headers=workspace["headers"])
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()]
    assert aid in ids


def test_decide_approve_without_execute(client, workspace):
    r = client.post(
        "/approvals",
        headers=workspace["headers"],
        json={"action": "custom.review", "payload": {"note": "check this"}, "reason": "manual"},
    )
    aid = r.json()["id"]

    r = client.post(
        f"/approvals/{aid}/decide",
        headers=workspace["headers"],
        json={"approve": True, "execute": False, "note": "lgtm"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved"
    assert body["decision_note"] == "lgtm"


def test_low_privilege_key_cannot_decide(client, workspace):
    r = client.post(
        "/workspace/api-keys",
        headers=workspace["headers"],
        json={
            "name": "agent",
            "role": "member",
            "scopes": ["approvals:read", "approvals:write", "contacts:read"],
        },
    )
    assert r.status_code == 201
    agent_key = r.json()["key"]

    r = client.post(
        "/approvals",
        headers={"Authorization": f"Bearer {agent_key}"},
        json={"action": "custom.x", "payload": {}},
    )
    assert r.status_code == 201
    aid = r.json()["id"]

    r = client.post(
        f"/approvals/{aid}/decide",
        headers={"Authorization": f"Bearer {agent_key}"},
        json={"approve": True},
    )
    assert r.status_code == 403


def test_reject(client, workspace):
    r = client.post(
        "/approvals",
        headers=workspace["headers"],
        json={"action": "deal.won", "payload": {"deal_id": "nope"}},
    )
    aid = r.json()["id"]
    r = client.post(
        f"/approvals/{aid}/decide",
        headers=workspace["headers"],
        json={"approve": False, "note": "not yet"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
