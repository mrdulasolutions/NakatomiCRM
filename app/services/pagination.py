"""Cursor-based pagination helper (created_at + id tiebreaker)."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.sql import ColumnElement


def encode_cursor(created_at: datetime, row_id: str) -> str:
    return base64.urlsafe_b64encode(
        json.dumps({"t": created_at.isoformat(), "i": row_id}).encode()
    ).decode()


def decode_cursor(cursor: str) -> tuple[datetime, str] | None:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        d = json.loads(raw)
        return datetime.fromisoformat(d["t"]), d["i"]
    except Exception:
        return None


def apply_cursor(
    query,
    *,
    model: Any,
    cursor: str | None,
    order_desc: bool = True,
):
    """Keyset pagination on (created_at, id). ``model`` must expose ``created_at`` and ``id``."""
    if not cursor:
        return query
    decoded = decode_cursor(cursor)
    if not decoded:
        return query
    ts, row_id = decoded
    if order_desc:
        cond: ColumnElement = or_(
            model.created_at < ts,
            and_(model.created_at == ts, model.id < row_id),
        )
    else:
        cond = or_(
            model.created_at > ts,
            and_(model.created_at == ts, model.id > row_id),
        )
    return query.where(cond)
