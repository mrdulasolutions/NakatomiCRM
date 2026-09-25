"""Capability scopes on API keys."""

from __future__ import annotations

from app.scopes import (
    DEFAULT_AGENT_SCOPES,
    default_scopes_for_role,
    has_scope,
    missing_scopes,
    normalize_scopes,
)


def test_has_scope_star():
    assert has_scope(["*"], "contacts:write")
    assert has_scope(["*"], "email:send")
    assert has_scope(["*"], "admin:keys")


def test_has_scope_write_implies_read():
    assert has_scope(["contacts:write"], "contacts:read")
    assert not has_scope(["contacts:read"], "contacts:write")


def test_has_scope_star_read():
    assert has_scope(["*:read"], "deals:read")
    assert not has_scope(["*:read"], "deals:write")


def test_normalize_empty_is_full():
    assert normalize_scopes(None) == ["*"]
    assert normalize_scopes([]) == ["*"]


def test_default_roles():
    assert default_scopes_for_role("owner") == ["*"]
    assert default_scopes_for_role("admin") == ["*"]
    assert "contacts:write" in default_scopes_for_role("member")
    assert "email:send" not in default_scopes_for_role("member")
    assert "admin:keys" not in default_scopes_for_role("member")
    ro = default_scopes_for_role("readonly")
    assert "contacts:read" in ro
    assert "contacts:write" not in ro


def test_missing_scopes():
    assert missing_scopes(DEFAULT_AGENT_SCOPES, "email:send") == ["email:send"]
    assert missing_scopes(["*"], "email:send") == []


def test_create_key_with_scopes(client, workspace):
    r = client.post(
        "/workspace/api-keys",
        headers=workspace["headers"],
        json={"name": "agent-ro", "role": "member", "scopes": ["contacts:read", "companies:read"]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["scopes"] == ["contacts:read", "companies:read"]
    key = body["key"]

    # can list contacts
    r = client.get("/contacts", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200

    # cannot create contacts
    r = client.post(
        "/contacts",
        headers={"Authorization": f"Bearer {key}"},
        json={"first_name": "Nope", "email": "nope@example.com"},
    )
    assert r.status_code == 403
    assert (
        "missing scopes" in r.json()["detail"].lower()
        or "missing scopes" in r.json().get("error", "").lower()
    )


def test_default_member_key_blocks_email_send(client, workspace):
    r = client.post(
        "/workspace/api-keys",
        headers=workspace["headers"],
        json={"name": "agent", "role": "member"},
    )
    assert r.status_code == 201
    key = r.json()["key"]
    scopes = r.json()["scopes"]
    assert "email:send" not in scopes
    assert "contacts:write" in scopes

    r = client.post(
        "/email/send",
        headers={"Authorization": f"Bearer {key}"},
        json={"to": ["x@example.com"], "subject": "hi", "body": "yo"},
    )
    assert r.status_code == 403
