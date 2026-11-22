"""Portable workspace archives and short-lived browser download grants."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from tempfile import SpooledTemporaryFile
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile

import jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ApiKey, MemberRole, Workspace
from app.oauth_grants import active_membership, oauth_metadata, oauth_scopes
from app.scopes import has_scope
from app.services.export import build_export
from app.services.storage import get_storage

ExportTarget = Literal["railway", "vps", "local"]
DOWNLOAD_SECONDS = 600
EXPORT_AUDIENCE = "nakatomi-workspace-archive"
EXPORT_ROLES = (MemberRole.owner, MemberRole.admin)

_SETUP = {
    "railway": "Deploy Nakatomi on Railway with PostgreSQL and a persistent volume or S3 storage.",
    "vps": "Deploy Nakatomi with PostgreSQL and persistent file storage on your VPS, for example with Docker Compose.",
    "local": "Start Nakatomi and PostgreSQL locally, for example with docker compose up -d.",
}


def can_export_archive(role: MemberRole, key: ApiKey | None) -> bool:
    metadata = (key.data or {}) if key else {}
    if key and (grant := oauth_metadata(key)):
        return role in EXPORT_ROLES and "mcp:export" in grant.get("scope", "").split()
    return role in EXPORT_ROLES or (metadata.get("agent") is True and metadata.get("allow_export") is True)


def issue_download_grant(
    workspace_id: str, api_key_id: str, target: ExportTarget, include_timeline: bool, include_files: bool
) -> str:
    return jwt.encode(
        {
            "aud": EXPORT_AUDIENCE,
            "workspace": workspace_id,
            "key": api_key_id,
            "target": target,
            "timeline": include_timeline,
            "files": include_files,
            "exp": datetime.now(UTC) + timedelta(seconds=DOWNLOAD_SECONDS),
        },
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def validate_download_grant(db: Session, token: str) -> dict | None:
    try:
        claims = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            audience=EXPORT_AUDIENCE,
            options={"require": ["exp", "aud", "workspace", "key", "target", "timeline", "files"]},
        )
    except jwt.InvalidTokenError:
        return None
    if claims["target"] not in _SETUP:
        return None

    key = db.get(ApiKey, claims["key"])
    if not key or key.workspace_id != claims["workspace"] or key.revoked_at:
        return None
    if key.expires_at and key.expires_at <= datetime.now(UTC):
        return None
    role, scopes = key.role, key.scopes
    grant = oauth_metadata(key)
    if grant:
        membership = active_membership(db, key)
        if not membership or grant.get("kind") != "access":
            return None
        role = membership.role
        current = oauth_scopes(grant.get("scope", "mcp"), role)
        scopes = [scope for scope in current if scope in (key.scopes or [])]
    if not can_export_archive(role, key) or not has_scope(scopes, "export:read"):
        return None
    if claims["files"] and not has_scope(scopes, "files:read"):
        return None
    return claims


def build_archive(
    db: Session, workspace: Workspace, *, target: ExportTarget, include_timeline: bool, include_files: bool
) -> SpooledTemporaryFile[bytes]:
    """Spool the ZIP to disk as needed. The caller owns the returned file."""
    document = build_export(db, workspace, include_timeline=include_timeline)
    file_entries = []
    archive = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")  # noqa: SIM115 — caller closes stream
    try:
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
            bundle.writestr("workspace.json", json.dumps(document, ensure_ascii=False))
            if include_files:
                storage = get_storage()
                for file in document["files"]:
                    key = file["storage_key"]
                    path = PurePosixPath(key)
                    if (
                        path.is_absolute()
                        or not path.parts
                        or path.parts[0] != workspace.id
                        or ".." in path.parts
                        or "\\" in key
                    ):
                        raise ValueError("A file has an unsupported storage key")
                    member = f"attachments/{file['id']}"
                    with storage.open(key) as source, bundle.open(member, "w", force_zip64=True) as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                    file_entries.append({"path": member, "storage_key": key, "filename": file["filename"]})
            bundle.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format": "nakatomi-workspace-archive",
                        "version": 1,
                        "target": target,
                        "include_timeline": include_timeline,
                        "include_files": include_files,
                        "attachments": file_entries,
                    },
                    indent=2,
                ),
            )
            bundle.writestr(
                "RESTORE.md",
                f"""# Restore a Nakatomi workspace

{_SETUP[target]}

1. Sign into the destination installation and select the destination workspace.
2. Optionally copy each attachment from its ZIP path to its exact storage key
   from manifest.json. For local storage, keys are relative to STORAGE_LOCAL_PATH.
   For S3 storage, use the configured bucket and exact object keys. Only copy
   attachments into storage you administer and check for conflicting objects.
3. Send workspace.json as the doc field to POST /import using an owner or admin
   credential that has export:write. Start with dry_run=true to inspect counts
   and warnings, then repeat with dry_run=false to apply.
4. Reconfigure deployment secrets and any integrations on the destination.

The importer merges supported workspace records. Timeline events, when
included, are for reference. File metadata may be present without file bytes.
This archive does not contain the Nakatomi application, database credentials,
API keys, OAuth grants, or a full PostgreSQL backup.
""",
            )
        archive.seek(0)
        return archive
    except BaseException:
        archive.close()
        raise
