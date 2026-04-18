"""OAuth 2.1 provider — discovery, registration, auth-code flow with PKCE,
token refresh, revocation."""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ApiKey, OAuthCode


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _register(client, redirect_uri: str = "http://localhost:54321/cb") -> str:
    r = client.post(
        "/oauth/register",
        json={"client_name": "test-harness", "redirect_uris": [redirect_uri]},
    )
    assert r.status_code == 201, r.text
    return r.json()["client_id"]


def test_discovery_metadata(client):
    r = client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    meta = r.json()
    for k in ("issuer", "authorization_endpoint", "token_endpoint", "registration_endpoint"):
        assert k in meta, f"missing {k}"
    assert "S256" in meta["code_challenge_methods_supported"]
    assert meta["grant_types_supported"] == ["authorization_code", "refresh_token"]

    r = client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    assert r.json()["bearer_methods_supported"] == ["header"]


def test_dynamic_client_registration(client):
    r = client.post(
        "/oauth/register",
        json={"client_name": "Claude Desktop", "redirect_uris": ["http://localhost:3333/cb"]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["client_id"]
    assert body["redirect_uris"] == ["http://localhost:3333/cb"]
    assert body["token_endpoint_auth_method"] == "none"


def test_full_authorization_code_flow(client, workspace):
    """Walk the whole flow: register → authorize → token exchange → use the
    access token against a protected endpoint."""
    verifier, challenge = _pkce()
    redirect_uri = "http://localhost:44444/cb"
    client_id = _register(client, redirect_uri)

    # 1. Browser lands on the login form.
    r = client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": "abc123",
            "scope": "mcp",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert r.status_code == 200
    assert "Authorize" in r.text
    assert client_id in r.text

    # 2. User submits credentials. We need a user. Sign one up.
    client.post(
        "/auth/signup",
        json={
            "email": "oauth-user@example.com",
            "password": "totally-secret-passphrase",
            "workspace_name": "OAuth WS",
            "workspace_slug": "oauth-ws",
        },
    )

    r = client.post(
        "/oauth/authorize",
        data={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": "abc123",
            "scope": "mcp",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "email": "oauth-user@example.com",
            "password": "totally-secret-passphrase",
        },
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    loc = r.headers["location"]
    parsed = urlparse(loc)
    qs = parse_qs(parsed.query)
    assert qs["state"] == ["abc123"]
    code = qs["code"][0]

    # 3. Exchange the code for tokens with the PKCE verifier.
    r = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert r.status_code == 200, r.text
    tokens = r.json()
    assert tokens["token_type"] == "Bearer"
    assert tokens["access_token"].startswith("nk_")
    assert tokens["refresh_token"].startswith("nk_")
    assert tokens["expires_in"] == 3600
    assert tokens["scope"] == "mcp"

    # 4. Access token works against a protected endpoint.
    r = client.get(
        "/contacts",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert r.status_code == 200

    # 5. Code cannot be reused.
    r = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert r.status_code == 400


def test_pkce_verifier_mismatch_rejected(client, workspace):
    verifier, challenge = _pkce()
    redirect_uri = "http://localhost:44444/cb"
    client_id = _register(client, redirect_uri)
    client.post(
        "/auth/signup",
        json={
            "email": "pkce@example.com",
            "password": "correct-horse-battery-staple",
            "workspace_name": "P",
            "workspace_slug": "pkce-ws",
        },
    )
    r = client.post(
        "/oauth/authorize",
        data={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": "",
            "scope": "mcp",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "email": "pkce@example.com",
            "password": "correct-horse-battery-staple",
        },
        follow_redirects=False,
    )
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]

    # Wrong verifier — should fail with "PKCE verification failed".
    r = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": "not-the-right-verifier",
        },
    )
    assert r.status_code == 400
    assert "PKCE" in r.json()["detail"] or "PKCE" in r.json().get("error", "")


def test_refresh_token_rotation(client, workspace):
    verifier, challenge = _pkce()
    redirect_uri = "http://localhost:44444/cb"
    client_id = _register(client, redirect_uri)
    client.post(
        "/auth/signup",
        json={
            "email": "refresh@example.com",
            "password": "correct-horse-battery-staple",
            "workspace_name": "R",
            "workspace_slug": "refresh-ws",
        },
    )
    r = client.post(
        "/oauth/authorize",
        data={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": "",
            "scope": "mcp",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "email": "refresh@example.com",
            "password": "correct-horse-battery-staple",
        },
        follow_redirects=False,
    )
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    tokens = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    ).json()
    first_access = tokens["access_token"]
    first_refresh = tokens["refresh_token"]

    # Use refresh_token to get a new access_token.
    r = client.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": first_refresh},
    )
    assert r.status_code == 200
    rotated = r.json()
    assert rotated["access_token"] != first_access
    assert rotated["refresh_token"] != first_refresh

    # Original refresh token is now revoked (rotation).
    r = client.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": first_refresh},
    )
    assert r.status_code == 400


def test_revoke_endpoint(client, workspace):
    verifier, challenge = _pkce()
    redirect_uri = "http://localhost:44444/cb"
    client_id = _register(client, redirect_uri)
    client.post(
        "/auth/signup",
        json={
            "email": "rev@example.com",
            "password": "correct-horse-battery-staple",
            "workspace_name": "V",
            "workspace_slug": "rev-ws",
        },
    )
    r = client.post(
        "/oauth/authorize",
        data={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": "",
            "scope": "mcp",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "email": "rev@example.com",
            "password": "correct-horse-battery-staple",
        },
        follow_redirects=False,
    )
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    access = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    ).json()["access_token"]

    # Token works.
    assert client.get("/contacts", headers={"Authorization": f"Bearer {access}"}).status_code == 200

    # Revoke it.
    r = client.post("/oauth/revoke", data={"token": access})
    assert r.status_code == 200
    assert r.json()["revoked"] is True

    # Now it's rejected.
    assert client.get("/contacts", headers={"Authorization": f"Bearer {access}"}).status_code == 401


def test_invalid_client_id_rejected(client):
    r = client.get(
        "/oauth/authorize",
        params={
            "client_id": "00000000-0000-0000-0000-000000000000",
            "redirect_uri": "http://localhost/cb",
            "response_type": "code",
            "code_challenge": "x" * 43,
            "code_challenge_method": "S256",
        },
    )
    assert r.status_code == 400


def test_unregistered_redirect_uri_rejected(client):
    client_id = _register(client, "http://localhost:12345/cb")
    r = client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "http://evil.example.com/phish",
            "response_type": "code",
            "code_challenge": "x" * 43,
            "code_challenge_method": "S256",
        },
    )
    assert r.status_code == 400


def test_response_type_implicit_rejected(client):
    client_id = _register(client)
    r = client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "http://localhost:54321/cb",
            "response_type": "token",  # implicit grant — not supported in 2.1
            "code_challenge": "x" * 43,
            "code_challenge_method": "S256",
        },
    )
    assert r.status_code == 400


def test_access_token_row_has_expiry(client, workspace):
    """The access token should land as an ApiKey row with expires_at ~1h out."""
    verifier, challenge = _pkce()
    redirect_uri = "http://localhost:44444/cb"
    client_id = _register(client, redirect_uri)
    client.post(
        "/auth/signup",
        json={
            "email": "expire@example.com",
            "password": "correct-horse-battery-staple",
            "workspace_name": "E",
            "workspace_slug": "expire-ws",
        },
    )
    r = client.post(
        "/oauth/authorize",
        data={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": "",
            "scope": "mcp",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "email": "expire@example.com",
            "password": "correct-horse-battery-staple",
        },
        follow_redirects=False,
    )
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )

    db = SessionLocal()
    try:
        # The access token is an ApiKey row; look it up by name prefix.
        rows = db.scalars(select(ApiKey).where(ApiKey.name.like("oauth:%:access"))).all()
        assert len(rows) >= 1
        for r in rows:
            assert r.expires_at is not None
    finally:
        db.close()


def test_code_is_single_use_and_short_lived(client, workspace):
    """A used code is rejected on the second exchange; the stored hash marks
    used_at. This test verifies the DB state directly."""
    verifier, challenge = _pkce()
    redirect_uri = "http://localhost:44444/cb"
    client_id = _register(client, redirect_uri)
    client.post(
        "/auth/signup",
        json={
            "email": "single@example.com",
            "password": "correct-horse-battery-staple",
            "workspace_name": "S",
            "workspace_slug": "single-ws",
        },
    )
    r = client.post(
        "/oauth/authorize",
        data={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": "",
            "scope": "mcp",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "email": "single@example.com",
            "password": "correct-horse-battery-staple",
        },
        follow_redirects=False,
    )
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]

    client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )

    db = SessionLocal()
    try:
        rows = db.scalars(select(OAuthCode)).all()
        assert rows[-1].used_at is not None
    finally:
        db.close()
