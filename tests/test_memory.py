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
