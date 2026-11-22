import json
import re
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Membership, User, WorkspaceInvitation
from app.security import hash_api_key
from app.services import account_email

ORIGIN = "https://crm.up.railway.app"
HEADERS = {"Origin": ORIGIN}
INVITATIONS = "/dashboard/members/invitations"
ACCEPT = "/auth/accept-invitation"


def _sign_in_owner(client, workspace, monkeypatch):
    monkeypatch.setattr(settings, "DASHBOARD_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(settings, "RAILWAY_PUBLIC_DOMAIN", "crm.up.railway.app")
    monkeypatch.setattr(settings, "RECOVERY_SMTP_HOST", "")
    monkeypatch.setattr(settings, "RECOVERY_RESEND_API_KEY", "")
    assert (
        client.post(
            f"{ORIGIN}/dashboard/session",
            json={"email": workspace["user_email"], "password": "testtest1234"},
            headers=HEADERS,
        ).status_code
        == 200
    )


def _invite(client, email, role="member"):
    result = client.post(f"{ORIGIN}{INVITATIONS}", data={"email": email, "role": role}, headers=HEADERS)
    assert result.status_code == 201
    link = re.search(r'id="link" value="([^"]+)"', result.text)[1]
    return result, urlsplit(link).fragment


def test_resend_invitation_joins_new_user_directly(client, workspace, monkeypatch):
    _sign_in_owner(client, workspace, monkeypatch)
    monkeypatch.setattr(settings, "RECOVERY_RESEND_API_KEY", "test-key")
    monkeypatch.setattr(settings, "RECOVERY_FROM_ADDRESS", "invitations@example.com")
    sent = []

    def deliver(request):
        sent.append(request)
        return httpx.Response(200, json={"id": "test-message"})

    mail = httpx.Client(transport=httpx.MockTransport(deliver))
    monkeypatch.setattr(account_email.httpx, "Client", lambda **kwargs: mail)
    email = "new-user@example.com"
    result, token = _invite(client, email, "readonly")
    assert "Invitation email submitted" in result.text
    assert str(sent[0].url) == "https://api.resend.com/emails"
    assert sent[0].headers["Authorization"] == "Bearer test-key"
    payload = json.loads(sent[0].content)
    assert payload["to"] == [email]
    assert f"{ORIGIN}{ACCEPT}#{token}" in payload["text"]
    with SessionLocal() as db:
        assert db.scalar(select(WorkspaceInvitation.digest)) == hash_api_key(token)

    client.cookies.clear()
    body = {"token": token, "password": "new-password-for-user"}
    assert (
        client.post(f"{ORIGIN}{ACCEPT}", data=body, headers=HEADERS, follow_redirects=False).status_code
        == 303
    )
    session = client.get(f"{ORIGIN}/dashboard/session").json()
    assert session["workspace_id"] == workspace["workspace_id"]
    assert [item["role"] for item in session["workspaces"]] == ["readonly"]
    assert client.get(f"{ORIGIN}/dashboard/members").status_code == 403
    assert client.post(f"{ORIGIN}{ACCEPT}", data=body, headers=HEADERS).status_code == 400

    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.email == email))
        memberships = db.scalars(select(Membership).where(Membership.user_id == user_id)).all()
        assert [row.workspace_id for row in memberships] == [workspace["workspace_id"]]

    teammate_cookie = client.cookies["nk_browser_session"]
    client.cookies.clear()
    _sign_in_owner(client, workspace, monkeypatch)
    member_url = f"{ORIGIN}/dashboard/members/{user_id}"
    assert (
        client.post(
            member_url, data={"action": "change", "role": "member"}, headers=HEADERS, follow_redirects=False
        ).status_code
        == 303
    )
    with SessionLocal() as db:
        assert db.scalar(select(Membership.role).where(Membership.user_id == user_id)).value == "member"
    assert (
        client.post(
            member_url, data={"action": "remove", "role": "member"}, headers=HEADERS, follow_redirects=False
        ).status_code
        == 303
    )
    with SessionLocal() as db:
        assert db.scalar(select(Membership.id).where(Membership.user_id == user_id)) is None
        assert db.get(User, user_id) is not None
    client.cookies.clear()
    client.cookies.set("nk_browser_session", teammate_cookie)
    assert client.get(f"{ORIGIN}/dashboard/session").status_code == 401


def test_existing_user_requires_authentication_and_reissue_invalidates_old_link(
    client, workspace, monkeypatch
):
    _sign_in_owner(client, workspace, monkeypatch)
    email = "existing-user@example.com"
    password = "old-password-for-user"
    assert (
        client.post(
            f"{ORIGIN}/auth/signup",
            json={
                "email": email,
                "password": password,
                "workspace_name": "Personal",
                "workspace_slug": "personal",
            },
        ).status_code
        == 200
    )
    _, revoked = _invite(client, email)
    assert (
        client.post(
            f"{ORIGIN}{INVITATIONS}/revoke", data={"email": email}, headers=HEADERS, follow_redirects=False
        ).status_code
        == 303
    )
    _, replaced = _invite(client, email)
    result, token = _invite(client, email)
    assert "Share this link privately" in result.text

    client.cookies.clear()
    for old_token in (revoked, replaced):
        assert (
            client.post(
                f"{ORIGIN}{ACCEPT}", data={"token": old_token, "password": password}, headers=HEADERS
            ).status_code
            == 400
        )
    assert (
        client.post(
            f"{ORIGIN}{ACCEPT}", data={"token": token, "password": "wrong-password"}, headers=HEADERS
        ).status_code
        == 401
    )
    assert (
        client.post(
            f"{ORIGIN}{ACCEPT}",
            data={"token": token, "password": password},
            headers=HEADERS,
            follow_redirects=False,
        ).status_code
        == 303
    )
    session = client.get(f"{ORIGIN}/dashboard/session").json()
    assert session["workspace_id"] == workspace["workspace_id"]
    assert {item["role"] for item in session["workspaces"]} == {"owner", "member"}
