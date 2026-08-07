"""Optional Google / GitHub SSO for human operators.

Enable a provider by setting its client id + secret. Discovery:

    GET /auth/sso/providers  → which providers are configured

Flow (authorization code):

    GET  /auth/sso/{provider}            → 302 to IdP
    GET  /auth/sso/{provider}/callback   → exchange code, issue JWT

Agents continue to use API keys / MCP OAuth — this is for dashboard and
human operators only. See docs/SSO.md.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import MemberRole, Membership, User, Workspace
from app.schemas import TokenResponse
from app.security import create_access_token

router = APIRouter(prefix="/auth/sso", tags=["auth"])

_STATE_TTL_SECONDS = 600
_PROVIDERS = ("google", "github")


def _enabled_providers() -> dict[str, bool]:
    return {
        "google": bool(settings.SSO_GOOGLE_CLIENT_ID and settings.SSO_GOOGLE_CLIENT_SECRET),
        "github": bool(settings.SSO_GITHUB_CLIENT_ID and settings.SSO_GITHUB_CLIENT_SECRET),
    }


def _public_base(request: Request) -> str:
    if settings.PUBLIC_BASE_URL.strip():
        return settings.PUBLIC_BASE_URL.strip().rstrip("/")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def _sign_state(provider: str, nonce: str) -> str:
    payload = {"p": provider, "n": nonce}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _verify_state(state: str, provider: str) -> None:
    try:
        data = jwt.decode(state, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=400, detail="invalid SSO state") from exc
    if data.get("p") != provider or not data.get("n"):
        raise HTTPException(status_code=400, detail="SSO state provider mismatch")


def _slugify(email: str) -> str:
    local = email.split("@", 1)[0].lower()
    slug = re.sub(r"[^a-z0-9]+", "-", local).strip("-")[:40] or "user"
    return slug


@router.get("/providers")
def list_providers() -> dict[str, Any]:
    enabled = _enabled_providers()
    return {
        "enabled": enabled,
        "any": any(enabled.values()),
        "auto_create_workspace": settings.SSO_AUTO_CREATE_WORKSPACE,
        "docs": "/docs/SSO.md",
    }


@router.get("/{provider}")
def sso_start(provider: str, request: Request) -> RedirectResponse:
    provider = provider.lower()
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail=f"unknown SSO provider: {provider}")
    if not _enabled_providers().get(provider):
        raise HTTPException(status_code=503, detail=f"SSO provider '{provider}' is not configured")

    nonce = secrets.token_urlsafe(16)
    state = _sign_state(provider, nonce)
    base = _public_base(request)
    redirect_uri = f"{base}/auth/sso/{provider}/callback"

    if provider == "google":
        params = {
            "client_id": settings.SSO_GOOGLE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    else:
        params = {
            "client_id": settings.SSO_GITHUB_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": "read:user user:email",
            "state": state,
        }
        url = "https://github.com/login/oauth/authorize?" + urlencode(params)

    return RedirectResponse(url, status_code=302)


@router.get("/{provider}/callback", response_model=TokenResponse)
def sso_callback(
    provider: str,
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
) -> TokenResponse:
    provider = provider.lower()
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail=f"unknown SSO provider: {provider}")
    if not _enabled_providers().get(provider):
        raise HTTPException(status_code=503, detail=f"SSO provider '{provider}' is not configured")
    _verify_state(state, provider)

    base = _public_base(request)
    redirect_uri = f"{base}/auth/sso/{provider}/callback"
    profile = _exchange_code(provider, code, redirect_uri)
    email = (profile.get("email") or "").lower().strip()
    subject = str(profile.get("subject") or "")
    display_name = profile.get("name")
    if not email or not subject:
        raise HTTPException(status_code=400, detail="SSO provider did not return email/subject")

    user = db.scalar(select(User).where(User.sso_provider == provider, User.sso_subject == subject))
    if not user:
        user = db.scalar(select(User).where(User.email == email))
        if user:
            user.sso_provider = provider
            user.sso_subject = subject
            if display_name and not user.display_name:
                user.display_name = display_name
        else:
            user = User(
                email=email,
                password_hash=None,
                display_name=display_name,
                sso_provider=provider,
                sso_subject=subject,
            )
            db.add(user)
            db.flush()

    if not user.is_active:
        raise HTTPException(status_code=403, detail="user is inactive")

    mem = db.scalar(select(Membership).where(Membership.user_id == user.id))
    if not mem:
        if not settings.SSO_AUTO_CREATE_WORKSPACE:
            raise HTTPException(
                status_code=403,
                detail="no workspace membership; ask an admin to invite you",
            )
        base_slug = _slugify(email)
        slug = base_slug
        n = 0
        while db.scalar(select(Workspace).where(Workspace.slug == slug)):
            n += 1
            slug = f"{base_slug}-{n}"
        ws = Workspace(name=f"{display_name or email}'s workspace", slug=slug)
        db.add(ws)
        db.flush()
        mem = Membership(workspace_id=ws.id, user_id=user.id, role=MemberRole.owner)
        db.add(mem)
    else:
        ws = db.get(Workspace, mem.workspace_id)
        if not ws:
            raise HTTPException(status_code=500, detail="membership references missing workspace")

    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, extra={"ws": ws.id})
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        workspace_id=ws.id,
        workspace_slug=ws.slug,
        expires_in_seconds=settings.JWT_EXPIRE_MINUTES * 60,
    )


def _exchange_code(provider: str, code: str, redirect_uri: str) -> dict[str, Any]:
    if provider == "google":
        return _google_profile(code, redirect_uri)
    return _github_profile(code, redirect_uri)


def _google_profile(code: str, redirect_uri: str) -> dict[str, Any]:
    with httpx.Client(timeout=20.0) as client:
        token_r = client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.SSO_GOOGLE_CLIENT_ID,
                "client_secret": settings.SSO_GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_r.status_code >= 400:
            raise HTTPException(status_code=400, detail=f"Google token error: {token_r.text[:200]}")
        access = token_r.json().get("access_token")
        if not access:
            raise HTTPException(status_code=400, detail="Google did not return access_token")
        ui = client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access}"},
        )
        if ui.status_code >= 400:
            raise HTTPException(status_code=400, detail=f"Google userinfo error: {ui.text[:200]}")
        data = ui.json()
        return {
            "subject": data.get("sub"),
            "email": data.get("email"),
            "name": data.get("name") or data.get("given_name"),
        }


def _github_profile(code: str, redirect_uri: str) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "nakatomi-crm"}
    with httpx.Client(timeout=20.0, headers=headers) as client:
        token_r = client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": settings.SSO_GITHUB_CLIENT_ID,
                "client_secret": settings.SSO_GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        if token_r.status_code >= 400:
            raise HTTPException(status_code=400, detail=f"GitHub token error: {token_r.text[:200]}")
        access = token_r.json().get("access_token")
        if not access:
            raise HTTPException(status_code=400, detail="GitHub did not return access_token")
        auth = {"Authorization": f"Bearer {access}"}
        ui = client.get("https://api.github.com/user", headers=auth)
        if ui.status_code >= 400:
            raise HTTPException(status_code=400, detail=f"GitHub user error: {ui.text[:200]}")
        data = ui.json()
        email = data.get("email")
        if not email:
            emails_r = client.get("https://api.github.com/user/emails", headers=auth)
            if emails_r.status_code < 400:
                emails = emails_r.json() or []
                primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
                email = (primary or (emails[0] if emails else {})).get("email")
        subject = str(data.get("id") or "")
        # Stable fallback if GitHub hides email (rare with user:email scope).
        if not email and subject:
            email = f"github-{subject}@users.noreply.github.com"
        return {
            "subject": subject,
            "email": email,
            "name": data.get("name") or data.get("login"),
        }


# keep import used for state entropy in tests if needed
def _state_fingerprint(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()[:12]
