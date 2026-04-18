"""Ingest core: dispatch, diagnostics, and standardization helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.deps import Principal


@dataclass
class IngestResult:
    record_count: int = 0
    created_ids: list[str] = field(default_factory=list)
    updated_ids: list[str] = field(default_factory=list)
    error_count: int = 0
    diagnostics: list[dict] = field(default_factory=list)


Adapter = Callable[[Session, Principal, Any, dict | None, bool], IngestResult]
_ADAPTERS: dict[str, Adapter] = {}


def register_adapter(fmt: str):
    def _wrap(fn: Adapter) -> Adapter:
        _ADAPTERS[fmt] = fn
        return fn

    return _wrap


def run_ingest(
    db: Session,
    p: Principal,
    *,
    fmt: str,
    payload: Any,
    mapping: dict | None,
    dry_run: bool,
) -> IngestResult:
    adapter = _ADAPTERS.get(fmt)
    if not adapter:
        return IngestResult(
            error_count=1,
            diagnostics=[{"level": "error", "message": f"no adapter for format '{fmt}'"}],
        )
    return adapter(db, p, payload, mapping, dry_run)


# ---------- Standardization helpers shared by all adapters ----------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def norm_email(v: Any) -> str | None:
    if not v:
        return None
    s = str(v).strip().lower()
    return s if _EMAIL_RE.match(s) else None


def norm_phone(v: Any) -> str | None:
    """Keep digits and leading '+'. E.164-ish without a strict library dep."""
    if not v:
        return None
    s = str(v).strip()
    plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None
    return ("+" if plus else "") + digits


def norm_domain(v: Any) -> str | None:
    if not v:
        return None
    s = str(v).strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = s.split("/")[0]
    return s or None


def norm_url(v: Any) -> str | None:
    if not v:
        return None
    s = str(v).strip()
    if not s:
        return None
    if not s.lower().startswith(("http://", "https://")):
        s = "https://" + s
    return s


def norm_tags(v: Any) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        items = [t.strip() for t in re.split(r"[,;|]", v)]
    elif isinstance(v, (list, tuple, set)):
        items = [str(t).strip() for t in v]
    else:
        return []
    seen = []
    for t in items:
        if t and t not in seen:
            seen.append(t)
    return seen


def norm_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None
