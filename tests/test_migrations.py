"""Alembic upgrade-from-scratch smoke test.

Uses a dedicated database (TEST_MIGRATE_URL) so it never touches the
session-scoped create_all tables used by the rest of the suite.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

from alembic import command
from alembic.config import Config


@pytest.mark.postgres
def test_alembic_upgrade_head():
    url = os.environ.get(
        "TEST_DATABASE_URL",
        os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://nakatomi:nakatomi@localhost:5432/nakatomi",
        ),
    )
    migrate_url = os.environ.get("TEST_MIGRATE_URL")
    if not migrate_url:
        if "/nakatomi_test" in url:
            migrate_url = url.replace("/nakatomi_test", "/nakatomi_migrate")
        elif url.rstrip("/").endswith("/nakatomi"):
            migrate_url = url.rstrip("/") + "_migrate"
        else:
            pytest.skip("set TEST_MIGRATE_URL for migration smoke test")

    admin_url = url.rsplit("/", 1)[0] + "/postgres"
    db_name = migrate_url.rsplit("/", 1)[-1]
    try:
        admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": db_name}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        admin.dispose()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"cannot create migrate database: {exc}")

    eng = create_engine(migrate_url)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", migrate_url)
    command.upgrade(cfg, "head")

    with eng.connect() as conn:
        tables = {
            r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        }
    assert "workspaces" in tables
    assert "api_keys" in tables
    assert "approval_requests" in tables
    with eng.connect() as conn:
        cols = {
            r[0]
            for r in conn.execute(
                text("SELECT column_name FROM information_schema.columns " "WHERE table_name = 'api_keys'")
            )
        }
    assert "scopes" in cols
    eng.dispose()
