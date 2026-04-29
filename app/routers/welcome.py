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

import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import __version__
from app.config import settings
from app.db import get_db
from app.models import ApiKey, MemberRole, Membership, User, Workspace
from app.security import generate_api_key, hash_api_key, hash_password

router = APIRouter(tags=["bootstrap"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_any_user(db: Session) -> bool:
    return (db.scalar(select(func.count(User.id))) or 0) > 0


def _check_token(request: Request) -> None:
    """If BOOTSTRAP_TOKEN is set in env, require ?token= matching it.
    Skipped if env var is unset or empty (the default 1-click flow)."""
    expected = os.getenv("BOOTSTRAP_TOKEN", "").strip()
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


# ---------------------------------------------------------------------------
# Server-rendered welcome page
# ---------------------------------------------------------------------------

# CSS uses literal `{` and `}` so we can't .format() — use str.replace() with
# %% markers, same approach as app/routers/oauth.py.
_WELCOME_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Welcome to Nakatomi</title>
  <style>
    :root { color-scheme: dark; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      color: #e8dfcf;
      background: #0a0e1a;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px;
    }
    .card {
      width: 100%;
      max-width: 520px;
      background: #131826;
      border: 1px solid #1f2638;
      border-radius: 14px;
      padding: 32px 28px;
      box-shadow: 0 10px 40px rgba(0,0,0,.35);
    }
    .logo { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
    .logo svg { width: 36px; height: 36px; }
    .logo h1 { font-size: 18px; font-weight: 600; margin: 0; letter-spacing: .02em; }
    p.lead { color: #b8b0a3; margin: 0 0 24px; }
    label { display: block; font-size: 12px; color: #8e8678; margin: 14px 0 6px; letter-spacing: .04em; text-transform: uppercase; }
    input {
      width: 100%;
      padding: 10px 12px;
      border-radius: 8px;
      border: 1px solid #2a3142;
      background: #0a0e1a;
      color: #e8dfcf;
      font: inherit;
    }
    input:focus { outline: 2px solid #f2c14e; outline-offset: 1px; }
    button {
      margin-top: 20px;
      width: 100%;
      padding: 12px 16px;
      border-radius: 8px;
      border: 0;
      background: #e8dfcf;
      color: #0a0e1a;
      font-weight: 600;
      cursor: pointer;
    }
    button:hover { background: #fff; }
    .err { color: #ff7676; margin-top: 12px; font-size: 13px; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .footer { margin-top: 22px; padding-top: 18px; border-top: 1px solid #1f2638; font-size: 12px; color: #6b6557; }
    a { color: #f2c14e; }
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">
      <svg viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <rect width="32" height="32" fill="#0a0e1a"/>
        <polygon points="6,28 26,28 25,20 7,20" fill="#e8dfcf"/>
        <polygon points="8,20 24,20 23,12 9,12" fill="#e8dfcf"/>
        <rect x="11" y="6" width="10" height="6" fill="#e8dfcf"/>
        <rect x="13" y="3" width="6" height="3" fill="#e8dfcf"/>
        <rect x="15" y="14" width="2" height="2" fill="#f2c14e"/>
      </svg>
      <h1>Welcome to Nakatomi</h1>
    </div>
    <p class="lead">Claim this instance — one form, one click. We'll create your workspace and give you an API key for your agent.</p>
    %%ERROR%%
    <form method="post" action="/welcome/signup">
      <label for="email">Email</label>
      <input id="email" name="email" type="email" required autocomplete="email">
      <label for="password">Password (min 8 chars)</label>
      <input id="password" name="password" type="password" required minlength="8" autocomplete="new-password">
      <label for="display_name">Your name (optional)</label>
      <input id="display_name" name="display_name" type="text" autocomplete="name">
      <div class="row">
        <div>
          <label for="workspace_name">Workspace name</label>
          <input id="workspace_name" name="workspace_name" required value="My Workspace">
        </div>
        <div>
          <label for="workspace_slug">Workspace slug</label>
          <input id="workspace_slug" name="workspace_slug" required pattern="[a-z0-9][a-z0-9_-]*" value="mine">
        </div>
      </div>
      <button type="submit">Create workspace + API key</button>
    </form>
    <div class="footer">
      Already initialized? <a href="/oauth/login">Sign in</a> · Docs at <a href="/docs">/docs</a> · Schema at <a href="/schema">/schema</a>
    </div>
  </div>
</body>
</html>
"""

_SUCCESS_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Nakatomi — claimed</title>
  <style>
    :root { color-scheme: dark; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      color: #e8dfcf;
      background: #0a0e1a;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px;
    }
    .card { width: 100%; max-width: 640px; background: #131826; border: 1px solid #1f2638; border-radius: 14px; padding: 32px 28px; box-shadow: 0 10px 40px rgba(0,0,0,.35); }
    h1 { font-size: 22px; margin: 0 0 8px; }
    h2 { font-size: 14px; color: #8e8678; text-transform: uppercase; letter-spacing: .05em; margin: 24px 0 8px; }
    p { color: #b8b0a3; margin: 0 0 16px; }
    code, pre { font-family: ui-monospace, Menlo, Consolas, monospace; }
    .key { display: block; padding: 12px 14px; border-radius: 8px; background: #0a0e1a; border: 1px solid #2a3142; color: #f2c14e; word-break: break-all; }
    .warn { background: rgba(242,193,78,.08); border: 1px solid #f2c14e; color: #f2c14e; padding: 10px 12px; border-radius: 8px; font-size: 13px; margin: 12px 0 16px; }
    pre { background: #0a0e1a; border: 1px solid #2a3142; border-radius: 8px; padding: 12px 14px; overflow-x: auto; font-size: 13px; color: #e8dfcf; }
    a { color: #f2c14e; }
    .footer { margin-top: 24px; padding-top: 18px; border-top: 1px solid #1f2638; font-size: 12px; color: #6b6557; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Nakatomi is yours.</h1>
    <p>Workspace <code>%%WORKSPACE_SLUG%%</code> is live with you (<code>%%EMAIL%%</code>) as owner.</p>

    <h2>Your API key</h2>
    <code class="key">%%API_KEY%%</code>
    <div class="warn">Save it now — Nakatomi never shows this key again. Lose it and you'll need to mint a new one.</div>

    <h2>Wire up an agent</h2>
    <p>Bearer clients (Claude Code, Cursor, raw HTTP):</p>
<pre>BASE=%%BASE_URL%%
KEY=%%API_KEY%%
curl -H "Authorization: Bearer $KEY" -H "X-Workspace: %%WORKSPACE_SLUG%%" $BASE/contacts</pre>
    <p>Claude Desktop: <em>Settings → Connectors → Add Custom Connector</em> → paste <code>%%BASE_URL%%</code>. OAuth handles auth — sign in with this email + password.</p>

    <div class="footer">
      <a href="/docs">API docs</a> · <a href="/schema">Schema</a> · <a href="/dashboard">Dashboard</a> (if enabled) · Repo: <a href="https://github.com/mrdulasolutions/NakatomiCRM">github.com/mrdulasolutions/NakatomiCRM</a>
    </div>
  </div>
</body>
</html>
"""


def _render_welcome(error: str | None = None) -> HTMLResponse:
    err_html = f'<div class="err">{error}</div>' if error else ""
    body = _WELCOME_HTML.replace("%%ERROR%%", err_html)
    return HTMLResponse(body)


@router.get("/welcome", response_class=HTMLResponse, include_in_schema=False)
def welcome_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """Always-renderable welcome page. ``GET /`` redirects here on a
    fresh install; this URL also works after init for testing."""
    if _has_any_user(db):
        return HTMLResponse(
            "<p style='font-family:system-ui;padding:20px'>Already initialized. "
            "<a href='/oauth/login'>Sign in</a> or "
            "<a href='/'>see the API root</a>.</p>",
            status_code=200,
        )
    return _render_welcome()


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
        return _render_welcome(error=str(exc.detail))

    base = str(request.base_url).rstrip("/")
    body = (
        _SUCCESS_HTML.replace("%%API_KEY%%", result["api_key"])
        .replace("%%WORKSPACE_SLUG%%", result["workspace_slug"])
        .replace("%%EMAIL%%", result["email"])
        .replace("%%BASE_URL%%", base)
    )
    return HTMLResponse(body)


# ---------------------------------------------------------------------------
# Root — JSON for already-initialized instances, redirect for fresh ones
# ---------------------------------------------------------------------------


@router.get("/", include_in_schema=False)
def root(request: Request, db: Session = Depends(get_db)):
    """Fresh installs see the welcome HTML. After the first user exists
    we serve the JSON discovery doc browsers don't get great use out of,
    but every agent client expects."""
    if not _has_any_user(db):
        # Inline the welcome HTML so the operator's first request after
        # deploy lands on a real page, not a redirect.
        return _render_welcome()
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
