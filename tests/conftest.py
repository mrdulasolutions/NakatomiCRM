"""Pytest fixtures.

Tests require a real Postgres because we use JSONB. Point ``TEST_DATABASE_URL`` at
a clean database the test run can drop and recreate. In CI we use the ``postgres``
service container; locally you can point at the docker-compose Postgres.

    TEST_DATABASE_URL=postgresql+psycopg://nakatomi:nakatomi@localhost:5432/nakatomi_test pytest
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-" + "0" * 16)
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://nakatomi:nakatomi@localhost:5432/nakatomi",
    ),
)
os.environ.setdefault("MEMORY_CONNECTORS", "")  # disable real memory calls in tests
os.environ.setdefault("DASHBOARD_ENABLED", "false")
os.environ.setdefault("WEBHOOK_WORKER_ENABLED", "false")  # tests drive the worker directly

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ApiKey, MemberRole, Membership, User, Workspace  # noqa: E402
from app.security import generate_api_key, hash_password  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    """Create a clean schema once per test session.

    We bypass Alembic here and use ``Base.metadata.create_all`` — fast and
    deterministic. Any extensions or raw-SQL objects that migrations add
    (e.g. pg_trgm) have to be enabled here too, since ``create_all`` only
    creates tables.
    """
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        Base.metadata.drop_all(bind=conn)
        Base.metadata.create_all(bind=conn)
    yield
    with engine.begin() as conn:
        Base.metadata.drop_all(bind=conn)


@pytest.fixture(autouse=True)
def _truncate_between_tests() -> Iterator[None]:
    """Wipe every row between tests so tests stay independent."""
    yield
    with engine.begin() as conn:
        # Drop rows in FK-safe order by truncating with CASCADE.
        tables = [t.name for t in reversed(Base.metadata.sorted_tables)]
        conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def workspace() -> dict:
    """Create a workspace + owner user + API key via the ORM. Return a dict of handles."""
    db = SessionLocal()
    try:
        user = User(
            email=f"test-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("testtest1234"),
            display_name="Test Owner",
        )
        ws = Workspace(name="Test Workspace", slug=f"test-{uuid.uuid4().hex[:6]}")
        db.add_all([user, ws])
        db.flush()
        db.add(Membership(workspace_id=ws.id, user_id=user.id, role=MemberRole.owner))
        full, prefix, digest = generate_api_key()
        key = ApiKey(
            workspace_id=ws.id,
            user_id=user.id,
            name="test",
            prefix=prefix,
            key_hash=digest,
            role=MemberRole.owner,
        )
        db.add(key)
        db.commit()
        return {
            "user_id": user.id,
            "user_email": user.email,
            "workspace_id": ws.id,
            "workspace_slug": ws.slug,
            "api_key": full,
            "headers": {"Authorization": f"Bearer {full}"},
        }
    finally:
        db.close()
