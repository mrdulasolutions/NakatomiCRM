import json
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import urlsplit
from zipfile import ZipFile

import pytest
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.mcp_server import export_workspace_zip
from app.models import ApiKey, MemberRole
from app.security import hash_api_key


def _context(workspace):
    request = SimpleNamespace(
        headers=workspace["headers"]
        | {
            "authorization": workspace["headers"]["Authorization"],
        },
        base_url="http://testserver/",
    )
    return SimpleNamespace(request_context=SimpleNamespace(request=request))


@pytest.mark.parametrize("target", ["railway", "vps", "local"])
def test_agent_export_download_and_import_dry_run(client, workspace, target):
    client.post("/contacts", headers=workspace["headers"], json={"first_name": "Zip Contact"})
    link = export_workspace_zip(_context(workspace), target=target, include_timeline=True)
    url = urlsplit(link["download_url"])
    assert url.path == "/export/archive" and not url.query and url.fragment
    assert client.get(url.path).status_code == 200

    response = client.post(f"{url.path}/download", data={"token": url.fragment})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "private, no-store"
    with ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["target"] == target
        document = json.loads(archive.read("workspace.json"))
        assert "timeline_events" in document
        assert document["contacts"][0]["first_name"] == "Zip Contact"
        assert "POST /import" in archive.read("RESTORE.md").decode()
    result = client.post("/import", headers=workspace["headers"], json={"doc": document, "dry_run": True})
    assert result.status_code == 200, result.text


def test_agent_export_attachments_and_live_permissions(client, workspace, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))
    upload = client.post("/files", headers=workspace["headers"], files={"upload": ("copy.txt", b"file data")})
    assert upload.status_code == 201, upload.text
    ctx = _context(workspace)
    token = urlsplit(export_workspace_zip(ctx, include_files=True)["download_url"]).fragment
    response = client.post("/export/archive/download", data={"token": token})
    assert response.status_code == 200, response.text
    with ZipFile(BytesIO(response.content)) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        assert bundle.read(manifest["attachments"][0]["path"]) == b"file data"
    with SessionLocal.begin() as db:
        key = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(workspace["api_key"])))
        key.role = MemberRole.member
    assert client.post("/export/archive/download", data={"token": token}).status_code == 403
    with pytest.raises(RuntimeError, match="explicitly export-enabled agent"):
        export_workspace_zip(ctx)


def test_export_permission_can_be_delegated_to_a_headless_agent(client, workspace, monkeypatch):
    monkeypatch.setattr(settings, "DASHBOARD_ENABLED", True)
    headers = {"Origin": "http://testserver"}
    login = client.post(
        "/dashboard/session",
        json={
            "email": workspace["user_email"],
            "password": "testtest1234",
        },
        headers=headers,
    )
    assert login.status_code == 200, login.text
    created = client.post(
        "/dashboard/agents",
        json={
            "name": "Headless exporter",
            "can_export": True,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    ctx = _context({"headers": {"Authorization": f"Bearer {created.json()['token']}"}})
    link = export_workspace_zip(ctx)
    assert (
        client.post(
            "/export/archive/download", data={"token": urlsplit(link["download_url"]).fragment}
        ).status_code
        == 200
    )
