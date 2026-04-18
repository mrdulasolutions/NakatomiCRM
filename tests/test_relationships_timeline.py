"""Relationship graph BFS + timeline event visibility."""

from __future__ import annotations


def test_relationship_graph_and_timeline(client, workspace):
    h = workspace["headers"]
    co = client.post("/companies", headers=h, json={"name": "Acme"}).json()
    a = client.post("/contacts", headers=h, json={"first_name": "Ada"}).json()
    g = client.post("/contacts", headers=h, json={"first_name": "Grace"}).json()

    client.post(
        "/relationships",
        headers=h,
        json={
            "source_type": "contact",
            "source_id": a["id"],
            "target_type": "company",
            "target_id": co["id"],
            "relation_type": "works_at",
        },
    )
    client.post(
        "/relationships",
        headers=h,
        json={
            "source_type": "contact",
            "source_id": a["id"],
            "target_type": "contact",
            "target_id": g["id"],
            "relation_type": "knows",
        },
    )

    # Neighbors of Ada at depth 1 should see both edges.
    r = client.get(
        f"/relationships/neighbors?entity_type=contact&entity_id={a['id']}&depth=1",
        headers=h,
    )
    assert r.status_code == 200, r.text
    relations = {e["relation_type"] for e in r.json()}
    assert {"works_at", "knows"}.issubset(relations)

    # Workspace timeline has creation + relationship events.
    r = client.get("/timeline", headers=h)
    events = {e["event_type"] for e in r.json()["items"]}
    assert {"company.created", "contact.created", "relationship.created"}.issubset(events)
