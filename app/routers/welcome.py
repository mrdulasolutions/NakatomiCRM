"""First-run welcome flow.

A fresh Nakatomi deploy lands you on an empty Postgres. The README's
``curl /auth/signup`` works, but for anyone who hasn't memorized the
JSON shape it's a friction wall right at the moment of "did this even
deploy?"

This module gives a fresh install a server-rendered welcome page and a
single ``POST /bootstrap`` endpoint that creates the first user,
workspace, membership, and API key in one transaction. After the first
user exists, ``/bootstrap`` is closed (409) and ``/`` reverts to the
JSON discovery doc.

Why one-shot rather than auth-gated:

* The window between deploy promotion and the operator's first request
  is small (seconds to minutes for an interactive deploy).
* The endpoint is single-claim — once any user exists, every subsequent
  request fails with 409. That's the same threat surface as a brand-new
  Wordpress install's first-admin form.
* Requiring a shared secret would defeat the "1-click" promise of the
  Railway template, which is half the point of shipping this in the
  first place.

If you need a stricter model — e.g. for environments where the deploy
sits idle for hours before someone claims it — set ``BOOTSTRAP_TOKEN``
in env and we'll require ``?token=`` matching it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import __version__
from app.brand_pages import (
    render_already_initialized,
    render_bootstrap_success,
    render_welcome_page,
)
from app.config import settings
from app.db import get_db
from app.models import ApiKey, MemberRole, Membership, User, Workspace
from app.security import generate_api_key, hash_password

router = APIRouter(tags=["bootstrap"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_any_user(db: Session) -> bool:
    return (db.scalar(select(func.count(User.id))) or 0) > 0


def _check_token(request: Request) -> None:
    """If BOOTSTRAP_TOKEN is set in env, require ?token= matching it.
    Skipped if env var is unset or empty (the default 1-click flow)."""
    expected = settings.BOOTSTRAP_TOKEN.strip()
    if not expected:
        return
    got = request.query_params.get("token", "")
    if got != expected:
        raise HTTPException(status_code=403, detail="bootstrap token required")


def _bootstrap(
    db: Session,
    *,
    email: str,
    password: str,
    display_name: str | None,
    workspace_name: str,
    workspace_slug: str,
) -> dict[str, Any]:
    """Atomically create user + workspace + membership + admin API key.
    Caller is responsible for the ``_has_any_user`` precheck and the
    ``_check_token`` precheck."""
    if db.scalar(select(Workspace).where(Workspace.slug == workspace_slug)):
        raise HTTPException(status_code=409, detail="workspace slug taken")

    user = User(
        email=email.lower(),
        password_hash=hash_password(password),
        display_name=display_name or None,
    )
    ws = Workspace(name=workspace_name, slug=workspace_slug)
    db.add(user)
    db.add(ws)
    db.flush()
    db.add(Membership(workspace_id=ws.id, user_id=user.id, role=MemberRole.owner))

    full, prefix, digest = generate_api_key()
    key = ApiKey(
        workspace_id=ws.id,
        user_id=user.id,
        name="bootstrap",
        prefix=prefix,
        key_hash=digest,
        role=MemberRole.admin,
        scopes=["*"],
    )
    db.add(key)
    db.commit()

    return {
        "user_id": user.id,
        "email": user.email,
        "workspace_id": ws.id,
        "workspace_slug": ws.slug,
        "api_key": full,
        "api_key_prefix": prefix,
        "created_at": datetime.now(UTC).isoformat(),
    }


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------


class BootstrapRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str | None = None
    workspace_name: str
    workspace_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")


@router.post("/bootstrap")
def bootstrap_json(
    payload: BootstrapRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """One-shot install endpoint. Returns the full credentials including
    the plaintext API key — shown exactly once. Closes after first use."""
    if _has_any_user(db):
        raise HTTPException(
            status_code=409,
            detail="this Nakatomi instance is already initialized — sign in via /auth/login",
        )
    _check_token(request)
    return _bootstrap(
        db,
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
        workspace_name=payload.workspace_name,
        workspace_slug=payload.workspace_slug,
    )


def _welcome_form_action(request: Request) -> str:
    action = "/welcome/signup"
    token = request.query_params.get("token", "").strip()
    if token:
        from urllib.parse import quote

        action = f"{action}?token={quote(token, safe='')}"
    return action


def _render_welcome(request: Request, error: str | None = None) -> HTMLResponse:
    return HTMLResponse(render_welcome_page(error=error, form_action=_welcome_form_action(request)))


@router.get("/welcome/preview", response_class=HTMLResponse, include_in_schema=False)
def welcome_preview(request: Request) -> HTMLResponse:
    """Design preview of the first-run claim form (no database required)."""
    return HTMLResponse(render_welcome_page(form_action=_welcome_form_action(request)))


@router.get("/welcome/claimed/preview", response_class=HTMLResponse, include_in_schema=False)
def welcome_claimed_preview(request: Request) -> HTMLResponse:
    base = str(request.base_url).rstrip("/")
    return HTMLResponse(
        render_bootstrap_success(
            api_key="nk_preview000000000000000000000000000000000000000000",
            workspace_slug="mine",
            email="you@company.com",
            base_url=base,
        )
    )


@router.get("/welcome", response_class=HTMLResponse, include_in_schema=False)
def welcome_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """Always-renderable welcome page. ``GET /`` redirects here on a
    fresh install; this URL also works after init for testing."""
    if _has_any_user(db):
        return HTMLResponse(render_already_initialized())
    return _render_welcome(request)


@router.post("/welcome/signup", include_in_schema=False)
def welcome_submit(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
    password: str = Form(..., min_length=8),
    display_name: str | None = Form(None),
    workspace_name: str = Form(...),
    workspace_slug: str = Form(..., pattern=r"^[a-z0-9][a-z0-9_-]*$"),
):
    if _has_any_user(db):
        return JSONResponse(
            status_code=409,
            content={"detail": "already initialized"},
        )
    try:
        _check_token(request)
        result = _bootstrap(
            db,
            email=email,
            password=password,
            display_name=display_name,
            workspace_name=workspace_name,
            workspace_slug=workspace_slug,
        )
    except HTTPException as exc:
        return _render_welcome(request, error=str(exc.detail))

    base = str(request.base_url).rstrip("/")
    return HTMLResponse(
        render_bootstrap_success(
            api_key=result["api_key"],
            workspace_slug=result["workspace_slug"],
            email=result["email"],
            base_url=base,
        )
    )


# ---------------------------------------------------------------------------
# Root — JSON for already-initialized instances, redirect for fresh ones
# ---------------------------------------------------------------------------


@router.get("/", include_in_schema=False)
def root(request: Request, db: Session = Depends(get_db)):
    """Fresh installs see the welcome HTML. After the first user exists
    we serve the JSON discovery doc browsers don't get great use out of,
    but every agent client expects."""
    if not _has_any_user(db):
        return _render_welcome(request)
    return JSONResponse(
        {
            "name": "Nakatomi CRM",
            "version": __version__,
            "docs": "/docs",
            "schema": "/schema",
            "mcp": "/mcp",
            "health": "/health",
            "llms": "/llms.txt",
            "agent_card": "/.well-known/agent.json",
            "dashboard": "/dashboard" if settings.DASHBOARD_ENABLED else None,
        }
    )
