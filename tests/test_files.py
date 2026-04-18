"""File upload / download — streaming correctness and metadata."""

from __future__ import annotations

import hashlib
import io

from sqlalchemy import select

from app.db import SessionLocal
from app.models import File


def _payload(size: int) -> bytes:
    """Deterministic but non-compressible bytes so cloud-backed transports
    can't cheat and the SHA is stable across test runs."""
    # Repeating a 37-byte prime-length key forces variety in every MB.
    key = b"nakatomi-streaming-payload-marker-42!"
    reps = (size + len(key) - 1) // len(key)
    return (key * reps)[:size]


def test_upload_then_download_round_trip(client, workspace):
    h = workspace["headers"]
    body = _payload(4 * 1024 * 1024)  # 4 MB — above Starlette's 1 MB spill-to-disk threshold
    sha = hashlib.sha256(body).hexdigest()

    r = client.post(
        "/files",
        headers=h,
        files={"upload": ("demo.bin", io.BytesIO(body), "application/octet-stream")},
    )
    assert r.status_code == 201, r.text
    meta = r.json()
    assert meta["size_bytes"] == len(body)
    assert meta["sha256"] == sha
    assert meta["filename"] == "demo.bin"

    # Download streams the bytes back byte-for-byte.
    r = client.get(f"/files/{meta['id']}", headers=h)
    assert r.status_code == 200
    assert r.content == body
    assert r.headers["content-type"].startswith("application/octet-stream")
    assert "demo.bin" in r.headers["content-disposition"]


def test_upload_attaches_to_entity(client, workspace):
    h = workspace["headers"]
    contact = client.post("/contacts", headers=h, json={"first_name": "Ada"}).json()

    r = client.post(
        "/files",
        headers=h,
        files={"upload": ("note.txt", io.BytesIO(b"hello"), "text/plain")},
        data={"entity_type": "contact", "entity_id": contact["id"]},
    )
    assert r.status_code == 201, r.text
    assert r.json()["entity_type"] == "contact"
    assert r.json()["entity_id"] == contact["id"]

    # The list endpoint filters by the entity linkage.
    r = client.get(
        f"/files?entity_type=contact&entity_id={contact['id']}",
        headers=h,
    )
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_upload_empty_file(client, workspace):
    """Edge case: zero-byte payload. SHA of empty string is well-known."""
    h = workspace["headers"]
    r = client.post(
        "/files",
        headers=h,
        files={"upload": ("empty.txt", io.BytesIO(b""), "text/plain")},
    )
    assert r.status_code == 201
    assert r.json()["size_bytes"] == 0
    assert r.json()["sha256"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_file_bytes_actually_land_in_storage(client, workspace, tmp_path, monkeypatch):
    """The storage_key should point at a real object. We verify by reading
    directly from the local storage backend."""
    h = workspace["headers"]
    body = _payload(512 * 1024)  # 512 KB — below the spill threshold

    r = client.post(
        "/files",
        headers=h,
        files={"upload": ("small.bin", io.BytesIO(body), "application/octet-stream")},
    )
    assert r.status_code == 201

    db = SessionLocal()
    try:
        f = db.scalars(select(File).where(File.filename == "small.bin")).one()
    finally:
        db.close()

    from app.services.storage import get_storage

    storage = get_storage()
    # get_storage returns LocalStorage in tests (STORAGE_BACKEND=local is default).
    fetched = storage.get(f.storage_key)
    assert fetched == body
    assert hashlib.sha256(fetched).hexdigest() == f.sha256


def test_delete_removes_file_and_storage(client, workspace):
    h = workspace["headers"]
    r = client.post(
        "/files",
        headers=h,
        files={"upload": ("doomed.txt", io.BytesIO(b"gone"), "text/plain")},
    ).json()

    d = client.delete(f"/files/{r['id']}", headers=h)
    assert d.status_code == 200

    # List no longer returns it.
    assert not any(f["id"] == r["id"] for f in client.get("/files", headers=h).json())

    # Storage object is gone too — follow-up GET yields 404.
    missing = client.get(f"/files/{r['id']}", headers=h)
    assert missing.status_code == 404
