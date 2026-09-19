"""Tests for app.tools.filesystem — sandboxing, RBAC and audit metadata."""
from __future__ import annotations

import os

import pytest

from app.models import AuditLog, Role, Tenant, User
from app.tools import ToolContext
from app.tools.filesystem import (
    FilesystemToolProvider,
    _allowed_dirs,
    _audit_metadata,
    _configured_dirs,
    _validate_path,
)

# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_dir_caches():
    """The allowed-dir lookups are lru_cached; reset around every test."""
    _configured_dirs.cache_clear()
    _allowed_dirs.cache_clear()
    yield
    _configured_dirs.cache_clear()
    _allowed_dirs.cache_clear()


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point FILESYSTEM_ALLOWED_DIRS at a temp dir and clear cached settings."""
    from app.config import get_settings

    root = tmp_path / "sandbox"
    root.mkdir()
    (root / "notes.txt").write_text("hello world", encoding="utf-8")

    monkeypatch.setenv("FILESYSTEM_ALLOWED_DIRS", str(root))
    get_settings.cache_clear()
    _configured_dirs.cache_clear()
    _allowed_dirs.cache_clear()
    yield root
    get_settings.cache_clear()


@pytest.fixture
def user(db_session):
    tenant = Tenant(name="FS Corp", slug="fs-corp")
    db_session.add(tenant)
    db_session.flush()
    u = User(
        email="admin@fs.com",
        hashed_password="x",
        role=Role.admin,
        tenant_id=tenant.id,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


def _ctx(db_session, user, ip="10.0.0.1"):
    return ToolContext(user=user, db=db_session, ip=ip)


# ── path sandboxing ──────────────────────────────────────────────────────────


def test_validate_path_accepts_file_inside_sandbox(sandbox):
    assert _validate_path(str(sandbox / "notes.txt")) == str(
        sandbox / "notes.txt"
    )


def test_validate_path_rejects_traversal_escape(sandbox):
    with pytest.raises(PermissionError):
        _validate_path(str(sandbox / ".." / "escaped.txt"))


def test_validate_path_rejects_sibling_with_shared_prefix(tmp_path, monkeypatch):
    """`/x/sandbox-evil` must not pass because it starts with `/x/sandbox`."""
    from app.config import get_settings

    allowed = tmp_path / "sandbox"
    allowed.mkdir()
    evil = tmp_path / "sandbox-evil"
    evil.mkdir()
    (evil / "f.txt").write_text("x", encoding="utf-8")

    monkeypatch.setenv("FILESYSTEM_ALLOWED_DIRS", str(allowed))
    get_settings.cache_clear()
    _configured_dirs.cache_clear()
    _allowed_dirs.cache_clear()
    try:
        with pytest.raises(PermissionError):
            _validate_path(str(evil / "f.txt"))
    finally:
        get_settings.cache_clear()


def test_validate_path_rejects_everything_when_unconfigured(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("FILESYSTEM_ALLOWED_DIRS", "")
    get_settings.cache_clear()
    _configured_dirs.cache_clear()
    _allowed_dirs.cache_clear()
    try:
        with pytest.raises(PermissionError):
            _validate_path("/etc/passwd")
    finally:
        get_settings.cache_clear()


def test_allowed_dirs_drops_nonexistent_entries(tmp_path, monkeypatch):
    from app.config import get_settings

    real = tmp_path / "real"
    real.mkdir()
    monkeypatch.setenv(
        "FILESYSTEM_ALLOWED_DIRS", f"{real},{tmp_path / 'ghost'}"
    )
    get_settings.cache_clear()
    _configured_dirs.cache_clear()
    _allowed_dirs.cache_clear()
    try:
        assert len(_configured_dirs()) == 2
        assert _allowed_dirs() == (str(real),)
    finally:
        get_settings.cache_clear()


# ── tool exposure ────────────────────────────────────────────────────────────


def test_tools_hidden_when_no_allowed_dirs(db_session, user, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("FILESYSTEM_ALLOWED_DIRS", "")
    get_settings.cache_clear()
    _configured_dirs.cache_clear()
    _allowed_dirs.cache_clear()
    try:
        provider = FilesystemToolProvider()
        assert provider.get_tools(_ctx(db_session, user)) == []
        assert provider.get_tool_defaults(_ctx(db_session, user)) == []
    finally:
        get_settings.cache_clear()


def test_tools_exposed_when_configured(sandbox, db_session, user):
    provider = FilesystemToolProvider()
    names = {t.name for t in provider.get_tools(_ctx(db_session, user))}
    assert "fs_read_file" in names
    assert "fs_write_file" in names


def test_viewer_cannot_see_write_tools(sandbox, db_session, user):
    user.role = Role.viewer
    db_session.commit()
    provider = FilesystemToolProvider()
    names = {t.name for t in provider.get_tools(_ctx(db_session, user))}
    assert "fs_write_file" not in names
    assert "fs_read_file" not in names  # read requires analyst


# ── RBAC on dispatch ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyst_denied_write(sandbox, db_session, user):
    user.role = Role.analyst
    db_session.commit()
    provider = FilesystemToolProvider()
    result = await provider.handle(
        "fs_write_file",
        {"path": str(sandbox / "new.txt"), "content": "data"},
        _ctx(db_session, user),
    )
    assert result is not None
    assert "Permission denied" in result[0].text
    assert not (sandbox / "new.txt").exists()

    events = [a.event for a in db_session.query(AuditLog).all()]
    assert "fs.fs_write_file.denied" in events


@pytest.mark.asyncio
async def test_unknown_tool_passes_through(sandbox, db_session, user):
    provider = FilesystemToolProvider()
    assert await provider.handle("not_a_tool", {}, _ctx(db_session, user)) is None


# ── audit metadata ───────────────────────────────────────────────────────────


def test_audit_metadata_redacts_file_content():
    meta = _audit_metadata("fs_write_file", {"path": "/x/f", "content": "s" * 5000})
    assert meta["args"]["content"] == "<5000 chars>"
    assert "sssss" not in str(meta)


def test_audit_metadata_records_resolved_path(tmp_path):
    target = tmp_path / "f.txt"
    meta = _audit_metadata("fs_read_file", {"path": str(tmp_path / ".." / tmp_path.name / "f.txt")})
    assert meta["args"]["path_resolved"] == os.path.realpath(str(target))


@pytest.mark.asyncio
async def test_successful_read_is_audited_with_path(sandbox, db_session, user):
    provider = FilesystemToolProvider()
    result = await provider.handle(
        "fs_read_file", {"path": str(sandbox / "notes.txt")}, _ctx(db_session, user),
    )
    assert result[0].text == "hello world"

    entry = db_session.query(AuditLog).filter(
        AuditLog.event == "fs.fs_read_file"
    ).one()
    assert entry.metadata_["args"]["path_resolved"] == str(sandbox / "notes.txt")
    assert entry.ip_address == "10.0.0.1"


@pytest.mark.asyncio
async def test_write_audit_never_contains_file_content(sandbox, db_session, user):
    provider = FilesystemToolProvider()
    secret = "SUPER_SECRET_PAYROLL_DATA"
    await provider.handle(
        "fs_write_file",
        {"path": str(sandbox / "out.txt"), "content": secret},
        _ctx(db_session, user),
    )
    entry = db_session.query(AuditLog).filter(
        AuditLog.event == "fs.fs_write_file"
    ).one()
    assert secret not in str(entry.metadata_)
    assert entry.metadata_["args"]["content"] == f"<{len(secret)} chars>"


@pytest.mark.asyncio
async def test_error_audit_includes_the_attempted_path(sandbox, db_session, user):
    """A blocked traversal must record *which* path was attempted."""
    provider = FilesystemToolProvider()
    outside = str(sandbox.parent / "outside.txt")
    result = await provider.handle(
        "fs_read_file", {"path": outside}, _ctx(db_session, user),
    )
    assert "Error" in result[0].text

    entry = db_session.query(AuditLog).filter(
        AuditLog.event == "fs.fs_read_file.error"
    ).one()
    assert entry.metadata_["args"]["path_resolved"] == os.path.realpath(outside)
    assert "error" in entry.metadata_
