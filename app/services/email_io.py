"""Email I/O — IMAP polling for inbound, SMTP for outbound.

Why stdlib instead of an ORM-style email library:

* Python's stdlib ``imaplib`` and ``smtplib`` cover everything we need
  (UID FETCH, IDLE-less polling, STARTTLS, plain auth) and ship in
  every Python build. Adding a dep to do less feels backwards.
* HTML rendering, attachments, and threading are deferred to v0.4 —
  start with text/plain so we ship something testable.

The poller is a process-level loop, similar to ``app.services.webhook_delivery``.
``EMAIL_POLLER_ENABLED=false`` (default) keeps it dormant; flip to
``true`` and set ``EMAIL_POLL_INTERVAL_SECONDS`` (default 300) to enable.
"""

from __future__ import annotations

import imaplib
import logging
import smtplib
import threading
import time
from datetime import UTC, datetime
from email import message_from_bytes
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Activity, Contact, EmailConfig, EntityType, TimelineEvent, Workspace

log = logging.getLogger("nakatomi.email")


# ---------------------------------------------------------------------------
# Outbound
# ---------------------------------------------------------------------------


def send_email(
    cfg: EmailConfig,
    *,
    to: list[str],
    cc: list[str],
    bcc: list[str],
    subject: str,
    body: str,
    body_html: str | None = None,
) -> None:
    """Send via SMTP using the workspace's configured creds. Raises on failure."""
    if not cfg.smtp_host or not cfg.smtp_user or not cfg.smtp_password:
        raise RuntimeError("SMTP not configured for this workspace")

    msg = EmailMessage()
    msg["From"] = cfg.from_address or cfg.smtp_user
    if cfg.from_name:
        msg["From"] = f"{cfg.from_name} <{cfg.from_address or cfg.smtp_user}>"
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg.set_content(body)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    recipients = list({*to, *cc, *bcc})
    smtp_cls = smtplib.SMTP_SSL if (cfg.smtp_port or 0) == 465 else smtplib.SMTP
    with smtp_cls(cfg.smtp_host, cfg.smtp_port or 587, timeout=30) as smtp:
        smtp.ehlo()
        if cfg.smtp_use_tls and smtp_cls is smtplib.SMTP:
            smtp.starttls()
            smtp.ehlo()
        smtp.login(cfg.smtp_user, cfg.smtp_password)
        smtp.send_message(msg, to_addrs=recipients)


# ---------------------------------------------------------------------------
# Inbound
# ---------------------------------------------------------------------------


def _extract_addresses(*headers: str | None) -> list[str]:
    pairs: list[tuple[str, str]] = []
    for h in headers:
        if h:
            pairs.extend(getaddresses([h]))
    return [addr.lower() for _, addr in pairs if addr]


def _match_contact(db: Session, workspace_id: str, addresses: Iterable[str]) -> str | None:
    """Best-effort contact match by primary email. Returns the first match."""
    for addr in addresses:
        c = db.scalar(
            select(Contact).where(
                Contact.workspace_id == workspace_id,
                Contact.email == addr,
                Contact.deleted_at.is_(None),
            )
        )
        if c:
            return c.id
    return None


def _record_inbound(
    db: Session,
    cfg: EmailConfig,
    *,
    raw: bytes,
    uid: int,
) -> Activity | None:
    """Parse one IMAP message and persist it as an Activity. Idempotent on
    Activity.external_id (the IMAP UID + workspace scope)."""
    msg = message_from_bytes(raw)
    subject = msg.get("Subject", "(no subject)")
    sender = msg.get("From", "")
    to_hdr = msg.get("To", "")
    cc_hdr = msg.get("Cc", "")

    occurred_at = datetime.now(UTC)
    if dh := msg.get("Date"):
        try:
            occurred_at = parsedate_to_datetime(dh)
        except (TypeError, ValueError):
            pass

    # Extract a plain-text body. Walk parts and grab the first text/plain.
    body_text = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.is_attachment():
                body_text = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                break
    else:
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            body_text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")

    addrs = _extract_addresses(sender, to_hdr, cc_hdr)
    contact_id = _match_contact(db, cfg.workspace_id, addrs)

    external_id = f"imap:{cfg.id}:{uid}"
    if db.scalar(
        select(Activity).where(
            Activity.workspace_id == cfg.workspace_id,
            Activity.external_id == external_id,
        )
    ):
        return None

    activity = Activity(
        workspace_id=cfg.workspace_id,
        external_id=external_id,
        kind="email_inbound",
        subject=subject[:500] if subject else None,
        body=body_text[:50_000] if body_text else None,
        occurred_at=occurred_at,
        entity_type=EntityType.contact if contact_id else None,
        entity_id=contact_id,
        data={
            "from": sender,
            "to": to_hdr,
            "cc": cc_hdr,
            "message_id": msg.get("Message-ID"),
            "imap_uid": uid,
            "matched_addresses": addrs,
        },
    )
    db.add(activity)
    return activity


def poll_workspace(cfg: EmailConfig) -> int:
    """Pull new IMAP messages for one workspace. Returns the count fetched.
    Caller is responsible for the DB session (we open one to persist
    activities + advance the UID watermark)."""
    if not cfg.imap_host or not cfg.imap_user or not cfg.imap_password:
        return 0

    imap_cls = imaplib.IMAP4_SSL if cfg.imap_use_ssl else imaplib.IMAP4
    fetched = 0
    with imap_cls(cfg.imap_host, cfg.imap_port or (993 if cfg.imap_use_ssl else 143)) as imap:
        imap.login(cfg.imap_user, cfg.imap_password)
        imap.select(cfg.imap_folder, readonly=True)
        # SEARCH UID > last_seen — IMAP4 SEARCH supports `UID N:*`.
        last_uid = cfg.last_polled_uid or 0
        criteria = f"UID {last_uid + 1}:*" if last_uid else "ALL"
        typ, data = imap.uid("search", None, criteria)
        if typ != "OK" or not data or not data[0]:
            return 0
        uids = [int(u) for u in data[0].split()]
        if not uids:
            return 0

        db = SessionLocal()
        try:
            ws = db.get(Workspace, cfg.workspace_id)
            if not ws:
                return 0
            cfg_db = db.get(EmailConfig, cfg.id)
            if not cfg_db:
                return 0
            highest_uid = cfg_db.last_polled_uid or 0
            for uid in uids:
                if uid <= (cfg_db.last_polled_uid or 0):
                    continue
                typ, payload = imap.uid("fetch", str(uid), "(RFC822)")
                if typ != "OK" or not payload or not payload[0]:
                    continue
                raw = payload[0][1] if isinstance(payload[0], tuple) else b""
                if not raw:
                    continue
                act = _record_inbound(db, cfg_db, raw=raw, uid=uid)
                if act is not None:
                    fetched += 1
                    highest_uid = max(highest_uid, uid)
                    db.flush()
                    # Synthetic timeline event — no Principal because the
                    # poller runs as system. Webhooks fire on the activity
                    # via REST as usual; this just gives /timeline/{ws} a
                    # row for the inbound email.
                    db.add(
                        TimelineEvent(
                            workspace_id=cfg_db.workspace_id,
                            entity_type=EntityType.contact if act.entity_id else EntityType.activity,
                            entity_id=act.entity_id or act.id,
                            event_type="email.inbound",
                            actor_user_id=None,
                            actor_api_key_id=None,
                            payload={"activity_id": act.id, "subject": act.subject},
                        )
                    )
            cfg_db.last_polled_uid = highest_uid
            cfg_db.last_polled_at = datetime.now(UTC)
            db.commit()
        finally:
            db.close()
    return fetched


# ---------------------------------------------------------------------------
# Worker thread (mirrors webhook_delivery's pattern)
# ---------------------------------------------------------------------------

_stop = threading.Event()
_thread: threading.Thread | None = None


def _worker_loop() -> None:
    interval = max(60, int(getattr(settings, "EMAIL_POLL_INTERVAL_SECONDS", 300) or 300))
    log.info("email poller starting (interval=%ss)", interval)
    while not _stop.is_set():
        try:
            db = SessionLocal()
            try:
                rows = db.scalars(select(EmailConfig).where(EmailConfig.is_active.is_(True))).all()
                cfg_ids = [(c.id, c.workspace_id) for c in rows]
            finally:
                db.close()
            for cfg_id, _ws_id in cfg_ids:
                if _stop.is_set():
                    break
                db = SessionLocal()
                try:
                    cfg = db.get(EmailConfig, cfg_id)
                    if cfg:
                        try:
                            n = poll_workspace(cfg)
                            if n:
                                log.info("email poll workspace=%s fetched=%s", cfg.workspace_id, n)
                        except Exception as exc:  # noqa: BLE001
                            log.warning("email poll workspace=%s failed: %s", cfg.workspace_id, exc)
                finally:
                    db.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("email poller iteration failed: %s", exc)
        # Sleep in 1-second increments so stop is responsive.
        for _ in range(interval):
            if _stop.is_set():
                break
            time.sleep(1)
    log.info("email poller stopped")


def start_worker() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_worker_loop, name="nakatomi-email-poller", daemon=True)
    _thread.start()


def stop_worker() -> None:
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=5)
