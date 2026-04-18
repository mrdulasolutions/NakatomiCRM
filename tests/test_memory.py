"""Memory link + trace — doesn't hit real connectors."""

from __future__ import annotations


def test_link_and_trace(client, workspace):
    h = workspace["headers"]
    contact = client.post("/contacts", headers=h, json={"first_name": "Ada"}).json()

    r = client.post(
        "/memory/link",
        headers=h,
        json={
            "connector": "docdeploy",
            "external_id": "mem_abc",
            "crm_entity_type": "contact",
            "crm_entity_id": contact["id"],
            "note": "initial call",
        },
    )
    assert r.status_code == 201, r.text
    link_id = r.json()["id"]

    # Same link again → 409.
    r = client.post(
        "/memory/link",
        headers=h,
        json={
            "connector": "docdeploy",
            "external_id": "mem_abc",
            "crm_entity_type": "contact",
            "crm_entity_id": contact["id"],
        },
    )
    assert r.status_code == 409

    r = client.get(f"/memory/trace/contact/{contact['id']}", headers=h)
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["connector"] == "docdeploy"

    r = client.delete(f"/memory/link/{link_id}", headers=h)
    assert r.status_code == 200

    r = client.get(f"/memory/trace/contact/{contact['id']}", headers=h)
    assert r.json() == []


def test_list_connectors_empty_by_default(client, workspace):
    r = client.get("/memory/connectors", headers=workspace["headers"])
    assert r.status_code == 200
    # No adapters configured in the test env.
    assert r.json() == []


def test_list_links_paginates_and_filters(client, workspace):
    h = workspace["headers"]
    # Three contacts, one company, varied connectors and entity types.
    c1 = client.post("/contacts", headers=h, json={"first_name": "A"}).json()
    c2 = client.post("/contacts", headers=h, json={"first_name": "B"}).json()
    co = client.post("/companies", headers=h, json={"name": "Acme"}).json()

    def link(connector, etype, eid, note):
        client.post(
            "/memory/link",
            headers=h,
            json={
                "connector": connector,
                "external_id": f"mem_{connector}_{eid[:4]}",
                "crm_entity_type": etype,
                "crm_entity_id": eid,
                "note": note,
            },
        )

    link("docdeploy", "contact", c1["id"], "c1 call")
    link("docdeploy", "contact", c2["id"], "c2 call")
    link("supermemory", "contact", c1["id"], "c1 transcript")
    link("docdeploy", "company", co["id"], "acme brief")

    # Unfiltered: all 4.
    r = client.get("/memory/links", headers=h)
    assert r.status_code == 200
    assert r.json()["count"] == 4
    assert len(r.json()["items"]) == 4

    # Filter by connector.
    r = client.get("/memory/links?connector=docdeploy", headers=h)
    assert r.json()["count"] == 3
    for item in r.json()["items"]:
        assert item["connector"] == "docdeploy"

    # Filter by entity type.
    r = client.get("/memory/links?entity_type=company", headers=h)
    assert r.json()["count"] == 1
    assert r.json()["items"][0]["crm_entity_type"] == "company"

    # Filter by specific entity id — trace-equivalent via list.
    r = client.get(f"/memory/links?entity_type=contact&entity_id={c1['id']}", headers=h)
    assert r.json()["count"] == 2
    assert {item["connector"] for item in r.json()["items"]} == {"docdeploy", "supermemory"}


def test_list_links_paginates(client, workspace):
    h = workspace["headers"]
    contact = client.post("/contacts", headers=h, json={"first_name": "Ada"}).json()
    for i in range(5):
        client.post(
            "/memory/link",
            headers=h,
            json={
                "connector": "docdeploy",
                "external_id": f"mem_{i}",
                "crm_entity_type": "contact",
                "crm_entity_id": contact["id"],
            },
        )

    r = client.get("/memory/links?limit=2", headers=h).json()
    assert r["count"] == 5
    assert len(r["items"]) == 2
    assert r["next_cursor"]

    r2 = client.get(f"/memory/links?limit=2&cursor={r['next_cursor']}", headers=h).json()
    assert len(r2["items"]) == 2
    # No overlap between pages.
    first_ids = {x["id"] for x in r["items"]}
    second_ids = {x["id"] for x in r2["items"]}
    assert not (first_ids & second_ids)
