"""Tests for Alembic migrations — verify schema matches models with no drift."""
from __future__ import annotations

from sqlalchemy import create_engine, inspect

import app.models  # noqa: F401 — register all models
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from app.database import Base

ALEMBIC_INI = "alembic.ini"


def _alembic_cfg(db_url: str) -> Config:
    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_upgrade_head_creates_all_tables(tmp_path, monkeypatch):
    """Running upgrade head on a fresh DB creates all expected tables."""
    db_path = tmp_path / "test_migration.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    command.upgrade(_alembic_cfg(db_url), "head")

    engine = create_engine(db_url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert "tenants" in tables
    assert "users" in tables
    assert "db_connections" in tables
    assert "tenant_entra_configs" in tables
    assert "api_keys" in tables
    assert "audit_logs" in tables
    assert "oauth_states" in tables
    assert "alembic_version" in tables


def test_no_schema_drift(tmp_path, monkeypatch):
    """After upgrade head, autogenerate detects no further changes (models == DB)."""
    db_path = tmp_path / "test_migration.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    command.upgrade(_alembic_cfg(db_url), "head")

    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            migration_ctx = MigrationContext.configure(conn)
            diff = compare_metadata(migration_ctx, Base.metadata)
    finally:
        engine.dispose()

    assert diff == [], f"Schema drift detected — models and DB differ: {diff}"


def test_downgrade_removes_all_tables(tmp_path, monkeypatch):
    """Downgrade to base removes all application tables."""
    db_path = tmp_path / "test_migration.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    cfg = _alembic_cfg(db_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    engine = create_engine(db_url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert "tenants" not in tables
    assert "users" not in tables
    assert "db_connections" not in tables
    assert "tenant_entra_configs" not in tables
