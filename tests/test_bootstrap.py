"""POST /bootstrap + welcome page contract tests.

Bootstrap is a one-shot endpoint: it must work exactly once on a fresh
DB and refuse forever after. Tests verify both halves plus the
HTML form path."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_root_serves_welcome_html_on_fresh_install(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "Welcome to Nakatomi" in body
    assert 'name="email"' in body
    assert 'name="workspace_slug"' in body


def test_root_serves_json_after_init(client: TestClient) -> None:
    payload = {
        "email": "owner@example.com",
        "password": "hunter2hunter2",
        "display_name": "Owner",
        "workspace_name": "First",
        "workspace_slug": "first",
    }
    r = client.post("/bootstrap", json=payload)
    assert r.status_code == 200, r.text
    r = client.get("/")
    assert "application/json" in r.headers["content-type"]
    body = r.json()
    assert body["name"] == "Nakatomi CRM"
    assert body["mcp"] == "/mcp"


def test_bootstrap_creates_user_workspace_apikey(client: TestClient) -> None:
    payload = {
        "email": "owner@example.com",
        "password": "hunter2hunter2",
        "display_name": "Owner",
        "workspace_name": "Acme",
        "workspace_slug": "acme",
    }
    r = client.post("/bootstrap", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "owner@example.com"
    assert body["workspace_slug"] == "acme"
    assert body["api_key"].startswith("nk_")
    assert body["api_key_prefix"]
    assert body["user_id"] and body["workspace_id"]

    # API key works against an authenticated route
    headers = {"Authorization": f"Bearer {body['api_key']}"}
    r = client.get("/contacts", headers=headers)
    assert r.status_code == 200, r.text


def test_bootstrap_refuses_when_users_exist(client: TestClient) -> None:
    payload = {
        "email": "first@example.com",
        "password": "hunter2hunter2",
        "workspace_name": "First",
        "workspace_slug": "first",
    }
    r = client.post("/bootstrap", json=payload)
    assert r.status_code == 200

    # second call must be rejected
    payload2 = {**payload, "email": "second@example.com", "workspace_slug": "second"}
    r = client.post("/bootstrap", json=payload2)
    assert r.status_code == 409
    assert "already initialized" in r.json()["detail"].lower()


def test_bootstrap_rejects_short_password(client: TestClient) -> None:
    r = client.post(
        "/bootstrap",
        json={
            "email": "x@example.com",
            "password": "short",
            "workspace_name": "X",
            "workspace_slug": "x",
        },
    )
    assert r.status_code == 422


def test_bootstrap_rejects_bad_slug(client: TestClient) -> None:
    r = client.post(
        "/bootstrap",
        json={
            "email": "x@example.com",
            "password": "hunter2hunter2",
            "workspace_name": "X",
            "workspace_slug": "Has Spaces",
        },
    )
    assert r.status_code == 422


def test_welcome_form_submission_returns_html_with_key(client: TestClient) -> None:
    r = client.post(
        "/welcome/signup",
        data={
            "email": "form@example.com",
            "password": "hunter2hunter2",
            "display_name": "Form User",
            "workspace_name": "Form WS",
            "workspace_slug": "form",
        },
    )
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "Nakatomi is yours." in body
    assert "form@example.com" in body
    # API key surfaces in the rendered success page exactly once
    assert "nk_" in body


def test_welcome_form_rerenders_form_on_already_initialized(client: TestClient) -> None:
    client.post(
        "/bootstrap",
        json={
            "email": "first@example.com",
            "password": "hunter2hunter2",
            "workspace_name": "First",
            "workspace_slug": "first",
        },
    )
    r = client.post(
        "/welcome/signup",
        data={
            "email": "second@example.com",
            "password": "hunter2hunter2",
            "workspace_name": "Second",
            "workspace_slug": "second",
        },
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "already initialized"
