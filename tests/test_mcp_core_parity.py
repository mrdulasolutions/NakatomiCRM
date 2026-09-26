"""MCP parity for deal read + company update + task complete."""

from __future__ import annotations

from types import SimpleNamespace

from app.mcp_server import (
    complete_task,
    create_company,
    create_deal,
    create_task,
    get_deal,
    search_companies,
    search_deals,
    update_company,
)


class _FakeCtx:
    def __init__(self, api_key: str) -> None:
        request = SimpleNamespace(headers={"authorization": f"Bearer {api_key}"})
        self.request_context = SimpleNamespace(request=request)


def test_mcp_deal_read_and_search(workspace, client):
    h = workspace["headers"]
    ctx = _FakeCtx(workspace["api_key"])
    r = client.post(
        "/pipelines",
        headers=h,
        json={
            "name": "Sales",
            "slug": "sales",
            "is_default": True,
            "stages": [{"name": "Lead", "slug": "lead", "position": 0, "probability": 10}],
        },
    )
    assert r.status_code == 201
    co = create_company(ctx, name="Acme Corp", domain="acme.com")
    deal = create_deal(ctx, name="Enterprise Deployment", amount=25000, company_id=co["id"])
    got = get_deal(ctx, deal_id=deal["id"])
    assert got["name"] == "Enterprise Deployment"
    assert float(got["amount"]) == 25000
    hits = search_deals(ctx, query="Enterprise", company_id=co["id"])
    assert len(hits) == 1
    assert hits[0]["id"] == deal["id"]


def test_mcp_update_company_and_complete_task(workspace):
    ctx = _FakeCtx(workspace["api_key"])
    co = create_company(ctx, name="Patch Co", domain="patch.co")
    updated = update_company(ctx, company_id=co["id"], updates={"industry": "SaaS"})
    assert updated["industry"] == "SaaS"
    task = create_task(ctx, title="Follow up", entity_type="company", entity_id=co["id"])
    done = complete_task(ctx, task_id=task["id"])
    assert done["status"] == "done"
    assert done["completed_at"] is not None


def test_mcp_search_deals_by_company_name_flow(workspace):
    ctx = _FakeCtx(workspace["api_key"])
    co = create_company(ctx, name="Acme Corp")
    create_deal(ctx, name="Acme Big Deal", company_id=co["id"])
    companies = search_companies(ctx, query="Acme")
    assert companies
    deals = search_deals(ctx, query="Acme", company_id=companies[0]["id"])
    assert len(deals) == 1
