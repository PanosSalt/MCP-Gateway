"""Tests for app.api.api_keys — API key CRUD endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_access_token, hash_password
from app.models import Role, Tenant, User


@pytest.fixture
def setup_data(db_session):
    tenant = Tenant(name="Key Corp", slug="key-corp")
    db_session.add(tenant)
    db_session.flush()

    admin = User(
        email="admin@key.com",
        hashed_password=hash_password("pw"),
        role=Role.admin,
        tenant_id=tenant.id,
    )
    viewer = User(
        email="viewer@key.com",
        hashed_password=hash_password("pw"),
        role=Role.viewer,
        tenant_id=tenant.id,
    )
    db_session.add_all([admin, viewer])
    db_session.commit()
    db_session.refresh(admin)
    db_session.refresh(viewer)
    return tenant, admin, viewer


def _auth_header(user: User) -> dict:
    token = create_access_token(user.id, user.tenant_id, user.role.value)
    return {"Authorization": f"Bearer {token}"}


# ── create key ───────────────────────────────────────────────────────


def test_create_api_key_returns_raw_key_once(client: TestClient, setup_data):
    _, admin, _ = setup_data
    resp = client.post(
        "/api-keys",
        json={"name": "Claude Desktop"},
        headers=_auth_header(admin),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "raw_key" in body
    assert body["raw_key"].startswith("mgw_")
    assert body["raw_key"].startswith(body["prefix"] + "_")
    assert body["name"] == "Claude Desktop"
    assert "id" in body


def test_create_api_key_requires_auth(client: TestClient, setup_data):
    resp = client.post("/api-keys", json={"name": "test"})
    assert resp.status_code == 401


def test_create_api_key_name_required(client: TestClient, setup_data):
    _, admin, _ = setup_data
    resp = client.post("/api-keys", json={}, headers=_auth_header(admin))
    assert resp.status_code == 422


# ── list keys ────────────────────────────────────────────────────────


def test_list_api_keys_hides_raw_key(client: TestClient, setup_data):
    _, admin, _ = setup_data
    client.post("/api-keys", json={"name": "Key1"}, headers=_auth_header(admin))

    resp = client.get("/api-keys", headers=_auth_header(admin))
    assert resp.status_code == 200
    keys = resp.json()
    assert len(keys) == 1
    assert "raw_key" not in keys[0]
    assert "hashed_key" not in keys[0]
    assert keys[0]["name"] == "Key1"


def test_list_api_keys_isolated_per_user(client: TestClient, setup_data):
    _, admin, viewer = setup_data
    client.post("/api-keys", json={"name": "AdminKey"}, headers=_auth_header(admin))

    resp = client.get("/api-keys", headers=_auth_header(viewer))
    assert resp.status_code == 200
    assert resp.json() == []


# ── revoke key ───────────────────────────────────────────────────────


def test_revoke_api_key(client: TestClient, setup_data):
    _, admin, _ = setup_data
    create_resp = client.post(
        "/api-keys", json={"name": "ToRevoke"}, headers=_auth_header(admin)
    )
    key_id = create_resp.json()["id"]

    revoke_resp = client.delete(f"/api-keys/{key_id}", headers=_auth_header(admin))
    assert revoke_resp.status_code == 204

    # Key still appears in list (soft delete) but with revoked_at set
    list_resp = client.get("/api-keys", headers=_auth_header(admin))
    key = next(k for k in list_resp.json() if k["id"] == key_id)
    assert key["revoked_at"] is not None


def test_revoke_other_users_key_returns_404(client: TestClient, setup_data):
    _, admin, viewer = setup_data
    create_resp = client.post(
        "/api-keys", json={"name": "AdminKey"}, headers=_auth_header(admin)
    )
    key_id = create_resp.json()["id"]

    resp = client.delete(f"/api-keys/{key_id}", headers=_auth_header(viewer))
    assert resp.status_code == 404


def test_revoke_nonexistent_key_returns_404(client: TestClient, setup_data):
    _, admin, _ = setup_data
    resp = client.delete("/api-keys/nonexistent-id", headers=_auth_header(admin))
    assert resp.status_code == 404


# ── api_key authentication ───────────────────────────────────────────


def test_api_key_authenticates_on_protected_endpoint(client: TestClient, setup_data):
    _, admin, _ = setup_data
    create_resp = client.post(
        "/api-keys", json={"name": "Test Key"}, headers=_auth_header(admin)
    )
    raw_key = create_resp.json()["raw_key"]

    # Use the raw key to hit a protected endpoint via query param
    resp = client.get("/api-keys", params={"api_key": raw_key})
    assert resp.status_code == 200


def test_revoked_key_rejected(client: TestClient, setup_data):
    _, admin, _ = setup_data
    create_resp = client.post(
        "/api-keys", json={"name": "ToRevoke"}, headers=_auth_header(admin)
    )
    key_id = create_resp.json()["id"]
    raw_key = create_resp.json()["raw_key"]

    client.delete(f"/api-keys/{key_id}", headers=_auth_header(admin))

    resp = client.get("/api-keys", params={"api_key": raw_key})
    assert resp.status_code == 401


def test_invalid_api_key_rejected(client: TestClient, setup_data):
    resp = client.get("/api-keys", params={"api_key": "mgw_bad_key"})
    assert resp.status_code == 401


# ── jwt still works (regression) ─────────────────────────────────────


def test_jwt_still_works_on_protected_endpoint(client: TestClient, setup_data):
    _, admin, _ = setup_data
    resp = client.get("/api-keys", headers=_auth_header(admin))
    assert resp.status_code == 200


def test_jwt_still_works_on_tenants_me(client: TestClient, setup_data):
    _, admin, _ = setup_data
    resp = client.get("/tenants/me", headers=_auth_header(admin))
    assert resp.status_code == 200


