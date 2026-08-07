"""MCP tools for custom field CRUD + describe_schema workspace pack."""

from __future__ import annotations

from types import SimpleNamespace

from app.mcp_server import (
    create_custom_field,
    delete_custom_field,
    describe_schema,
    list_custom_fields,
    list_object_types,
    update_custom_field,
)


class _FakeCtx:
    """Minimal MCP Context stand-in that carries Authorization."""

    def __init__(self, api_key: str) -> None:
        request = SimpleNamespace(headers={"authorization": f"Bearer {api_key}"})
        self.request_context = SimpleNamespace(request=request)


def test_mcp_custom_field_crud(workspace):
    ctx = _FakeCtx(workspace["api_key"])

    created = create_custom_field(
        ctx,
        entity_type="contact",
        name="linkedin_url",
        label="LinkedIn URL",
        field_type="url",
        description="profile URL",
    )
    assert created["name"] == "linkedin_url"
    assert created["field_type"] == "url"
    fid = created["id"]

    listed = list_custom_fields(ctx, entity_type="contact")
    assert any(f["id"] == fid for f in listed)
    assert list_custom_fields(ctx, entity_type="deal") == []

    updated = update_custom_field(ctx, field_id=fid, label="LinkedIn", required=True)
    assert updated["label"] == "LinkedIn"
    assert updated["required"] is True

    schema = describe_schema(ctx)
    assert schema["version"]
    assert any(f["name"] == "linkedin_url" for f in schema["custom_fields"])
    assert "custom_object_types" in schema
    assert schema["protocols"]["versions"]["mcp"] == "1.0"

    assert list_object_types(ctx) == []

    deleted = delete_custom_field(ctx, field_id=fid)
    assert deleted["ok"] is True
    assert list_custom_fields(ctx, entity_type="contact") == []


def test_mcp_custom_field_duplicate_and_bad_type(workspace):
    ctx = _FakeCtx(workspace["api_key"])
    create_custom_field(
        ctx,
        entity_type="company",
        name="tier",
        label="Tier",
        field_type="select",
        options=["A", "B"],
    )
    try:
        create_custom_field(
            ctx, entity_type="company", name="tier", label="Tier again", field_type="string"
        )
        raise AssertionError("expected duplicate RuntimeError")
    except RuntimeError as exc:
        assert "already exists" in str(exc)

    try:
        create_custom_field(
            ctx, entity_type="contact", name="bad", label="Bad", field_type="xml"
        )
        raise AssertionError("expected bad type RuntimeError")
    except RuntimeError as exc:
        assert "field_type" in str(exc)
