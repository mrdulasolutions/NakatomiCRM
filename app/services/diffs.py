"""Compute before/after field diffs from SQLAlchemy session state.

Used by PATCH routes to attach a ``changes`` dict to the timeline event.
Format::

    {
        "title": {"from": "old", "to": "new"},
        "status": {"from": "open", "to": "won"},
    }

Only fields that actually changed are included. ``None`` is preserved
(distinguishing "unset → 'x'" from "'x' → 'y'").
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import inspect as sa_inspect


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, str | int | float | bool | list | dict):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime | date):
        return v.isoformat()
    if hasattr(v, "value"):  # Enum
        return v.value
    return str(v)


def compute_changes(obj: Any, attr_names: list[str]) -> dict[str, dict[str, Any]]:
    """Return ``{attr: {"from": old, "to": new}}`` for every attribute in
    ``attr_names`` that SQLAlchemy reports a change for. Attributes that
    didn't change are omitted.

    Must be called BEFORE ``db.commit()`` / ``db.flush()`` finalizes the
    instance — the ``history`` API only has the old values while the
    session is dirty.
    """
    state = sa_inspect(obj)
    changes: dict[str, dict[str, Any]] = {}
    for name in attr_names:
        if name not in state.attrs:
            continue
        hist = state.attrs[name].history
        if not hist.has_changes():
            continue
        before = hist.deleted[0] if hist.deleted else None
        # For additions the current attribute value is authoritative.
        after = hist.added[0] if hist.added else getattr(obj, name)
        changes[name] = {"from": _jsonable(before), "to": _jsonable(after)}
    return changes
