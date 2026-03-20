from __future__ import annotations

import os
from collections.abc import Generator
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
# PyJWT (HS256) warns if the HMAC secret is under 32 bytes; keep tests quiet.
os.environ.setdefault(
    "SECRET_KEY",
    "unit-test-jwt-secret-key-32-bytes-minimum-length!!",
)
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key-for-32bytes!!")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app

engine_test = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine_test
)


@pytest.fixture(autouse=True)
def setup_db() -> Generator[None, None, None]:
    Base.metadata.create_all(bind=engine_test)
    yield
    Base.metadata.drop_all(bind=engine_test)


@pytest.fixture
def db_session(setup_db: None) -> Generator[Session, None, None]:
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(setup_db: None) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        session = TestSessionLocal()
        try:
            yield session
        finally:
            session.close()

    # Stub the Alembic migration-state check in the /health endpoint.
    # Tests use create_all rather than running migrations, so the
    # alembic_version table never exists and the check would return 503.
    _mock_script = MagicMock()
    _mock_script.get_heads.return_value = []
    _mock_ctx = MagicMock()
    _mock_ctx.get_current_heads.return_value = []

    app.dependency_overrides[get_db] = _override_get_db
    with (
        patch("app.main._ScriptDirectory") as mock_sd,
        patch("app.main._MigrationContext") as mock_mc,
    ):
        mock_sd.from_config.return_value = _mock_script
        mock_mc.configure.return_value = _mock_ctx
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()
