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
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.browser_sessions import public_origin, set_session
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


_STATE_COOKIE = "nk_sso_state"


def _verify_state(request: Request, state: str, provider: str) -> dict:
    fingerprint = request.cookies.get(_STATE_COOKIE, "")
    if not secrets.compare_digest(fingerprint, _state_fingerprint(state)):
        raise HTTPException(400, "Invalid SSO browser state")
    try:
        data = jwt.decode(
            state, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM], options={"require": ["exp"]}
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(400, "Invalid SSO state") from exc
    if data.get("p") != provider or not data.get("n"):
        raise HTTPException(400, "SSO state provider mismatch")
    return data


def _dashboard_destination(return_to: str | None) -> str:
    if return_to:
        url = urlsplit(return_to)
        if not url.scheme and not url.netloc and url.path == "/oauth/authorize":
            return url._replace(fragment="").geturl()
    return "/dashboard"


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
def sso_start(
    provider: str, request: Request, dashboard: bool = False, return_to: str | None = None
) -> RedirectResponse:
    provider = provider.lower()
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail=f"unknown SSO provider: {provider}")
    if not _enabled_providers().get(provider):
        raise HTTPException(status_code=503, detail=f"SSO provider '{provider}' is not configured")

    nonce = secrets.token_urlsafe(16)
    state = jwt.encode(
        {
            "p": provider,
            "n": nonce,
            "next": _dashboard_destination(return_to) if dashboard else None,
            "exp": datetime.now(UTC) + timedelta(seconds=_STATE_TTL_SECONDS),
        },
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    base = public_origin(request)
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

    response = RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})
    response.set_cookie(
        _STATE_COOKIE,
        _state_fingerprint(state),
        max_age=_STATE_TTL_SECONDS,
        httponly=True,
        secure=base.startswith("https://"),
        samesite="lax",
        path="/auth/sso",
    )
    return response


@router.get("/{provider}/callback", response_model=TokenResponse)
def sso_callback(
    provider: str,
    request: Request,
    response: Response,
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
) -> TokenResponse | RedirectResponse:
    provider = provider.lower()
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail=f"unknown SSO provider: {provider}")
    if not _enabled_providers().get(provider):
        raise HTTPException(status_code=503, detail=f"SSO provider '{provider}' is not configured")
    state_data = _verify_state(request, state, provider)

    base = public_origin(request)
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
            if not profile.get("email_verified") or user.sso_subject:
                raise HTTPException(403, "An administrator must link this identity")
            user.sso_provider = provider
            user.sso_subject = subject
            if display_name and not user.display_name:
                user.display_name = display_name
        else:
            if not profile.get("email_verified"):
                raise HTTPException(403, "A verified provider email is required")
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

    if state_data.get("next"):
        response = RedirectResponse(_dashboard_destination(state_data["next"]), status_code=303)
        set_session(request, response, db, user.id, ws.id)
        response.delete_cookie(
            _STATE_COOKIE, path="/auth/sso", httponly=True, secure=base.startswith("https://"), samesite="lax"
        )
        return response

    response.delete_cookie(
        _STATE_COOKIE, path="/auth/sso", httponly=True, secure=base.startswith("https://"), samesite="lax"
    )
    response.headers["Cache-Control"] = "no-store"
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
            "email_verified": data.get("email_verified") is True,
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
        emails_r = client.get("https://api.github.com/user/emails", headers=auth)
        emails = emails_r.json() if emails_r.is_success else []
        email = next((e.get("email") for e in emails if e.get("primary") and e.get("verified")), None)
        return {
            "subject": str(data.get("id") or ""),
            "email": email,
            "email_verified": bool(email),
            "name": data.get("name") or data.get("login"),
        }


# keep import used for state entropy in tests if needed
def _state_fingerprint(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()[:12]
