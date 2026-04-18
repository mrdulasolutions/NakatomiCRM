"""Smoke: discovery surface is reachable and well-formed."""

from __future__ import annotations


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "version" in body


def test_root_advertises_surfaces(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    for key in ("docs", "schema", "mcp", "health", "llms", "agent_card"):
        assert key in body


def test_openapi(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert "paths" in r.json()


def test_llms_txt(client):
    r = client.get("/llms.txt")
    assert r.status_code == 200
    body = r.text
    assert "Nakatomi" in body
    assert "Auth" in body


def test_agent_card(client):
    r = client.get("/.well-known/agent.json")
    assert r.status_code == 200
    card = r.json()
    assert card["name"] == "Nakatomi CRM"
    assert any(t["type"] == "mcp" for t in card["transports"])


def test_openapi_metadata_populated(client):
    """OpenAPI doc should expose contact, license, tag descriptions."""
    spec = client.get("/openapi.json").json()
    assert spec["info"]["contact"]["email"] == "matt@mrdula.solutions"
    assert spec["info"]["license"]["name"] == "MIT"
    tag_names = {t["name"] for t in spec.get("tags", [])}
    assert {"contacts", "memory", "webhooks", "export-import"}.issubset(tag_names)
    # Every listed tag has a description.
    for t in spec.get("tags", []):
        assert t.get("description"), f"tag {t['name']} missing description"


def test_error_responses_are_problem_details(client, workspace):
    """4xx bodies follow RFC 9457 — with `type`, `title`, `status`, `detail`, `instance`."""
    r = client.get("/contacts/00000000-0000-0000-0000-000000000000", headers=workspace["headers"])
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["status"] == 404
    assert body["title"] == "Not Found"
    assert body["instance"].startswith("/contacts/")
    assert body["detail"]
    # legacy key preserved for now
    assert body["error"] == body["detail"]


def test_schema_endpoint(client):
    r = client.get("/schema")
    assert r.status_code == 200
    data = r.json()
    entities = {e["entity"] for e in data["entities"]}
    assert {"contact", "company", "deal", "relationship", "pipeline"}.issubset(entities)
    assert "contact.created" in data["event_types"]
