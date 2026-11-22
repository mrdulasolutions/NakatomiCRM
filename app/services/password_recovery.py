"""Password reset grants and shared account recovery operations."""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import BrowserSession, EmailConfig, PasswordReset, User
from app.security import hash_api_key, hash_password
from app.services.email_io import send_email

log = logging.getLogger(__name__)
RESET_TTL = timedelta(minutes=20)


def recovery_origin() -> str | None:
    origin = settings.public_origin
    smtp_configured = settings.RECOVERY_SMTP_HOST and (
        bool(settings.RECOVERY_SMTP_USER) == bool(settings.RECOVERY_SMTP_PASSWORD)
    )
    if not (
        origin and settings.RECOVERY_FROM_ADDRESS and (settings.RECOVERY_RESEND_API_KEY or smtp_configured)
    ):
        return None
    try:
        url = urlsplit(origin)
        local_http = url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}
        if (url.scheme != "https" and not local_http) or not url.hostname or url.username or url.password:
            return None
        if url.path or url.query or url.fragment:
            return None
    except ValueError:
        return None
    return origin


def active_user(db: Session, email: str) -> User | None:
    return db.scalar(
        select(User).where(User.email == email.strip().lower(), User.is_active).with_for_update()
    )


def issue_reset(db: Session, email: str) -> tuple[str, str] | None:
    user = active_user(db, email)
    if not user or not user.password_hash:
        return None
    now = datetime.now(UTC)
    reset = db.get(PasswordReset, user.id)
    if reset and reset.created_at > now - timedelta(minutes=1):
        return None
    plaintext = secrets.token_urlsafe(32)
    if reset is None:
        reset = PasswordReset(user_id=user.id)
        db.add(reset)
    reset.digest = hash_api_key(plaintext)
    reset.created_at = now
    reset.expires_at = now + RESET_TTL
    db.commit()
    return user.email, plaintext


def validate_new_password(password: str) -> None:
    if len(password) < 8 or len(password.encode()) > 72:
        raise ValueError("Use at least 8 characters and at most 72 UTF-8 bytes.")


def change_password(db: Session, user: User, password: str) -> None:
    """Update a locked user row, revoking browser sessions and any reset grant."""
    validate_new_password(password)
    user.password_hash = hash_password(password)
    db.execute(delete(BrowserSession).where(BrowserSession.user_id == user.id))
    db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
    db.commit()


def redeem_reset(db: Session, token: str, password: str) -> bool:
    digest = hash_api_key(token)
    user_id = db.scalar(select(PasswordReset.user_id).where(PasswordReset.digest == digest))
    if not user_id:
        return False
    user = db.get(User, user_id, with_for_update=True)
    reset = db.get(PasswordReset, user_id, populate_existing=True)
    if not user or not user.is_active or not user.password_hash or not reset:
        return False
    if reset.digest != digest or reset.expires_at <= datetime.now(UTC):
        return False
    change_password(db, user, password)
    return True


def send_reset_email(email: str, link: str) -> None:
    subject = "Reset your Nakatomi password"
    body = (
        "Open this link to reset your password. It expires in 20 minutes.\n\n"
        f"{link}\n\nIf you did not request this, you can ignore this email."
    )
    try:
        if settings.RECOVERY_RESEND_API_KEY:
            with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
                response = client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {settings.RECOVERY_RESEND_API_KEY}"},
                    json={
                        "from": settings.RECOVERY_FROM_ADDRESS,
                        "to": [email],
                        "subject": subject,
                        "text": body,
                    },
                )
                response.raise_for_status()
            return
        cfg = EmailConfig(
            smtp_host=settings.RECOVERY_SMTP_HOST,
            smtp_port=settings.RECOVERY_SMTP_PORT,
            smtp_user=settings.RECOVERY_SMTP_USER or None,
            smtp_password=settings.RECOVERY_SMTP_PASSWORD or None,
            smtp_use_tls=settings.RECOVERY_SMTP_USE_TLS,
            from_address=settings.RECOVERY_FROM_ADDRESS,
        )
        send_email(cfg, to=[email], cc=[], bcc=[], subject=subject, body=body, require_auth=False)
    except Exception as exc:
        log.warning("Password reset email delivery failed (%s)", type(exc).__name__)
