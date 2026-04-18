"""Signup / login / me, plus the auth error paths."""

from __future__ import annotations


def test_signup_login_me(client):
    email = "owner@example.com"
    password = "correct-horse-battery-staple"

    r = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": password,
            "workspace_name": "Acme",
            "workspace_slug": "acme",
            "display_name": "Owner",
        },
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    ws_slug = r.json()["workspace_slug"]

    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200

    r = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}", "X-Workspace": ws_slug},
    )
    assert r.status_code == 200
    assert r.json()["email"] == email


def test_missing_auth(client):
    r = client.get("/contacts")
    assert r.status_code == 401


def test_bad_api_key(client):
    r = client.get("/contacts", headers={"Authorization": "Bearer nk_bogus_key"})
    assert r.status_code == 401


def test_api_key_round_trip(client, workspace):
    r = client.get("/contacts", headers=workspace["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body == {"items": [], "next_cursor": None, "count": 0}
