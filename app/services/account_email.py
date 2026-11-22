"""Installation-wide email for account recovery and workspace invitations."""

from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.models import EmailConfig
from app.services.email_io import send_email


def email_configured() -> bool:
    smtp = settings.RECOVERY_SMTP_HOST and (
        bool(settings.RECOVERY_SMTP_USER) == bool(settings.RECOVERY_SMTP_PASSWORD)
    )
    return bool(settings.RECOVERY_FROM_ADDRESS and (settings.RECOVERY_RESEND_API_KEY or smtp))


def canonical_origin() -> str | None:
    origin = settings.public_origin
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


def send_account_email(email: str, subject: str, body: str) -> None:
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
