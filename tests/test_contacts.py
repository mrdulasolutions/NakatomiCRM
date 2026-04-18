"""Contacts CRUD + bulk upsert + soft delete + pagination."""

from __future__ import annotations


def test_create_get_patch_delete(client, workspace):
    h = workspace["headers"]

    r = client.post(
        "/contacts",
        headers=h,
        json={"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com"},
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]

    r = client.get(f"/contacts/{cid}", headers=h)
    assert r.status_code == 200
    assert r.json()["email"] == "ada@example.com"

    r = client.patch(f"/contacts/{cid}", headers=h, json={"title": "Mathematician"})
    assert r.status_code == 200
    assert r.json()["title"] == "Mathematician"

    r = client.delete(f"/contacts/{cid}", headers=h)
    assert r.status_code == 200

    r = client.get("/contacts", headers=h)
    assert r.json()["count"] == 0

    r = client.get("/contacts?include_deleted=true", headers=h)
    assert r.json()["count"] == 1


def test_bulk_upsert_matches_on_external_id(client, workspace):
    h = workspace["headers"]

    r = client.post(
        "/contacts/bulk_upsert",
        headers=h,
        json=[
            {"external_id": "apollo-1", "first_name": "A", "email": "a@example.com"},
            {"external_id": "apollo-2", "first_name": "B", "email": "b@example.com"},
        ],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == 2
    assert body["updated"] == 0

    # Re-upsert with the same external_ids; should update, not duplicate.
    r = client.post(
        "/contacts/bulk_upsert",
        headers=h,
        json=[
            {"external_id": "apollo-1", "first_name": "Aardvark"},
            {"external_id": "apollo-2", "first_name": "Bonobo"},
        ],
    )
    assert r.status_code == 200
    assert r.json() == {
        "created": 0,
        "updated": 2,
        "ids": body["ids"],  # same ids both times
    }


def test_search_and_tag_filter(client, workspace):
    h = workspace["headers"]
    client.post("/contacts", headers=h, json={"first_name": "Ada", "tags": ["vip"]})
    client.post("/contacts", headers=h, json={"first_name": "Grace", "tags": ["alumni"]})

    r = client.get("/contacts?q=ada", headers=h)
    assert r.status_code == 200
    assert r.json()["count"] == 1

    r = client.get("/contacts?tag=alumni", headers=h)
    assert r.json()["count"] == 1
    assert r.json()["items"][0]["first_name"] == "Grace"


def test_pagination(client, workspace):
    h = workspace["headers"]
    for i in range(5):
        client.post("/contacts", headers=h, json={"first_name": f"C{i}"})

    r = client.get("/contacts?limit=2", headers=h)
    page1 = r.json()
    assert len(page1["items"]) == 2
    assert page1["next_cursor"]

    r = client.get(f"/contacts?limit=2&cursor={page1['next_cursor']}", headers=h)
    page2 = r.json()
    assert len(page2["items"]) == 2
    assert page2["items"][0]["id"] != page1["items"][0]["id"]
