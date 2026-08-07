"""Idempotency-Key replay on mutating routes."""

from __future__ import annotations


def test_create_contact_idempotent_replay(client, workspace):
    headers = {
        **workspace["headers"],
        "Idempotency-Key": "contact-create-1",
    }
    payload = {"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com"}
    r1 = client.post("/contacts", headers=headers, json=payload)
    assert r1.status_code == 201, r1.text
    body1 = r1.json()
    assert body1["email"] == "ada@example.com"
    cid = body1["id"]

    r2 = client.post("/contacts", headers=headers, json=payload)
    assert r2.status_code == 201
    assert r2.headers.get("Idempotent-Replay") == "true"
    body2 = r2.json()
    assert body2["id"] == cid

    # only one contact in the workspace
    r = client.get("/contacts", headers=workspace["headers"])
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_idempotency_key_conflict_on_different_body(client, workspace):
    headers = {
        **workspace["headers"],
        "Idempotency-Key": "same-key",
    }
    r1 = client.post(
        "/contacts",
        headers=headers,
        json={"first_name": "One", "email": "one@example.com"},
    )
    assert r1.status_code == 201
    r2 = client.post(
        "/contacts",
        headers=headers,
        json={"first_name": "Two", "email": "two@example.com"},
    )
    assert r2.status_code == 409


def test_request_id_header(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers.get("X-Request-Id")


def test_health_deep(client):
    r = client.get("/health/deep")
    assert r.status_code == 200
    assert r.json()["db"] == "up"
