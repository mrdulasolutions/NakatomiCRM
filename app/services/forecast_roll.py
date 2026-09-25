"""Forecast rollup helpers (P2.7 stretch)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.models import Deal, DealStatus, Stage


def _commit_category(deal: Deal) -> str:
    raw = (deal.data or {}).get("commit_category") or (deal.data or {}).get("commit")
    if raw is None:
        return "pipeline"
    return str(raw).strip().lower() or "pipeline"


def rollup_forecast_rows(
    rows: list[tuple[Deal, Stage]],
    *,
    label: str,
    start: date,
    end: date,
    pipeline_id: str | None,
    owner_user_id: str | None,
) -> dict[str, Any]:
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
    by_commit: dict[str, dict] = {}
    by_currency: dict[str, dict] = {}

    for deal, stage in rows:
        amount = float(deal.amount or 0)
        prob_frac = float(stage.probability or 0) / 100.0
        currency = (deal.currency or "USD").upper()
        commit = _commit_category(deal)

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

        cm = by_commit.setdefault(
            commit,
            {"commit_category": commit, "count": 0, "amount": 0.0, "weighted_amount": 0.0},
        )
        cm["count"] += 1
        cm["amount"] += amount
        cm["weighted_amount"] += weighted

        cur = by_currency.setdefault(
            currency,
            {"currency": currency, "count": 0, "amount": 0.0, "weighted_amount": 0.0},
        )
        cur["count"] += 1
        cur["amount"] += amount
        cur["weighted_amount"] += weighted

    return {
        "period": label,
        "from": start.isoformat(),
        "to": (end - timedelta(days=1)).isoformat(),
        "pipeline_id": pipeline_id,
        "owner_user_id": owner_user_id,
        "totals": {k: round(v, 2) if isinstance(v, float) else v for k, v in totals.items()},
        "by_stage": sorted(by_stage.values(), key=lambda r: r["stage_slug"]),
        "by_owner": list(by_owner.values()),
        "by_commit": sorted(by_commit.values(), key=lambda r: r["commit_category"]),
        "by_currency": sorted(by_currency.values(), key=lambda r: r["currency"]),
        "fx_note": "Amounts are native per deal.currency; no FX conversion applied.",
    }
