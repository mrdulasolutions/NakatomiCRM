"""Custom field definitions: CRUD + uniqueness + filter by entity_type."""

from __future__ import annotations


def test_create_list_patch_delete(client, workspace):
    h = workspace["headers"]

    r = client.post(
        "/custom-fields",
        headers=h,
        json={
            "entity_type": "contact",
            "name": "linkedin_url",
            "label": "LinkedIn URL",
            "field_type": "url",
            "required": False,
            "description": "profile URL on linkedin.com",
        },
    )
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    assert r.json()["field_type"] == "url"

    # List returns it, filtered by entity_type.
    r = client.get("/custom-fields?entity_type=contact", headers=h)
    assert r.status_code == 200
    names = [f["name"] for f in r.json()]
    assert "linkedin_url" in names

    # Filtering by a different entity_type yields nothing.
    r = client.get("/custom-fields?entity_type=deal", headers=h)
    assert r.json() == []

    # Patch label + required.
    r = client.patch(
        f"/custom-fields/{fid}",
        headers=h,
        json={"label": "LinkedIn", "required": True},
    )
    assert r.status_code == 200
    assert r.json()["label"] == "LinkedIn"
    assert r.json()["required"] is True

    # Delete.
    r = client.delete(f"/custom-fields/{fid}", headers=h)
    assert r.status_code == 200
    r = client.get("/custom-fields?entity_type=contact", headers=h)
    assert r.json() == []


def test_duplicate_name_rejected(client, workspace):
    h = workspace["headers"]
    payload = {
        "entity_type": "contact",
        "name": "nickname",
        "label": "Nickname",
        "field_type": "string",
    }
    assert client.post("/custom-fields", headers=h, json=payload).status_code == 201
    r = client.post("/custom-fields", headers=h, json=payload)
    assert r.status_code == 409


def test_same_name_different_entity_types_allowed(client, workspace):
    h = workspace["headers"]
    base = {"name": "source", "label": "Source", "field_type": "string"}
    assert (
        client.post("/custom-fields", headers=h, json={**base, "entity_type": "contact"}).status_code == 201
    )
    assert (
        client.post("/custom-fields", headers=h, json={**base, "entity_type": "company"}).status_code == 201
    )


def test_invalid_field_type_rejected(client, workspace):
    h = workspace["headers"]
    r = client.post(
        "/custom-fields",
        headers=h,
        json={
            "entity_type": "contact",
            "name": "bad",
            "label": "bad",
            "field_type": "quaternion",
        },
    )
    assert r.status_code == 422


def test_member_role_cannot_create(client, workspace):
    """Admins/owners manage schema; plain members can read but not write."""
    h = workspace["headers"]
    # Mint a plain-member key from the existing owner key.
    r = client.post(
        "/workspace/api-keys",
        headers=h,
        json={"name": "member-key", "role": "member"},
    )
    assert r.status_code == 201
    member_h = {"Authorization": f"Bearer {r.json()['key']}"}

    # Member can read.
    assert client.get("/custom-fields", headers=member_h).status_code == 200
    # Member cannot create.
    r = client.post(
        "/custom-fields",
        headers=member_h,
        json={"entity_type": "contact", "name": "x", "label": "x", "field_type": "string"},
    )
    assert r.status_code == 403
