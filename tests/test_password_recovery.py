import getpass
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select

from app.cli import main
from app.config import settings
from app.db import SessionLocal
from app.models import BrowserSession, PasswordReset
from app.routers import password_recovery
from app.security import hash_api_key
from app.services import account_email


def _recovery_config(monkeypatch, origin="http://localhost:8000"):
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", origin)
    monkeypatch.setattr(settings, "RECOVERY_RESEND_API_KEY", "")
    monkeypatch.setattr(settings, "RECOVERY_SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "RECOVERY_FROM_ADDRESS", "recovery@example.com")


def test_recovery_restores_existing_dashboard_account(client, workspace, monkeypatch):
    origin = "http://localhost:8000"
    _recovery_config(monkeypatch, origin)
    monkeypatch.setattr(settings, "DASHBOARD_ENABLED", True)
    sent = []
    monkeypatch.setattr(password_recovery, "send_reset_email", lambda *args: sent.append(args))
    credentials = {"email": workspace["user_email"], "password": "testtest1234"}
    assert client.post("/dashboard/session", json=credentials, headers={"origin": origin}).status_code == 200
    browser_cookie = client.cookies["nk_browser_session"]

    response = client.post("/auth/forgot-password", data={"email": credentials["email"]})
    missing = client.post("/auth/forgot-password", data={"email": "unknown@example.com"})
    assert response.text == missing.text
    assert response.headers["Cache-Control"] == "no-store"
    assert client.post("/auth/forgot-password", data={"email": credentials["email"]}).status_code == 200
    assert len(sent) == 1
    email, link = sent[0]
    assert email == credentials["email"]
    assert link.startswith(f"{origin}/auth/reset-password#")
    token = urlsplit(link).fragment
    with SessionLocal() as db:
        assert db.scalar(select(PasswordReset.digest)) == hash_api_key(token)
    body = {"token": token, "password": "replacement-password", "confirm": "replacement-password"}
    assert client.post("/auth/reset-password", data={**body, "confirm": "does-not-match"}).status_code == 400
    assert client.post("/auth/reset-password", data=body).status_code == 200
    assert client.post("/auth/reset-password", data=body).status_code == 400
    with SessionLocal() as db:
        assert db.get(BrowserSession, hash_api_key(browser_cookie)) is None
    assert client.post("/auth/login", json=credentials).status_code == 401
    signed_in = client.post("/auth/login", json={**credentials, "password": body["password"]})
    assert signed_in.status_code == 200
    assert signed_in.json()["workspace_id"] == workspace["workspace_id"]
    assert client.get("/auth/me", headers=workspace["headers"]).status_code == 200


def test_railway_links_use_canonical_host_and_expire(client, workspace, monkeypatch):
    _recovery_config(monkeypatch, "")
    monkeypatch.setattr(settings, "RAILWAY_PUBLIC_DOMAIN", "crm.up.railway.app")
    monkeypatch.setattr(settings, "RECOVERY_SMTP_HOST", "")
    monkeypatch.setattr(settings, "RECOVERY_RESEND_API_KEY", "test-key")
    sent = []

    def deliver(request):
        sent.append(request)
        return httpx.Response(200, json={"id": "test-message"})

    http_client = httpx.Client(transport=httpx.MockTransport(deliver))
    monkeypatch.setattr(account_email.httpx, "Client", lambda **kwargs: http_client)
    client.post(
        "/auth/forgot-password",
        data={"email": workspace["user_email"]},
        headers={
            "X-Forwarded-Host": "unexpected.example.com",
        },
    )
    assert len(sent) == 1
    assert str(sent[0].url) == "https://api.resend.com/emails"
    assert sent[0].headers["Authorization"] == "Bearer test-key"
    message = json.loads(sent[0].content)
    assert message["from"] == "recovery@example.com"
    assert message["to"] == [workspace["user_email"]]
    link = message["text"].splitlines()[2]
    assert link.startswith("https://crm.up.railway.app/auth/reset-password#")
    with SessionLocal.begin() as db:
        db.scalar(select(PasswordReset)).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    response = client.post(
        "/auth/reset-password",
        data={
            "token": urlsplit(link).fragment,
            "password": "replacement-password",
            "confirm": "replacement-password",
        },
    )
    assert response.status_code == 400


def test_operator_can_reset_without_email(client, workspace, monkeypatch):
    monkeypatch.setattr(settings, "RECOVERY_SMTP_HOST", "")
    monkeypatch.setattr(getpass, "getpass", lambda _: "operator-reset-password")
    assert "installation operator" in client.get("/auth/forgot-password").text
    assert main(["reset-password", "--email", workspace["user_email"]]) == 0
    response = client.post(
        "/auth/login",
        json={
            "email": workspace["user_email"],
            "password": "operator-reset-password",
        },
    )
    assert response.status_code == 200
    assert response.json()["user_id"] == workspace["user_id"]
