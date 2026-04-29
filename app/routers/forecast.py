"""Pipeline forecasting — period rollups by stage and owner.

The shape is intentionally simple: pick a period (a quarter or month),
group open deals by stage and weight them by stage probability. The
weighted sum is the forecast. Won deals contribute at 100%; lost deals
are excluded.

Rationale for keeping this dumb:

* Real forecasting models are workspace-specific (rep ramp, seasonality,
  deal-specific risk multipliers). Shipping a one-size model would ship
  the wrong model. We give agents the structured rollup and let them
  layer the smarts on top.
* All four ingredients agents need — won-to-date, weighted pipeline,
  open deal count, breakdown by stage and owner — come out of the same
  query in 30ms.

Period syntax:

* ``2026Q2`` — calendar quarter
* ``2026-04`` — calendar month
* ``custom:<from>:<to>`` — explicit ISO 8601 dates (inclusive both ends)
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Principal, get_principal
from app.models import Deal, DealStatus, Stage

router = APIRouter(prefix="/forecast", tags=["forecast"])

_QUARTER_RE = re.compile(r"^(\d{4})Q([1-4])$")
_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_CUSTOM_RE = re.compile(r"^custom:(\d{4}-\d{2}-\d{2}):(\d{4}-\d{2}-\d{2})$")


def _parse_period(period: str) -> tuple[date, date, str]:
    """Return (from, to_exclusive, label). Raises 422 if unparseable."""
    if m := _QUARTER_RE.match(period):
        year, q = int(m.group(1)), int(m.group(2))
        start_month = (q - 1) * 3 + 1
        start = date(year, start_month, 1)
        # next quarter start
        if q == 4:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, start_month + 3, 1)
        return start, end, period
    if m := _MONTH_RE.match(period):
        year, month = int(m.group(1)), int(m.group(2))
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        return start, end, period
    if m := _CUSTOM_RE.match(period):
        try:
            start = date.fromisoformat(m.group(1))
            end = date.fromisoformat(m.group(2)) + timedelta(days=1)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"invalid custom period: {exc}") from exc
        return start, end, period
    raise HTTPException(
        status_code=422,
        detail="period must be like '2026Q2', '2026-04', or 'custom:2026-04-01:2026-06-30'",
    )


@router.get("")
def forecast(
    period: str = Query(..., description="2026Q2 | 2026-04 | custom:2026-04-01:2026-06-30"),
    pipeline_id: str | None = Query(None),
    owner_user_id: str | None = Query(None),
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> dict:
    """Forecast for the period — totals, stage breakdown, owner breakdown.

    Filters:
    * ``pipeline_id`` — restrict to one pipeline.
    * ``owner_user_id`` — restrict to one owner (useful for rep-level dashboards).

    Output:
    * ``totals``: ``open_count``, ``open_amount``, ``weighted_amount``,
      ``won_count``, ``won_amount``, ``lost_count``, ``lost_amount``.
    * ``by_stage``: list of ``{stage_id, stage_slug, probability, count, amount, weighted_amount}``.
    * ``by_owner``: list of ``{owner_user_id, count, amount, weighted_amount}``.
    """
    start, end, label = _parse_period(period)
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
    end_dt = datetime.combine(end, datetime.min.time(), tzinfo=UTC)

    base = (
        select(Deal, Stage)
        .join(Stage, Stage.id == Deal.stage_id)
        .where(
            Deal.workspace_id == p.workspace.id,
            Deal.deleted_at.is_(None),
            Deal.expected_close_date >= start_dt,
            Deal.expected_close_date < end_dt,
        )
    )
    if pipeline_id:
        base = base.where(Deal.pipeline_id == pipeline_id)
    if owner_user_id:
        base = base.where(Deal.owner_user_id == owner_user_id)

    rows = db.execute(base).all()

    totals = {
        "open_count": 0,
        "open_amount": 0.0,
        "weighted_amount": 0.0,
        "won_count": 0,
        "won_amount": 0.0,
        "lost_count": 0,
        "lost_amount": 0.0,
    }
    by_stage: dict[str, dict] = {}
    by_owner: dict[str, dict] = {}

    for deal, stage in rows:
        amount = float(deal.amount or 0)
        # ``Stage.probability`` is stored as a percentage 0..100 (matches the
        # existing UX); divide once here so weighted amounts are proper sums.
        prob_frac = float(stage.probability or 0) / 100.0
        if deal.status == DealStatus.won:
            totals["won_count"] += 1
            totals["won_amount"] += amount
            weight = 1.0
        elif deal.status == DealStatus.lost:
            totals["lost_count"] += 1
            totals["lost_amount"] += amount
            weight = 0.0
        else:
            totals["open_count"] += 1
            totals["open_amount"] += amount
            weight = prob_frac

        weighted = amount * weight
        totals["weighted_amount"] += weighted

        st = by_stage.setdefault(
            stage.id,
            {
                "stage_id": stage.id,
                "stage_slug": stage.slug,
                "stage_name": stage.name,
                "probability": float(stage.probability or 0),
                "count": 0,
                "amount": 0.0,
                "weighted_amount": 0.0,
            },
        )
        st["count"] += 1
        st["amount"] += amount
        st["weighted_amount"] += weighted

        owner_key = deal.owner_user_id or "unassigned"
        ow = by_owner.setdefault(
            owner_key,
            {
                "owner_user_id": deal.owner_user_id,
                "count": 0,
                "amount": 0.0,
                "weighted_amount": 0.0,
            },
        )
        ow["count"] += 1
        ow["amount"] += amount
        ow["weighted_amount"] += weighted

    return {
        "period": label,
        "from": start.isoformat(),
        "to": (end - timedelta(days=1)).isoformat(),
        "pipeline_id": pipeline_id,
        "owner_user_id": owner_user_id,
        "totals": {k: round(v, 2) if isinstance(v, float) else v for k, v in totals.items()},
        "by_stage": sorted(by_stage.values(), key=lambda r: r["stage_slug"]),
        "by_owner": list(by_owner.values()),
    }
