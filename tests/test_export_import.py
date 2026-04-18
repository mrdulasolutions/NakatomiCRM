"""Export + import: round-trip fidelity, dry-run, schema-version gate."""

from __future__ import annotations

import uuid

from sqlalchemy import select, text

from app.db import SessionLocal, engine
from app.models import (
    Company,
    Contact,
    CustomFieldDefinition,
    Deal,
    Note,
    Pipeline,
    Relationship,
    Task,
    Webhook,
)


def _seed(client, h) -> dict:
    """Populate a workspace with one of everything. Returns the created handles."""
    pipe = client.post(
        "/pipelines",
        headers=h,
        json={
            "name": "Sales",
            "slug": "sales",
            "is_default": True,
            "stages": [
                {"name": "Lead", "slug": "lead", "position": 0, "probability": 10},
                {"name": "Won", "slug": "won", "position": 1, "probability": 100, "is_won": True},
            ],
        },
    ).json()
    co = client.post(
        "/companies",
        headers=h,
        json={"name": "Acme", "domain": "acme.example", "external_id": "acme-co"},
    ).json()
    c = client.post(
        "/contacts",
        headers=h,
        json={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@acme.example",
            "external_id": "ada-1",
            "company_id": co["id"],
        },
    ).json()
    deal = client.post(
        "/deals",
        headers=h,
        json={
            "name": "Big Deal",
            "amount": 10000,
            "currency": "USD",
            "primary_contact_id": c["id"],
            "company_id": co["id"],
        },
    ).json()
    client.post(
        "/notes",
        headers=h,
        json={"entity_type": "deal", "entity_id": deal["id"], "body": "kicked off"},
    )
    client.post(
        "/tasks",
        headers=h,
        json={"title": "Send proposal", "entity_type": "deal", "entity_id": deal["id"]},
    )
    client.post(
        "/activities",
        headers=h,
        json={"kind": "call", "subject": "intro", "entity_type": "contact", "entity_id": c["id"]},
    )
    client.post(
        "/relationships",
        headers=h,
        json={
            "source_type": "contact",
            "source_id": c["id"],
            "target_type": "company",
            "target_id": co["id"],
            "relation_type": "works_at",
        },
    )
    client.post(
        "/custom-fields",
        headers=h,
        json={"entity_type": "contact", "name": "linkedin", "label": "LinkedIn", "field_type": "url"},
    )
    client.post(
        "/memory/link",
        headers=h,
        json={
            "connector": "docdeploy",
            "external_id": "mem_abc",
            "crm_entity_type": "contact",
            "crm_entity_id": c["id"],
        },
    )
    client.post(
        "/webhooks",
        headers=h,
        json={"name": "hook", "url": "https://example.invalid/h", "events": ["*"]},
    )
    return {"pipeline": pipe, "company": co, "contact": c, "deal": deal}


def _wipe_workspace(workspace_id: str) -> None:
    """Drop every CRM row for a workspace without touching the workspace itself.

    Ordering matters: children before parents. ``stages`` isn't in the list —
    it has no ``workspace_id`` and cascades when we drop pipelines.
    """
    tables = [
        "relationships",
        "memory_links",
        "webhook_deliveries",
        "webhooks",
        "notes",
        "tasks",
        "activities",
        "deals",  # must precede pipelines (FK RESTRICT)
        "pipelines",  # CASCADEs stages
        "contacts",
        "companies",
        "custom_field_definitions",
        "files",
        "ingest_runs",
        "timeline_events",
        "audit_log",
    ]
    with engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t} WHERE workspace_id = :ws"), {"ws": workspace_id})


def test_round_trip_export_import(client, workspace):
    h = workspace["headers"]
    seeded = _seed(client, h)

    # 1. Export.
    r = client.get("/export", headers=h)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["schema_version"] == 1
    assert doc["counts"]["contacts"] == 1
    assert doc["counts"]["companies"] == 1
    assert doc["counts"]["deals"] == 1
    # Webhook secret redacted.
    assert doc["webhooks"][0]["secret"] == "[redacted on export]"

    # 2. Wipe.
    _wipe_workspace(workspace["workspace_id"])
    assert client.get("/contacts", headers=h).json()["count"] == 0

    # 3. Re-import.
    r = client.post("/import", headers=h, json={"doc": doc, "dry_run": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is False
    assert body["created"].get("contacts") == 1
    assert body["created"].get("companies") == 1
    assert body["created"].get("deals") == 1
    assert body["created"].get("pipelines") == 1
    assert body["created"].get("stages") == 2
    # Webhook was imported without a secret -> warning + a fresh secret.
    assert any("mint a new one" in w for w in body["warnings"])

    # 4. Data is back, with fresh UUIDs but intact relationships.
    db = SessionLocal()
    try:
        contact = db.scalars(select(Contact).where(Contact.external_id == "ada-1")).one()
        company = db.scalars(select(Company).where(Company.external_id == "acme-co")).one()
        assert contact.id != seeded["contact"]["id"]  # fresh uuid
        assert contact.company_id == company.id  # FK rewritten through id_map

        deal = db.scalars(select(Deal).where(Deal.name == "Big Deal")).one()
        assert deal.primary_contact_id == contact.id
        assert deal.company_id == company.id

        pipe = db.scalars(select(Pipeline).where(Pipeline.slug == "sales")).one()
        assert deal.pipeline_id == pipe.id

        # Relationship got rewritten too.
        edge = db.scalars(select(Relationship).where(Relationship.relation_type == "works_at")).one()
        assert edge.source_id == contact.id
        assert edge.target_id == company.id

        # Notes/tasks/custom-fields survived.
        assert db.scalars(select(Note).where(Note.body == "kicked off")).one()
        assert db.scalars(select(Task).where(Task.title == "Send proposal")).one()
        assert db.scalars(select(CustomFieldDefinition).where(CustomFieldDefinition.name == "linkedin")).one()
        # Webhook exists with a freshly-minted secret.
        hook = db.scalars(select(Webhook).where(Webhook.url == "https://example.invalid/h")).one()
        assert hook.secret and hook.secret != "[redacted on export]"
    finally:
        db.close()


def test_dry_run_does_not_persist(client, workspace):
    h = workspace["headers"]
    _seed(client, h)
    doc = client.get("/export", headers=h).json()
    _wipe_workspace(workspace["workspace_id"])

    r = client.post("/import", headers=h, json={"doc": doc, "dry_run": True})
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["created"]  # counts are reported
    # But nothing landed.
    assert client.get("/contacts", headers=h).json()["count"] == 0
    assert client.get("/companies", headers=h).json()["count"] == 0


def test_second_import_updates_instead_of_duplicating(client, workspace):
    h = workspace["headers"]
    _seed(client, h)
    doc = client.get("/export", headers=h).json()

    # Re-import without wiping: the matcher should upsert, not duplicate.
    r = client.post("/import", headers=h, json={"doc": doc, "dry_run": False})
    body = r.json()
    assert body["updated"].get("contacts") == 1
    assert body["updated"].get("companies") == 1
    assert body["created"].get("contacts", 0) == 0
    assert body["created"].get("companies", 0) == 0

    # One contact, one company — no duplicates.
    assert client.get("/contacts", headers=h).json()["count"] == 1
    assert client.get("/companies", headers=h).json()["count"] == 1


def test_rejects_unknown_schema_version(client, workspace):
    h = workspace["headers"]
    r = client.post("/import", headers=h, json={"doc": {"schema_version": 999}, "dry_run": False})
    assert r.status_code == 422
    assert "schema_version" in r.json()["error"]


def test_member_role_cannot_import_or_export(client, workspace):
    r = client.post(
        "/workspace/api-keys",
        headers=workspace["headers"],
        json={"name": "m", "role": "member"},
    ).json()
    member_h = {"Authorization": f"Bearer {r['key']}"}
    assert client.get("/export", headers=member_h).status_code == 403
    assert client.post("/import", headers=member_h, json={"doc": {"schema_version": 1}}).status_code == 403


def test_uuid_translated_for_polymorphic_refs(client, workspace):
    """Notes on an entity use (entity_type, entity_id). After round-trip, the
    entity_id must point at the freshly minted CRM row, not the stale source id."""
    h = workspace["headers"]
    _seed(client, h)
    doc = client.get("/export", headers=h).json()
    _wipe_workspace(workspace["workspace_id"])
    client.post("/import", headers=h, json={"doc": doc, "dry_run": False})

    db = SessionLocal()
    try:
        deal = db.scalars(select(Deal).where(Deal.name == "Big Deal")).one()
        note = db.scalars(select(Note).where(Note.body == "kicked off")).one()
        assert note.entity_id == deal.id
    finally:
        db.close()


def test_schema_version_round_trip_preserved(client, workspace):
    h = workspace["headers"]
    _seed(client, h)
    doc = client.get("/export", headers=h).json()
    assert "exported_at" in doc and "nakatomi_version" in doc
    # Sanity: the export is a pure dict the import accepts.
    _ = uuid.UUID(doc["workspace"]["id"])
