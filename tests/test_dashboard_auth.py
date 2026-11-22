from urllib.parse import parse_qs, urlsplit

from app.config import settings
from app.routers import sso

ORIGIN = {"Origin": "http://testserver"}
DASHBOARD = {"X-Nakatomi-Dashboard": "1"}


def test_dashboard_session_and_agent_lifecycle(client, workspace, monkeypatch):
    monkeypatch.setattr(settings, "DASHBOARD_ENABLED", True)
    assert client.get("/dashboard").status_code == 200
    assert "Connect your API key" not in client.get("/dashboard").text
    credentials = {"email": workspace["user_email"], "password": "testtest1234"}
    assert client.post("/dashboard/session", json=credentials).status_code == 403
    response = client.post("/dashboard/session", json=credentials, headers=ORIGIN)
    assert response.status_code == 200, response.text
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "access_token" not in response.json()
    assert client.get("/workspace", headers=DASHBOARD).status_code == 200
    assert client.get("/workspace").status_code == 401
    assert (
        client.get("/workspace", headers={**DASHBOARD, "Origin": "https://other.example"}).status_code == 403
    )

    response = client.post("/dashboard/agents", json={"name": "Grok"}, headers=ORIGIN)
    assert response.status_code == 201, response.text
    token = response.json()["token"]
    agents = client.get("/dashboard/agents").json()["agents"]
    assert len(agents) == 1
    assert "deals:read" in agents[0]["scopes"]
    assert "deals:write" not in agents[0]["scopes"]
    authorization = {"Authorization": f"Bearer {token}"}
    assert client.get("/deals", headers=authorization).status_code == 200
    assert client.delete(f"/dashboard/agents/{agents[0]['id']}", headers=ORIGIN).status_code == 204
    assert client.get("/deals", headers=authorization).status_code == 401
    assert client.delete("/dashboard/session", headers=ORIGIN).status_code == 204
    assert client.get("/dashboard/session").status_code == 401


def test_dashboard_sso_requires_browser_state_and_verified_email(client, workspace, monkeypatch):
    monkeypatch.setattr(settings, "DASHBOARD_ENABLED", True)
    monkeypatch.setattr(settings, "SSO_GOOGLE_CLIENT_ID", "example")
    monkeypatch.setattr(settings, "SSO_GOOGLE_CLIENT_SECRET", "example")
    profile = {"email": workspace["user_email"], "subject": "test-subject", "email_verified": False}
    monkeypatch.setattr(sso, "_exchange_code", lambda *args: profile)
    callback = "/auth/sso/google/callback"
    response = client.get("/auth/sso/google?dashboard=true", follow_redirects=False)
    state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]
    query = {"state": state, "code": "example"}
    assert client.get(callback, params=query, follow_redirects=False).status_code == 403
    profile["email_verified"] = True
    response = client.get(callback, params=query, follow_redirects=False)
    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/dashboard"
    assert client.get("/dashboard/session").status_code == 200
    assert client.get(callback, params=query, follow_redirects=False).status_code == 400


def test_railway_discovery_uses_canonical_https_origin(client, monkeypatch):
    monkeypatch.setattr(settings, "RAILWAY_PUBLIC_DOMAIN", "nakatomi.up.railway.app")
    metadata = client.get(
        "/.well-known/oauth-protected-resource/mcp",
        headers={
            "X-Forwarded-Host": "other.example",
        },
    ).json()
    assert metadata["resource"] == "https://nakatomi.up.railway.app/mcp"
    assert metadata["authorization_servers"] == ["https://nakatomi.up.railway.app"]
    response = client.post("/mcp", json={}, headers={"Accept": "application/json, text/event-stream"})
    assert response.status_code == 401
    assert (
        'resource_metadata="https://nakatomi.up.railway.app/.well-known/oauth-protected-resource/mcp"'
        in (response.headers["www-authenticate"])
    )
