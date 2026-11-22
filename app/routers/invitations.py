"""Dashboard membership and email invitations."""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import EmailStr
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.brand_pages import account_page, esc
from app.browser_sessions import browser_principal, require_same_origin, set_session
from app.config import settings
from app.db import get_db
from app.deps import Principal
from app.models import BrowserSession, MemberRole, Membership, User, Workspace, WorkspaceInvitation
from app.routers.dashboard import dashboard_admin
from app.security import hash_api_key, hash_password, verify_password
from app.services.account_email import canonical_origin, email_configured, send_account_email
from app.services.password_recovery import validate_new_password

router = APIRouter(tags=["workspace"])
log = logging.getLogger(__name__)
MEMBERS_URL = "/dashboard/members"
INVITES_URL = f"{MEMBERS_URL}/invitations"
ACCEPT_URL = "/auth/accept-invitation"
INVITATION_TTL = timedelta(days=2)


def _manageable_roles(role: MemberRole) -> tuple[MemberRole, ...]:
    roles = (MemberRole.member, MemberRole.readonly)
    return (*roles, MemberRole.admin) if role == MemberRole.owner else roles


@router.get(MEMBERS_URL, response_class=HTMLResponse)
def members(db: Session = Depends(get_db), p: Principal = Depends(dashboard_admin)):
    entries = db.execute(
        select(User.id, User.email, Membership.role)
        .join(Membership)
        .where(Membership.workspace_id == p.workspace.id)
        .order_by(User.email)
    )
    manageable_roles = _manageable_roles(p.role)
    roster_items = []
    for user_id, email, role in entries:
        actions = ""
        if p.user and p.user.id != user_id and role in manageable_roles:
            options = "".join(
                f'<option value="{option.value}"{" selected" if option == role else ""}>{option.value}</option>'
                for option in manageable_roles
            )
            actions = f"""<form method="post" action="{MEMBERS_URL}/{esc(user_id)}">
              <select name="role" aria-label="Role for {esc(email)}">{options}</select>
              <button name="action" value="change">Save role</button>
              <button name="action" value="remove">Remove member</button>
            </form>"""
        roster_items.append(f"<li>{esc(email)} ({esc(role.value)}){actions}</li>")
    roster = "".join(roster_items)
    pending = db.scalars(
        select(WorkspaceInvitation)
        .where(
            WorkspaceInvitation.workspace_id == p.workspace.id,
            WorkspaceInvitation.expires_at > datetime.now(UTC),
        )
        .order_by(WorkspaceInvitation.email)
    )
    invitations = []
    for invite in pending:
        revoke = ""
        if invite.role != MemberRole.admin.value or p.role == MemberRole.owner:
            revoke = f"""<form method="post" action="{INVITES_URL}/revoke">
              <input type="hidden" name="email" value="{esc(invite.email)}">
              <button>Revoke invitation</button>
            </form>"""
        invitations.append(f"<li>{esc(invite.email)} ({esc(invite.role)}){revoke}</li>")
    invites = "".join(invitations)
    admin_option = '<option value="admin">Admin</option>' if p.role == MemberRole.owner else ""
    return account_page(
        f"Members · {p.workspace.name}",
        f"""<p><a href="/dashboard">Back to dashboard</a></p>
        <ul>{roster}</ul>
        <h2>Invite a teammate</h2>
        <form method="post" action="{INVITES_URL}">
          <label for="email">Email</label>
          <input id="email" type="email" name="email" required maxlength="320">
          <label for="role">Role</label>
          <select id="role" name="role">
            <option value="member">Member</option>
            <option value="readonly">Read-only</option>{admin_option}
          </select>
          <button>Create invitation</button>
        </form>
        <p>Creating another invitation for the same email replaces its previous link.</p>
        <h2>Pending invitations</h2><ul>{invites}</ul>""",
    )


@router.post(f"{MEMBERS_URL}/{{user_id:uuid}}")
def manage_member(
    user_id: UUID,
    request: Request,
    action: Literal["change", "remove"] = Form(),
    role: MemberRole = Form(),
    db: Session = Depends(get_db),
    p: Principal = Depends(dashboard_admin),
):
    require_same_origin(request)
    if not p.user or p.user.id == str(user_id):
        raise HTTPException(403, "You cannot manage your own membership")
    membership = db.scalar(
        select(Membership)
        .where(Membership.workspace_id == p.workspace.id, Membership.user_id == str(user_id))
        .with_for_update()
    )
    if not membership:
        raise HTTPException(404, "Workspace member not found")
    allowed = _manageable_roles(p.role)
    if membership.role not in allowed or (action == "change" and role not in allowed):
        raise HTTPException(403, "You cannot manage that role")
    if action == "remove":
        db.execute(
            delete(BrowserSession).where(
                BrowserSession.workspace_id == membership.workspace_id,
                BrowserSession.user_id == membership.user_id,
            )
        )
        db.execute(
            delete(WorkspaceInvitation).where(
                WorkspaceInvitation.workspace_id == membership.workspace_id,
                WorkspaceInvitation.email
                == select(User.email).where(User.id == membership.user_id).scalar_subquery(),
            )
        )
        db.delete(membership)
    else:
        membership.role = role
    db.commit()
    return RedirectResponse(MEMBERS_URL, status_code=303)


@router.post(INVITES_URL, response_class=HTMLResponse)
def create_invitation(
    request: Request,
    email: EmailStr = Form(),
    role: MemberRole = Form(),
    db: Session = Depends(get_db),
    p: Principal = Depends(dashboard_admin),
):
    require_same_origin(request)
    if role not in _manageable_roles(p.role):
        raise HTTPException(403, "You cannot invite someone with that role")
    origin = canonical_origin()
    if not origin:
        return account_page(
            "Invitation unavailable",
            '<p>Set the application’s public URL before inviting teammates.</p><p><a href="/dashboard/members">Back to members</a></p>',
            status_code=503,
        )
    address = email.lower()
    workspace_id, workspace_name = p.workspace.id, p.workspace.name
    db.get(Workspace, workspace_id, with_for_update={"key_share": True})
    existing = db.scalar(
        select(Membership.id).join(User).where(Membership.workspace_id == workspace_id, User.email == address)
    )
    if existing:
        return account_page(
            "Already a member", '<p><a href="/dashboard/members">Back to members</a></p>', status_code=409
        )
    token = secrets.token_urlsafe(32)
    invite = db.get(WorkspaceInvitation, (workspace_id, address), with_for_update=True)
    if invite and invite.role == MemberRole.admin.value and p.role != MemberRole.owner:
        raise HTTPException(403, "Only an owner can replace an admin invitation")
    if invite is None:
        invite = WorkspaceInvitation(workspace_id=workspace_id, email=address)
        db.add(invite)
    invite.digest = hash_api_key(token)
    invite.role = role.value
    invite.expires_at = datetime.now(UTC) + INVITATION_TTL
    db.commit()
    link = f"{origin}{ACCEPT_URL}#{token}"
    status = "Share this link privately with your teammate. It expires in two days."
    if email_configured():
        try:
            send_account_email(
                address,
                "You’re invited to a Nakatomi workspace",
                f"You’ve been invited to join {workspace_name} on Nakatomi.\n\n{link}\n\n"
                "This link expires in two days and can be used once.",
            )
            status = "Invitation email submitted. You can also share this link privately."
        except Exception as exc:
            log.warning("Workspace invitation email delivery failed (%s)", type(exc).__name__)
            status = "Email delivery failed. Share this link privately with your teammate."
    return account_page(
        "Invitation created",
        f"""<p>{esc(status)}</p>
        <label for="link">Invitation link</label>
        <input id="link" value="{esc(link)}" readonly size="65">
        <p><a href="{MEMBERS_URL}">Back to members</a></p>""",
        status_code=201,
    )


@router.post(f"{INVITES_URL}/revoke")
def revoke_invitation(
    request: Request,
    email: EmailStr = Form(),
    db: Session = Depends(get_db),
    p: Principal = Depends(dashboard_admin),
):
    require_same_origin(request)
    statement = delete(WorkspaceInvitation).where(
        WorkspaceInvitation.workspace_id == p.workspace.id, WorkspaceInvitation.email == email.lower()
    )
    if p.role != MemberRole.owner:
        statement = statement.where(WorkspaceInvitation.role != MemberRole.admin.value)
    db.execute(statement)
    db.commit()
    return RedirectResponse(MEMBERS_URL, status_code=303)


def _accept_page(message: str = "", token: str = "", *, status_code: int = 200):
    return account_page(
        "Join a workspace",
        f"""<p role="status" id="message">{esc(message)}</p>
        <p>If you’re signed in with the invited email, you can join without entering a password.
        If you already have a password, use it here. If you’re new, choose a password.</p>
        <p>For a Google or GitHub account, <a href="/dashboard">sign in</a> and reopen the invitation.</p>
        <form method="post">
          <input id="token" name="token" value="{esc(token)}" type="hidden">
          <label for="password">Password</label>
          <input id="password" name="password" type="password">
          <button id="join" disabled>Join workspace</button>
        </form>
        <script>
          const token = document.getElementById("token");
          if (location.hash) {{
            token.value = location.hash.slice(1);
            history.replaceState(null, "", location.pathname);
          }}
          if (token.value) document.getElementById("join").disabled = false;
          else document.getElementById("message").textContent = "Open your invitation link to join.";
        </script>""",
        status_code=status_code,
    )


@router.get(ACCEPT_URL, response_class=HTMLResponse)
def invitation_page():
    if not settings.DASHBOARD_ENABLED:
        raise HTTPException(404, "Dashboard is disabled")
    return _accept_page()


@router.post(ACCEPT_URL, response_class=HTMLResponse)
def accept_invitation(
    request: Request,
    token: str = Form(max_length=128),
    password: str = Form(default=""),
    db: Session = Depends(get_db),
):
    if not settings.DASHBOARD_ENABLED:
        raise HTTPException(404, "Dashboard is disabled")
    require_same_origin(request)
    invitation = db.scalar(
        select(WorkspaceInvitation).where(WorkspaceInvitation.digest == hash_api_key(token)).with_for_update()
    )
    if not invitation or invitation.expires_at <= datetime.now(UTC):
        return _accept_page("This invitation is invalid or expired.", status_code=400)
    user = db.scalar(select(User).where(User.email == invitation.email).with_for_update())
    if user:
        principal = browser_principal(request, db)
        signed_in = principal and principal.user and principal.user.id == user.id
        password_ok = (
            not signed_in
            and user.password_hash
            and len(password.encode()) <= 72
            and verify_password(password, user.password_hash)
        )
        if not user.is_active or not (signed_in or password_ok):
            return _accept_page(
                "Sign in with the invited account or enter its password.", token, status_code=401
            )
    else:
        try:
            validate_new_password(password)
        except ValueError as exc:
            return _accept_page(str(exc), token, status_code=400)
        user = User(email=invitation.email, password_hash=hash_password(password))
        db.add(user)
    workspace_id = invitation.workspace_id
    try:
        db.flush()
        existing = db.scalar(
            select(Membership.id).where(
                Membership.workspace_id == workspace_id, Membership.user_id == user.id
            )
        )
        if not existing:
            db.add(Membership(workspace_id=workspace_id, user_id=user.id, role=MemberRole(invitation.role)))
        db.delete(invitation)
        db.commit()
    except IntegrityError:
        db.rollback()
        return _accept_page(
            "Your account was updated. Open the invitation again to continue.", status_code=409
        )
    response = RedirectResponse("/dashboard", status_code=303)
    set_session(request, response, db, user.id, workspace_id)
    return response
