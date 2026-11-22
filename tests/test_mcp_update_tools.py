"""MCP update tools: update_deal (issue #27) + task/note/product/lead/line-item parity."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.mcp_server import (
    add_line_item,
    add_note,
    create_deal,
    create_lead,
    create_product,
    create_task,
    update_deal,
    update_lead,
    update_line_item,
    update_note,
    update_product,
    update_task,
)
from app.models import ApiKey, AuditLog, MemberRole, TimelineEvent, WebhookDelivery, Workspace
from app.security import generate_api_key


class _FakeCtx:
    def __init__(self, api_key: str) -> None:
        request = SimpleNamespace(headers={"authorization": f"Bearer {api_key}"})
        self.request_context = SimpleNamespace(request=request)


def _pipeline(client, h) -> None:
    r = client.post(
        "/pipelines",
        headers=h,
        json={
            "name": "Sales",
            "slug": "sales",
            "is_default": True,
            "stages": [
                {"name": "Lead", "slug": "lead", "position": 0, "probability": 10},
                {"name": "Passed", "slug": "passed", "position": 1, "probability": 0, "is_lost": True},
            ],
        },
    )
    assert r.status_code == 201, r.text


def _scoped_ctx(workspace: dict, scopes: list[str], role: MemberRole = MemberRole.member) -> _FakeCtx:
    db = SessionLocal()
    try:
        full, prefix, digest = generate_api_key()
        db.add(
            ApiKey(
                workspace_id=workspace["workspace_id"],
                user_id=workspace["user_id"],
                name="scoped",
                prefix=prefix,
                key_hash=digest,
                role=role,
                scopes=scopes,
            )
        )
        db.commit()
        return _FakeCtx(full)
    finally:
        db.close()


def _events(entity_id: str, event_type: str) -> tuple[list[TimelineEvent], list[AuditLog]]:
    db = SessionLocal()
    try:
        tl = db.scalars(
            select(TimelineEvent).where(
                TimelineEvent.entity_id == entity_id, TimelineEvent.event_type == event_type
            )
        ).all()
        audit = db.scalars(
            select(AuditLog).where(AuditLog.entity_id == entity_id, AuditLog.action == event_type)
        ).all()
        return list(tl), list(audit)
    finally:
        db.close()


@pytest.fixture
def deal(workspace, client):
    _pipeline(client, workspace["headers"])
    ctx = _FakeCtx(workspace["api_key"])
    return create_deal(
        ctx,
        name="Active VC",
        amount=1000,
        data={"next_step": "send deck", "next_step_date": "2026-11-30", "source": "intro"},
    )


# ---------------------------------------------------------------------------
# update_deal
# ---------------------------------------------------------------------------


def test_update_deal_partial_update_leaves_other_fields(workspace, deal):
    ctx = _FakeCtx(workspace["api_key"])
    out = update_deal(ctx, deal_id=deal["id"], amount=2500, currency="EUR")
    assert out["amount"] == 2500
    assert out["currency"] == "EUR"
    assert out["name"] == "Active VC"
    assert out["stage_id"] == deal["stage_id"]
    assert out["data"] == deal["data"]


def test_update_deal_merges_data_and_null_removes_key(workspace, deal):
    ctx = _FakeCtx(workspace["api_key"])
    out = update_deal(
        ctx,
        deal_id=deal["id"],
        data={"next_step": None, "next_step_date": None, "loss_reason": "timing"},
    )
    assert out["data"] == {"source": "intro", "loss_reason": "timing"}


def test_update_deal_merge_data_false_replaces(workspace, deal):
    ctx = _FakeCtx(workspace["api_key"])
    out = update_deal(ctx, deal_id=deal["id"], data={"loss_reason": "no fit"}, merge_data=False)
    assert out["data"] == {"loss_reason": "no fit"}


def test_update_deal_tags_dates_and_clear_fields(workspace, deal):
    ctx = _FakeCtx(workspace["api_key"])
    out = update_deal(
        ctx,
        deal_id=deal["id"],
        tags=["vc", "q4"],
        expected_close_date="2026-12-31T00:00:00Z",
    )
    assert out["tags"] == ["vc", "q4"]
    assert datetime.fromisoformat(out["expected_close_date"]) == datetime(2026, 12, 31, tzinfo=UTC)
    cleared = update_deal(ctx, deal_id=deal["id"], clear_fields=["amount", "expected_close_date"])
    assert cleared["amount"] is None
    assert cleared["expected_close_date"] is None
    with pytest.raises(RuntimeError, match="cannot clear 'name'"):
        update_deal(ctx, deal_id=deal["id"], clear_fields=["name"])
    with pytest.raises(RuntimeError, match="both set and listed"):
        update_deal(ctx, deal_id=deal["id"], amount=5, clear_fields=["amount"])


def test_update_deal_emits_event_with_diff_and_audit(workspace, deal):
    ctx = _FakeCtx(workspace["api_key"])
    update_deal(ctx, deal_id=deal["id"], name="Active VC (Seed)", data={"next_step": None})
    tl, audit = _events(deal["id"], "deal.updated")
    assert len(tl) == 1
    assert len(audit) == 1
    changes = tl[0].payload["changes"]
    assert changes["name"] == {"from": "Active VC", "to": "Active VC (Seed)"}
    assert "next_step" in changes["data"]["from"]
    assert "next_step" not in changes["data"]["to"]
    assert audit[0].payload == tl[0].payload


def test_update_deal_enqueues_webhook(client, workspace, deal):
    r = client.post(
        "/webhooks",
        headers=workspace["headers"],
        json={"name": "hook", "url": "https://example.invalid/hook", "events": ["deal.updated"]},
    )
    assert r.status_code == 201, r.text
    update_deal(_FakeCtx(workspace["api_key"]), deal_id=deal["id"], amount=42)
    db = SessionLocal()
    try:
        rows = db.scalars(select(WebhookDelivery)).all()
        assert [d.event_type for d in rows] == ["deal.updated"]
    finally:
        db.close()


def test_update_deal_status_lost_mirrors_rest(workspace, deal):
    ctx = _FakeCtx(workspace["api_key"])
    out = update_deal(ctx, deal_id=deal["id"], status="lost", data={"loss_reason": "passed"})
    assert out["status"] == "lost"
    assert out["closed_at"] is not None
    assert out["stage_id"] == deal["stage_id"]  # status does not move the stage
    tl, audit = _events(deal["id"], "deal.lost")
    assert len(tl) == 1 and len(audit) == 1


def test_update_deal_requires_deals_write(workspace, deal):
    ro = _scoped_ctx(workspace, ["deals:read"])
    with pytest.raises(RuntimeError, match="missing scopes"):
        update_deal(ro, deal_id=deal["id"], amount=1)
    rw = _scoped_ctx(workspace, ["deals:write"])
    assert update_deal(rw, deal_id=deal["id"], amount=7)["amount"] == 7


def test_update_deal_validation_and_errors(workspace, deal):
    ctx = _FakeCtx(workspace["api_key"])
    with pytest.raises(RuntimeError, match="no fields to update"):
        update_deal(ctx, deal_id=deal["id"])
    with pytest.raises(RuntimeError, match="invalid update"):
        update_deal(ctx, deal_id=deal["id"], status="exploded")
    with pytest.raises(RuntimeError, match="not found"):
        update_deal(ctx, deal_id="00000000-0000-0000-0000-000000000000", amount=1)


def test_update_deal_respects_workspace_policy(workspace, deal):
    db = SessionLocal()
    try:
        ws = db.get(Workspace, workspace["workspace_id"])
        ws.data = {
            "policies": {
                "block": [{"action": "deal.updated", "when": {"amount_gte": 1_000_000}, "message": "too big"}]
            }
        }
        db.commit()
    finally:
        db.close()
    with pytest.raises(RuntimeError, match="policy blocked: too big"):
        update_deal(_FakeCtx(workspace["api_key"]), deal_id=deal["id"], amount=5_000_000)


def test_update_deal_custom_field_validation_sees_removed_keys(client, workspace, deal):
    r = client.post(
        "/custom-fields",
        headers=workspace["headers"],
        json={
            "entity_type": "deal",
            "name": "source",
            "label": "Source",
            "field_type": "string",
            "required": True,
        },
    )
    assert r.status_code == 201, r.text
    ctx = _FakeCtx(workspace["api_key"])
    with pytest.raises(RuntimeError, match="source is required"):
        update_deal(ctx, deal_id=deal["id"], data={"source": None})
    assert update_deal(ctx, deal_id=deal["id"], data={"source": "referral"})["data"]["source"] == "referral"


def test_rest_patch_deal_unchanged(client, workspace, deal):
    r = client.patch(f"/deals/{deal['id']}", headers=workspace["headers"], json={"data": {"x": 1}})
    assert r.status_code == 200, r.text
    assert r.json()["data"] == {"x": 1}  # REST PATCH still replaces data wholesale
    tl, audit = _events(deal["id"], "deal.updated")
    assert len(tl) == 1 and len(audit) == 1


# ---------------------------------------------------------------------------
# Other update tools
# ---------------------------------------------------------------------------


def test_update_task(workspace):
    ctx = _FakeCtx(workspace["api_key"])
    t = create_task(ctx, title="Call", description="old", data={"a": 1, "b": 2})
    out = update_task(
        ctx, task_id=t["id"], status="done", data={"b": None, "c": 3}, clear_fields=["description"]
    )
    assert out["status"] == "done"
    assert out["completed_at"] is not None
    assert out["title"] == "Call"
    assert out["description"] is None
    assert out["data"] == {"a": 1, "c": 3}
    tl, audit = _events(t["id"], "task.updated")
    assert len(tl) == 1 and len(audit) == 1
    with pytest.raises(RuntimeError, match="missing scopes"):
        update_task(_scoped_ctx(workspace, ["tasks:read"]), task_id=t["id"], title="x")


def test_update_note(workspace, deal):
    ctx = _FakeCtx(workspace["api_key"])
    n = add_note(ctx, entity_type="deal", entity_id=deal["id"], body="v1", data={"k": 1})
    out = update_note(ctx, note_id=n["id"], body="v2", data={"j": 2})
    assert out["body"] == "v2"
    assert out["data"] == {"k": 1, "j": 2}
    assert update_note(ctx, note_id=n["id"], data={"z": 0}, merge_data=False)["data"] == {"z": 0}
    tl, audit = _events(n["id"], "note.updated")
    assert len(tl) == 2 and len(audit) == 2
    with pytest.raises(RuntimeError, match="missing scopes"):
        update_note(_scoped_ctx(workspace, ["notes:read"]), note_id=n["id"], body="x")


def test_update_product(workspace):
    ctx = _FakeCtx(workspace["api_key"])
    prod = create_product(ctx, name="Seat", sku="SEAT-1", unit_price=10)
    out = update_product(ctx, product_id=prod["id"], unit_price=12.5, is_active=False)
    assert out["unit_price"] == 12.5
    assert out["is_active"] is False
    assert out["sku"] == "SEAT-1"
    tl, audit = _events(prod["id"], "product.updated")
    assert len(tl) == 1 and len(audit) == 1
    assert tl[0].payload["changes"]["unit_price"] == {"from": 10.0, "to": 12.5}
    with pytest.raises(RuntimeError, match="missing scopes"):
        update_product(_scoped_ctx(workspace, ["products:read"]), product_id=prod["id"], name="x")
    readonly = _scoped_ctx(workspace, ["products:write"], role=MemberRole.readonly)
    with pytest.raises(RuntimeError, match="requires one of"):
        update_product(readonly, product_id=prod["id"], name="x")


def test_update_lead(workspace):
    ctx = _FakeCtx(workspace["api_key"])
    lead = create_lead(ctx, email="a@b.co", first_name="Ann", title="CTO")
    out = update_lead(ctx, lead_id=lead["id"], status="qualified", score=88, clear_fields=["title"])
    assert out["status"] == "qualified"
    assert out["score"] == 88
    assert out["title"] is None
    assert out["first_name"] == "Ann"
    tl, audit = _events(lead["id"], "lead.updated")
    assert len(tl) == 1 and len(audit) == 1
    with pytest.raises(RuntimeError, match="invalid status"):
        update_lead(ctx, lead_id=lead["id"], status="bogus")
    with pytest.raises(RuntimeError, match="missing scopes"):
        update_lead(_scoped_ctx(workspace, ["leads:read"]), lead_id=lead["id"], score=1)


def test_update_line_item(workspace, deal):
    ctx = _FakeCtx(workspace["api_key"])
    line = add_line_item(ctx, deal_id=deal["id"], name="Setup", unit_price=100, data={"note": "x"})
    out = update_line_item(ctx, deal_id=deal["id"], line_item_id=line["id"], quantity=3, data={"note": None})
    assert out["quantity"] == 3
    assert out["unit_price"] == 100
    assert out["data"] == {}
    tl, audit = _events(deal["id"], "deal.line_item_updated")
    assert len(tl) == 1 and len(audit) == 1
    assert tl[0].payload["line_item_id"] == line["id"]
    with pytest.raises(RuntimeError, match="line item not found"):
        update_line_item(
            ctx, deal_id=deal["id"], line_item_id="00000000-0000-0000-0000-000000000000", quantity=1
        )
    with pytest.raises(RuntimeError, match="missing scopes"):
        update_line_item(
            _scoped_ctx(workspace, ["deals:read"]), deal_id=deal["id"], line_item_id=line["id"], quantity=1
        )


def test_rest_patch_line_item_now_emits_event(client, workspace, deal):
    ctx = _FakeCtx(workspace["api_key"])
    line = add_line_item(ctx, deal_id=deal["id"], name="Setup", unit_price=100)
    r = client.patch(
        f"/deals/{deal['id']}/line-items/{line['id']}", headers=workspace["headers"], json={"quantity": 2}
    )
    assert r.status_code == 200, r.text
    tl, audit = _events(deal["id"], "deal.line_item_updated")
    assert len(tl) == 1 and len(audit) == 1
