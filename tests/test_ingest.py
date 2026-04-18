"""Ingest CSV + JSON flows."""

from __future__ import annotations


def test_ingest_csv_contacts(client, workspace):
    h = workspace["headers"]
    csv_payload = (
        "external_id,first_name,last_name,email,tags\n"
        "lead-1,Ada,Lovelace,ADA@example.COM,vip;early\n"
        "lead-2,Grace,Hopper,grace@example.com,\n"
    )
    r = client.post(
        "/ingest",
        headers=h,
        json={"source": "test", "format": "csv", "payload": csv_payload},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["record_count"] == 2
    assert body["created"] == 2
    assert body["updated"] == 0
    assert body["errors"] == 0

    # Emails should be lowercased; tags split and deduped.
    r = client.get("/contacts?email=ada@example.com", headers=h)
    assert r.json()["count"] == 1
    assert "vip" in r.json()["items"][0]["tags"]


def test_ingest_json_updates_on_external_id(client, workspace):
    h = workspace["headers"]
    r = client.post(
        "/ingest",
        headers=h,
        json={
            "source": "test",
            "format": "json",
            "payload": [{"external_id": "x1", "first_name": "Old", "email": "x1@example.com"}],
        },
    )
    assert r.status_code == 200
    assert r.json()["created"] == 1

    r = client.post(
        "/ingest",
        headers=h,
        json={
            "source": "test",
            "format": "json",
            "payload": [{"external_id": "x1", "first_name": "New"}],
        },
    )
    assert r.json()["updated"] == 1

    r = client.get("/contacts?email=x1@example.com", headers=h)
    assert r.json()["items"][0]["first_name"] == "New"


def test_ingest_dry_run_leaves_db_untouched(client, workspace):
    h = workspace["headers"]
    r = client.post(
        "/ingest",
        headers=h,
        json={
            "source": "test",
            "format": "json",
            "payload": [{"first_name": "Ghost", "email": "ghost@example.com"}],
            "dry_run": True,
        },
    )
    assert r.status_code == 200
    # No real rows committed.
    r = client.get("/contacts", headers=h)
    assert r.json()["count"] == 0
