"""Product catalog, deal line items, and forecast rollups."""

from __future__ import annotations


def _make_pipeline(client, h):
    r = client.post(
        "/pipelines",
        headers=h,
        json={
            "name": "Sales",
            "slug": "sales",
            "is_default": True,
            "stages": [
                {"name": "Lead", "slug": "lead", "position": 0, "probability": 10},
                {"name": "Qualified", "slug": "qualified", "position": 1, "probability": 50},
                {"name": "Won", "slug": "won", "position": 2, "probability": 100, "is_won": True},
                {"name": "Lost", "slug": "lost", "position": 3, "probability": 0, "is_lost": True},
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_product_crud(client, workspace):
    h = workspace["headers"]
    r = client.post(
        "/products",
        headers=h,
        json={"name": "Pro Plan", "sku": "PRO-1", "unit_price": 99, "currency": "USD"},
    )
    assert r.status_code == 201, r.text
    prod = r.json()
    assert prod["sku"] == "PRO-1"
    pid = prod["id"]

    r = client.get(f"/products/{pid}", headers=h)
    assert r.status_code == 200
    assert r.json()["name"] == "Pro Plan"

    r = client.patch(f"/products/{pid}", headers=h, json={"unit_price": 129})
    assert r.status_code == 200
    assert r.json()["unit_price"] == 129

    r = client.get("/products", headers=h, params={"q": "pro"})
    assert r.status_code == 200
    assert any(p["id"] == pid for p in r.json()["items"])

    r = client.delete(f"/products/{pid}", headers=h)
    assert r.status_code == 200


def test_product_sku_uniqueness(client, workspace):
    h = workspace["headers"]
    client.post("/products", headers=h, json={"name": "A", "sku": "DUPE", "unit_price": 1})
    r = client.post("/products", headers=h, json={"name": "B", "sku": "DUPE", "unit_price": 2})
    assert r.status_code == 409


def test_line_item_snapshots_product(client, workspace):
    h = workspace["headers"]
    _make_pipeline(client, h)
    r = client.post("/products", headers=h, json={"name": "Pro", "sku": "P", "unit_price": 100})
    pid = r.json()["id"]
    r = client.post("/deals", headers=h, json={"name": "D1"})
    deal_id = r.json()["id"]

    r = client.post(
        f"/deals/{deal_id}/line-items",
        headers=h,
        json={"product_id": pid, "quantity": 3},
    )
    assert r.status_code == 201, r.text
    line = r.json()
    assert line["name"] == "Pro"
    assert line["sku"] == "P"
    assert line["unit_price"] == 100
    assert line["quantity"] == 3

    # Catalog change must NOT touch the historical line
    client.patch(f"/products/{pid}", headers=h, json={"unit_price": 999, "name": "Pro v2"})
    r = client.get(f"/deals/{deal_id}/line-items", headers=h)
    snapshot = r.json()[0]
    assert snapshot["name"] == "Pro"
    assert snapshot["unit_price"] == 100


def test_line_item_ad_hoc_no_product(client, workspace):
    h = workspace["headers"]
    _make_pipeline(client, h)
    r = client.post("/deals", headers=h, json={"name": "D1"})
    deal_id = r.json()["id"]

    r = client.post(
        f"/deals/{deal_id}/line-items",
        headers=h,
        json={"name": "Custom service", "unit_price": 500, "quantity": 1},
    )
    assert r.status_code == 201
    assert r.json()["product_id"] is None
    assert r.json()["name"] == "Custom service"


def test_line_item_requires_name_when_no_product(client, workspace):
    h = workspace["headers"]
    _make_pipeline(client, h)
    r = client.post("/deals", headers=h, json={"name": "D1"})
    deal_id = r.json()["id"]
    r = client.post(f"/deals/{deal_id}/line-items", headers=h, json={"quantity": 1})
    assert r.status_code == 422
    assert "name is required" in r.json()["detail"]


def test_line_item_delete_and_patch(client, workspace):
    h = workspace["headers"]
    _make_pipeline(client, h)
    r = client.post("/deals", headers=h, json={"name": "D1"})
    deal_id = r.json()["id"]
    r = client.post(
        f"/deals/{deal_id}/line-items",
        headers=h,
        json={"name": "X", "unit_price": 10, "quantity": 1},
    )
    line_id = r.json()["id"]

    r = client.patch(f"/deals/{deal_id}/line-items/{line_id}", headers=h, json={"quantity": 5})
    assert r.status_code == 200
    assert r.json()["quantity"] == 5

    r = client.delete(f"/deals/{deal_id}/line-items/{line_id}", headers=h)
    assert r.status_code == 200

    r = client.get(f"/deals/{deal_id}/line-items", headers=h)
    assert r.json() == []


# ---------- Forecast ----------


def test_forecast_quarter_rollup(client, workspace):
    h = workspace["headers"]
    pipe = _make_pipeline(client, h)
    qualified = next(s for s in pipe["stages"] if s["slug"] == "qualified")
    won = next(s for s in pipe["stages"] if s["slug"] == "won")

    # one open at qualified (50% of 1000) + one won at 100% of 2000
    client.post(
        "/deals",
        headers=h,
        json={
            "name": "Open",
            "amount": 1000,
            "stage_id": qualified["id"],
            "expected_close_date": "2026-05-15T00:00:00Z",
        },
    )
    client.post(
        "/deals",
        headers=h,
        json={
            "name": "Won",
            "amount": 2000,
            "stage_id": won["id"],
            "expected_close_date": "2026-06-01T00:00:00Z",
        },
    )

    r = client.get("/forecast", headers=h, params={"period": "2026Q2"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["period"] == "2026Q2"
    t = body["totals"]
    assert t["open_count"] == 1
    assert t["open_amount"] == 1000
    assert t["won_count"] == 1
    assert t["won_amount"] == 2000
    # 1000*0.5 + 2000*1.0 == 2500
    assert t["weighted_amount"] == 2500
    assert len(body["by_stage"]) == 2


def test_forecast_period_parsing(client, workspace):
    h = workspace["headers"]
    _make_pipeline(client, h)
    r = client.get("/forecast", headers=h, params={"period": "not-a-period"})
    assert r.status_code == 422

    r = client.get("/forecast", headers=h, params={"period": "2026-04"})
    assert r.status_code == 200
    assert r.json()["from"] == "2026-04-01"
    assert r.json()["to"] == "2026-04-30"

    r = client.get(
        "/forecast",
        headers=h,
        params={"period": "custom:2026-01-01:2026-03-31"},
    )
    assert r.status_code == 200
    assert r.json()["from"] == "2026-01-01"
    assert r.json()["to"] == "2026-03-31"
