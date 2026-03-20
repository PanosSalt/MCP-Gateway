from __future__ import annotations

import pytest

from app.config import Settings, get_settings


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_settings_defaults():
    s = Settings(
        database_url="postgresql://user:pass@localhost/db",
        secret_key="test",
        encryption_key="test-key-32-bytes-long-padding!!",
    )
    assert s.algorithm == "HS256"
    assert s.access_token_expire_minutes == 15
    assert s.base_url == "http://localhost:8000"
    assert s.llm_model == "claude-sonnet-4-6"
    assert s.llm_max_tokens_sql == 1024
    assert s.llm_max_tokens_summary == 500


def test_get_settings_returns_instance():
    s = get_settings()
    assert isinstance(s, Settings)


def test_insecure_defaults_rejected_in_production():
    """Settings with default secrets must raise."""
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(
            database_url="postgresql://user:pass@localhost/prod",
            secret_key="change-this-in-production",
            encryption_key="some-safe-key-that-is-32-bytes!!",
        )

    with pytest.raises(ValueError, match="ENCRYPTION_KEY"):
        Settings(
            database_url="postgresql://user:pass@localhost/prod",
            secret_key="some-safe-secret-key-value-here!",
            encryption_key="change-this-32-byte-key-in-prod!!",
        )


