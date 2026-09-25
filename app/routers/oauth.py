"""OAuth 2.1 provider for MCP clients (Claude Desktop, ChatGPT, Cursor).

Minimal implementation covering what's needed for Claude Desktop's "Add
Custom Connector" flow:

- Discovery metadata (RFC 8414) at ``/.well-known/oauth-authorization-server``
- Protected-resource metadata (RFC 9728) at ``/.well-known/oauth-protected-resource``
- Dynamic Client Registration (RFC 7591) at ``POST /oauth/register``
- Authorization-code grant with PKCE at ``GET/POST /oauth/authorize``
- Token endpoint at ``POST /oauth/token`` (authorization_code + refresh_token)
- Revocation at ``POST /oauth/revoke``

Access tokens are stored as ``ApiKey`` rows (short-lived, scoped to the
user's workspace membership role). Because ``ApiKey`` is what
``get_principal`` already checks, the request-auth path needs no changes.

We don't implement every RFC 6749 corner — notably no ``implicit`` grant
(deprecated in 2.1), no ``password`` grant, no ``client_credentials``.
MCP clients only ever need ``authorization_code`` + ``refresh_token``.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brand_pages import (
    esc,
    render_authorize_page,
    render_login_landing,
    render_oauth_complete,
    render_status_page,
)
from app.db import get_db
from app.models import ApiKey, MemberRole, Membership, OAuthClient, OAuthCode, User, Workspace
from app.security import generate_api_key, hash_api_key, verify_password

router = APIRouter(tags=["oauth"])

# Code TTL: 60s is plenty — the client exchanges it immediately after the
# browser redirect.
_CODE_TTL = timedelta(seconds=60)

# Access token TTL. Short enough that a leaked one is mostly useless;
# clients use refresh_token to renew.
_ACCESS_TOKEN_TTL = timedelta(hours=1)

# Refresh token TTL. Revocable via POST /oauth/revoke.
_REFRESH_TOKEN_TTL = timedelta(days=30)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _sha256_b64url(s: str) -> str:
    """PKCE S256: base64url(sha256(code_verifier))."""
    return base64.urlsafe_b64encode(hashlib.sha256(s.encode()).digest()).rstrip(b"=").decode()


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _issuer(request: Request) -> str:
    """Return the canonical public origin. Respects X-Forwarded-Proto/Host so
    that deployments behind a proxy (Railway) advertise the right URL."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    return f"{proto}://{host}"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
def authorization_server_metadata(request: Request) -> dict:
    """RFC 8414 — tells MCP clients where the auth endpoints are."""
    iss = _issuer(request)
    return {
        "issuer": iss,
        "authorization_endpoint": f"{iss}/oauth/authorize",
        "token_endpoint": f"{iss}/oauth/token",
        "revocation_endpoint": f"{iss}/oauth/revoke",
        "registration_endpoint": f"{iss}/oauth/register",
        "scopes_supported": ["mcp"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "service_documentation": "https://github.com/mrdulasolutions/NakatomiCRM/blob/main/docs/MCP.md",
    }


def _protected_resource_body(request: Request) -> dict:
    """RFC 9728 body — shared by base and /mcp path variants."""
    iss = _issuer(request)
    return {
        "resource": iss,
        "authorization_servers": [iss],
        "scopes_supported": ["mcp"],
        "bearer_methods_supported": ["header"],
    }


@router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
@router.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
def protected_resource_metadata(request: Request) -> dict:
    """RFC 9728 — tells clients which auth server protects this API.

    Also served under ``.../mcp`` because some MCP SDKs build the metadata URL
    as ``/.well-known/oauth-protected-resource`` + resource path.
    """
    return _protected_resource_body(request)


# ---------------------------------------------------------------------------
# Dynamic Client Registration
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    client_name: str | None = None
    redirect_uris: list[str]
    grant_types: list[str] | None = None
    response_types: list[str] | None = None
    token_endpoint_auth_method: str | None = None
    scope: str | None = None


@router.post("/oauth/register", status_code=201)
def register(req: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    """RFC 7591 — a client registers itself and gets a client_id back.

    Public clients (no secret) are the norm for MCP: Claude Desktop, Cursor,
    ChatGPT Custom Connectors all rely on PKCE.
    """
    if not req.redirect_uris:
        raise HTTPException(status_code=400, detail="redirect_uris is required")

    grant_types = req.grant_types or ["authorization_code", "refresh_token"]
    response_types = req.response_types or ["code"]
    scopes = (req.scope or "mcp").split()

    client = OAuthClient(
        name=req.client_name or "Unnamed MCP client",
        redirect_uris=req.redirect_uris,
        grant_types=grant_types,
        response_types=response_types,
        scopes=scopes,
    )
    db.add(client)
    db.commit()
    db.refresh(client)

    return {
        "client_id": client.id,
        "client_name": client.name,
        "redirect_uris": client.redirect_uris,
        "grant_types": client.grant_types,
        "response_types": client.response_types,
        "scope": " ".join(client.scopes),
        "token_endpoint_auth_method": "none",
        "client_id_issued_at": int(client.created_at.timestamp()),
    }


# ---------------------------------------------------------------------------
# Branded HTML (login, success, error)
# ---------------------------------------------------------------------------


def _oauth_error_page(
    *,
    status_code: int,
    headline: str,
    message: str,
    detail: str | None = None,
) -> HTMLResponse:
    return HTMLResponse(
        render_status_page(
            variant="error",
            title="Authorization error",
            headline=headline,
            message=message,
            detail=detail,
            primary_label="Return home",
            primary_href="/",
            secondary_label="Sign-in help",
            secondary_href="/oauth/login",
        ),
        status_code=status_code,
    )


@router.get("/oauth/login", response_class=HTMLResponse, include_in_schema=False)
def oauth_login_landing() -> HTMLResponse:
    """Human-readable entry when users follow links from the welcome page."""
    return HTMLResponse(render_login_landing())


@router.get("/oauth/success", response_class=HTMLResponse, include_in_schema=False)
def oauth_success_preview(
    client: str = Query("Your MCP client", description="Client name for the success message"),
) -> HTMLResponse:
    """Static success messaging (demo / documentation). Live OAuth uses ``/oauth/complete``."""
    return HTMLResponse(
        render_status_page(
            variant="success",
            title="Authorized",
            headline="You are connected",
            message=f"{client} can now access your Nakatomi workspace on your behalf.",
            detail="You may close this window and return to your agent. Tokens refresh automatically per OAuth 2.1.",
            primary_label="Return home",
            primary_href="/",
        )
    )


@router.get("/oauth/complete", response_class=HTMLResponse, include_in_schema=False)
def oauth_complete(
    client: str = Query("Application"),
    ru: str = Query(..., description="Registered redirect_uri from the authorize step"),
    to: str = Query(..., description="Full redirect URL including authorization code"),
) -> HTMLResponse:
    """Post-authorize interstitial — validates ``to`` then returns the user to the MCP client."""
    if not to.startswith(ru):
        return _oauth_error_page(
            status_code=400,
            headline="Invalid redirect",
            message="The continuation URL does not match the registered redirect URI.",
        )
    return HTMLResponse(render_oauth_complete(client_name=client, continue_url=to))


@router.get("/oauth/complete/preview", response_class=HTMLResponse, include_in_schema=False)
def oauth_complete_preview() -> HTMLResponse:
    return HTMLResponse(
        render_oauth_complete(
            client_name="Cursor",
            continue_url="http://127.0.0.1/callback?code=preview-not-valid",
        )
    )


@router.get("/oauth/error", response_class=HTMLResponse, include_in_schema=False)
def oauth_error_preview(
    headline: str = Query("Authorization failed"),
    message: str = Query("We could not complete the OAuth request."),
    detail: str | None = Query(None),
) -> HTMLResponse:
    return _oauth_error_page(
        status_code=400,
        headline=headline,
        message=message,
        detail=detail,
    )


@router.get("/oauth/authorize/preview", response_class=HTMLResponse, include_in_schema=False)
def authorize_preview(error: str | None = Query(None)) -> HTMLResponse:
    """Design preview of the authorize form (no live OAuth client required)."""
    preview_client = OAuthClient(
        name="Cursor",
        redirect_uris=["http://127.0.0.1/callback"],
        grant_types=["authorization_code"],
        response_types=["code"],
        scopes=["mcp"],
    )
    preview_client.id = "preview000000000000000000000001"
    return HTMLResponse(
        _render_login(
            client=preview_client,
            redirect_uri="http://127.0.0.1/callback",
            response_type="code",
            state="preview",
            scope="mcp",
            code_challenge="preview-challenge-not-for-token-exchange",
            code_challenge_method="S256",
            email="you@company.com",
            error=error,
        )
    )


def _render_login(
    *,
    client: OAuthClient,
    redirect_uri: str,
    response_type: str,
    state: str,
    scope: str,
    code_challenge: str,
    code_challenge_method: str,
    email: str = "",
    error: str | None = None,
    workspaces: list[Workspace] | None = None,
) -> str:
    ws_html = ""
    if workspaces and len(workspaces) > 1:
        options = "\n".join(
            f'<option value="{esc(ws.id)}">{esc(ws.name)} ({esc(ws.slug)})</option>' for ws in workspaces
        )
        ws_html = f'<label for="workspace_id">Workspace</label><select id="workspace_id" name="workspace_id">{options}</select>'

    return render_authorize_page(
        client_name=client.name,
        client_id=client.id,
        redirect_uri=redirect_uri,
        response_type=response_type,
        state=state,
        scope=scope,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        email=email,
        error=error,
        workspace_select_html=ws_html,
    )


# ---------------------------------------------------------------------------
# Authorization endpoint (login + consent)
# ---------------------------------------------------------------------------


@router.get("/oauth/authorize", response_class=HTMLResponse)
def authorize_get(
    request: Request,
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    response_type: str = Query(...),
    state: str = Query(""),
    scope: str = Query("mcp"),
    code_challenge: str = Query(...),
    code_challenge_method: str = Query("S256"),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Render the login form. The browser lands here after the MCP client
    pops open the OAuth URL."""
    if response_type != "code":
        return _oauth_error_page(
            status_code=400,
            headline="Unsupported response type",
            message="This server only supports the authorization code flow (response_type=code).",
        )
    if code_challenge_method != "S256":
        return _oauth_error_page(
            status_code=400,
            headline="PKCE required",
            message="Use code_challenge_method=S256 with your MCP client.",
        )

    client = db.get(OAuthClient, client_id)
    if not client or redirect_uri not in client.redirect_uris:
        return _oauth_error_page(
            status_code=400,
            headline="Unknown client",
            message="The client_id or redirect_uri is not registered with this Nakatomi instance.",
            detail="Register the connector via POST /oauth/register or check your MCP client settings.",
        )

    return HTMLResponse(
        _render_login(
            client=client,
            redirect_uri=redirect_uri,
            response_type=response_type,
            state=state,
            scope=scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
        )
    )


@router.post("/oauth/authorize")
def authorize_post(
    request: Request,
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    response_type: str = Form(...),
    state: str = Form(""),
    scope: str = Form("mcp"),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form("S256"),
    email: str = Form(...),
    password: str = Form(...),
    workspace_id: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Validate credentials, issue a short-lived code, redirect back."""
    client = db.get(OAuthClient, client_id)
    if not client or redirect_uri not in client.redirect_uris:
        raise HTTPException(status_code=400, detail="unknown client_id or redirect_uri not registered")

    user = db.scalar(select(User).where(User.email == email.lower()))
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        return HTMLResponse(
            _render_login(
                client=client,
                redirect_uri=redirect_uri,
                response_type=response_type,
                state=state,
                scope=scope,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                email=email,
                error="invalid email or password",
            ),
            status_code=401,
        )

    memberships = db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    if not memberships:
        return HTMLResponse(
            _render_login(
                client=client,
                redirect_uri=redirect_uri,
                response_type=response_type,
                state=state,
                scope=scope,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                email=email,
                error="no workspaces — sign up first",
            ),
            status_code=403,
        )

    chosen_ws_id: str
    if workspace_id:
        if not any(m.workspace_id == workspace_id for m in memberships):
            raise HTTPException(status_code=403, detail="not a member of that workspace")
        chosen_ws_id = workspace_id
    elif len(memberships) == 1:
        chosen_ws_id = memberships[0].workspace_id
    else:
        # Multiple workspaces, no selection — show form with the dropdown.
        ws_rows = [db.get(Workspace, m.workspace_id) for m in memberships]
        return HTMLResponse(
            _render_login(
                client=client,
                redirect_uri=redirect_uri,
                response_type=response_type,
                state=state,
                scope=scope,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                email=email,
                error="pick a workspace to authorize",
                workspaces=[w for w in ws_rows if w is not None],
            ),
            status_code=200,
        )

    code = secrets.token_urlsafe(48)
    db.add(
        OAuthCode(
            code_hash=_hash_code(code),
            client_id=client.id,
            user_id=user.id,
            workspace_id=chosen_ws_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scope=scope,
            expires_at=datetime.now(UTC) + _CODE_TTL,
        )
    )
    db.commit()

    sep = "&" if "?" in redirect_uri else "?"
    target = f"{redirect_uri}{sep}code={code}"
    if state:
        target += f"&state={state}"
    complete_url = (
        f"/oauth/complete?client={quote(client.name)}"
        f"&ru={quote(redirect_uri, safe='')}"
        f"&to={quote(target, safe='')}"
    )
    return RedirectResponse(url=complete_url, status_code=302)


# ---------------------------------------------------------------------------
# Token endpoint
# ---------------------------------------------------------------------------


@router.post("/oauth/token")
def token(
    grant_type: str = Form(...),
    code: str | None = Form(None),
    redirect_uri: str | None = Form(None),
    client_id: str | None = Form(None),
    code_verifier: str | None = Form(None),
    refresh_token: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Exchange a code for tokens, or refresh an access token."""
    if grant_type == "authorization_code":
        if not (code and redirect_uri and client_id and code_verifier):
            raise HTTPException(
                status_code=400, detail="missing code / redirect_uri / client_id / code_verifier"
            )
        row = db.get(OAuthCode, _hash_code(code))
        if not row:
            raise HTTPException(status_code=400, detail="invalid or expired code")
        if row.used_at is not None:
            raise HTTPException(status_code=400, detail="code already used")
        if row.expires_at < datetime.now(UTC):
            raise HTTPException(status_code=400, detail="code expired")
        if row.client_id != client_id:
            raise HTTPException(status_code=400, detail="client_id mismatch")
        if row.redirect_uri != redirect_uri:
            raise HTTPException(status_code=400, detail="redirect_uri mismatch")
        # PKCE: S256(code_verifier) must equal the stored challenge.
        if _sha256_b64url(code_verifier) != row.code_challenge:
            raise HTTPException(status_code=400, detail="PKCE verification failed")

        row.used_at = datetime.now(UTC)

        mem = db.scalar(
            select(Membership).where(
                Membership.user_id == row.user_id,
                Membership.workspace_id == row.workspace_id,
            )
        )
        if not mem:
            raise HTTPException(status_code=403, detail="user no longer a member")

        access, refresh = _issue_tokens(
            db,
            user_id=row.user_id,
            workspace_id=row.workspace_id,
            role=mem.role,
            client_id=row.client_id,
            scope=row.scope,
        )
        db.commit()
        return _token_response(access, refresh, row.scope)

    if grant_type == "refresh_token":
        if not refresh_token:
            raise HTTPException(status_code=400, detail="refresh_token is required")
        key = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(refresh_token)))
        if not key or key.revoked_at is not None:
            raise HTTPException(status_code=400, detail="invalid refresh_token")
        oauth_data = key.data.get("oauth") if isinstance(key.data, dict) else None
        if not oauth_data or oauth_data.get("kind") != "refresh":
            raise HTTPException(status_code=400, detail="not a refresh token")
        # Swap: rotate the refresh token, mint a fresh access token.
        key.revoked_at = datetime.now(UTC)
        access, refresh = _issue_tokens(
            db,
            user_id=key.user_id,
            workspace_id=key.workspace_id,
            role=key.role,
            client_id=oauth_data.get("client_id", ""),
            scope=oauth_data.get("scope", "mcp"),
        )
        db.commit()
        return _token_response(access, refresh, oauth_data.get("scope", "mcp"))

    raise HTTPException(status_code=400, detail=f"unsupported grant_type: {grant_type}")


def _issue_tokens(
    db: Session,
    *,
    user_id: str,
    workspace_id: str,
    role: MemberRole,
    client_id: str,
    scope: str,
) -> tuple[str, str]:
    """Mint an access token (1h) and a refresh token (30d) as ApiKey rows.

    Access tokens ride the existing ``get_principal`` path — same bearer
    format as manually-minted keys. Refresh tokens carry ``data.oauth.kind =
    "refresh"`` so we distinguish them at exchange time.
    """
    now = datetime.now(UTC)
    access_full, access_prefix, access_hash = generate_api_key()
    refresh_full, refresh_prefix, refresh_hash = generate_api_key()

    db.add(
        ApiKey(
            workspace_id=workspace_id,
            user_id=user_id,
            name=f"oauth:{client_id[:8]}:access",
            prefix=access_prefix,
            key_hash=access_hash,
            role=role,
            expires_at=now + _ACCESS_TOKEN_TTL,
            scopes=["*"],
        )
    )
    db.add(
        ApiKey(
            workspace_id=workspace_id,
            user_id=user_id,
            name=f"oauth:{client_id[:8]}:refresh",
            prefix=refresh_prefix,
            key_hash=refresh_hash,
            role=role,
            expires_at=now + _REFRESH_TOKEN_TTL,
            scopes=["*"],
        )
    )
    # Set `data` on the refresh-token row so we can identify it at renewal.
    db.flush()
    refresh_row = db.scalar(select(ApiKey).where(ApiKey.key_hash == refresh_hash))
    assert refresh_row is not None, "refresh token row vanished immediately after flush"
    refresh_row.data = {"oauth": {"kind": "refresh", "client_id": client_id, "scope": scope}}

    return access_full, refresh_full


def _token_response(access: str, refresh: str, scope: str) -> dict[str, Any]:
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": int(_ACCESS_TOKEN_TTL.total_seconds()),
        "refresh_token": refresh,
        "scope": scope,
    }


# ---------------------------------------------------------------------------
# Revocation
# ---------------------------------------------------------------------------


@router.post("/oauth/revoke", status_code=200)
def revoke(token: str = Form(...), db: Session = Depends(get_db)) -> JSONResponse:
    """RFC 7009 — accept any token type, mark it revoked. Always 200 to
    avoid leaking token-existence information."""
    row = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(token)))
    if row and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        db.commit()
    return JSONResponse({"revoked": True})
