from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import MemoryDelivery, MemoryLink
from app.services import egress
from app.services.memory import delivery
from app.services.memory.access import owns_result
from app.services.memory.base import MemoryItem, MemoryWriteResult
from app.services.storage import owned_storage_key


def test_archive_storage_keys_are_workspace_bound():
    assert owned_storage_key("first", "first/attachment")
    assert not owned_storage_key("first", "second/attachment")
    assert not owned_storage_key("first", "/first/attachment")


def test_integration_destination_policy(monkeypatch):
    monkeypatch.setattr(settings, "INTEGRATION_PRIVATE_HOSTS", "")
    monkeypatch.setattr(
        egress.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (2, 1, 6, "", ("192.168.12.3", 443)),
        ],
    )
    with pytest.raises(ValueError, match="permitted network"):
        egress.resolve_destination("private.example.test", 443)
    monkeypatch.setattr(settings, "INTEGRATION_PRIVATE_HOSTS", "private.example.test")
    assert egress.resolve_destination("private.example.test", 443) == "192.168.12.3"


def test_memory_results_require_matching_workspace():
    result = MemoryItem("docdeploy", "result", "memory", metadata={"workspace_id": "first"})
    assert owns_result("docdeploy", "first", result)
    assert not owns_result("docdeploy", "second", result)
    assert not owns_result("docdeploy", "first", MemoryItem("docdeploy", "unverified", "memory"))
    slugged = MemoryItem("gbrain", "nakatomi/first/contact/entity/event", "memory")
    assert owns_result("gbrain", "first", slugged)
    assert not owns_result("gbrain", "second", slugged)


def test_memory_delivery_retries_and_records_link(client, workspace, monkeypatch):
    calls = []

    def store_event(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("temporarily unavailable")
        return MemoryWriteResult("docdeploy", "remote-id")

    connector = SimpleNamespace(store_event=store_event)
    monkeypatch.setattr(delivery, "enabled_connectors", lambda: {"docdeploy": connector})
    monkeypatch.setattr(delivery, "get_connector", lambda _: connector)
    h = workspace["headers"]
    assert client.patch("/workspace", headers=h, json={"data": {"memory_mirroring": True}}).status_code == 200
    assert client.post("/contacts", headers=h, json={"first_name": "Ada"}).status_code == 201
    assert not calls
    assert delivery.process_pending() == 1
    with SessionLocal.begin() as db:
        row = db.scalars(select(MemoryDelivery)).one()
        assert row.status == "pending"
        row.next_attempt_at = datetime.now(UTC)
    assert delivery.process_pending() == 1
    with SessionLocal() as db:
        assert db.scalars(select(MemoryDelivery)).one().status == "succeeded"
        assert db.scalars(select(MemoryLink)).one().external_id == "remote-id"
    assert calls[0]["metadata"] == calls[1]["metadata"]
    assert calls[0]["text"] == "contact.created"
