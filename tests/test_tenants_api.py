"""Tests for app.api.tenants — tenant registration and user management."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_access_token, hash_password
from app.models import Role, Tenant, User

# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tenant_and_admin(db_session):
    tenant = Tenant(name="Tenant Corp", slug="tenant-corp")
    db_session.add(tenant)
    db_session.flush()
    admin = User(
        email="admin@tenant.com",
        hashed_password=hash_password("pw"),
        role=Role.admin,
        tenant_id=tenant.id,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(tenant)
    db_session.refresh(admin)
    return tenant, admin


@pytest.fixture
def admin_header(tenant_and_admin):
    _, admin = tenant_and_admin
    token = create_access_token(admin.id, admin.tenant_id, admin.role.value)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def viewer_header(db_session, tenant_and_admin):
    tenant, _ = tenant_and_admin
    viewer = User(
        email="viewer@tenant.com",
        hashed_password=hash_password("pw"),
        role=Role.viewer,
        tenant_id=tenant.id,
    )
    db_session.add(viewer)
    db_session.commit()
    db_session.refresh(viewer)
    token = create_access_token(viewer.id, tenant.id, viewer.role.value)
    return {"Authorization": f"Bearer {token}"}


# ── POST /tenants/ ────────────────────────────────────────────────────────────


def test_create_tenant_success(client: TestClient):
    resp = client.post(
        "/tenants/",
        json={
            "name": "New Corp",
            "slug": "new-corp",
            "admin_email": "admin@new.com",
            "admin_password": "SuperSecret123!",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "New Corp"
    assert body["slug"] == "new-corp"
    assert body["is_active"] is True
    assert "id" in body
    assert "created_at" in body


def test_create_tenant_duplicate_slug(client: TestClient):
    payload = {
        "name": "First",
        "slug": "dup-slug",
        "admin_email": "a@first.com",
        "admin_password": "SuperSecret123!",
    }
    client.post("/tenants/", json=payload)

    resp = client.post(
        "/tenants/",
        json={**payload, "name": "Second", "admin_email": "a@second.com"},
    )
    assert resp.status_code == 400
    assert "Slug already taken" in resp.json()["detail"]


def test_create_tenant_creates_admin_user(client: TestClient):
    """Tenant creation implicitly creates an admin user that can log in."""
    client.post(
        "/tenants/",
        json={
            "name": "Login Corp",
            "slug": "login-corp",
            "admin_email": "admin@login.com",
            "admin_password": "SuperSecret123!",
        },
    )
    login_resp = client.post(
        "/auth/login",
        json={"email": "admin@login.com", "password": "SuperSecret123!"},
    )
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()


# ── GET /tenants/me ───────────────────────────────────────────────────────────


def test_get_my_tenant(client: TestClient, tenant_and_admin, admin_header):
    tenant, _ = tenant_and_admin
    resp = client.get("/tenants/me", headers=admin_header)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == tenant.id
    assert body["slug"] == "tenant-corp"


def test_get_my_tenant_requires_auth(client: TestClient):
    resp = client.get("/tenants/me")
    assert resp.status_code in (401, 403)


# ── GET /tenants/users ────────────────────────────────────────────────────────


def test_list_users_admin(client: TestClient, tenant_and_admin, admin_header):
    resp = client.get("/tenants/users", headers=admin_header)
    assert resp.status_code == 200
    users = resp.json()
    assert isinstance(users, list)
    assert len(users) >= 1
    emails = [u["email"] for u in users]
    assert "admin@tenant.com" in emails


def test_list_users_viewer_forbidden(client: TestClient, viewer_header):
    resp = client.get("/tenants/users", headers=viewer_header)
    assert resp.status_code == 403


def test_list_users_scoped_to_tenant(client: TestClient, db_session, tenant_and_admin, admin_header):
    """Users from another tenant are not visible."""
    other_tenant = Tenant(name="Other", slug="other")
    db_session.add(other_tenant)
    db_session.flush()
    other_user = User(
        email="other@other.com",
        hashed_password=hash_password("pw"),
        role=Role.viewer,
        tenant_id=other_tenant.id,
    )
    db_session.add(other_user)
    db_session.commit()

    resp = client.get("/tenants/users", headers=admin_header)
    emails = [u["email"] for u in resp.json()]
    assert "other@other.com" not in emails


# ── POST /tenants/users ───────────────────────────────────────────────────────


def test_create_user_success(client: TestClient, tenant_and_admin, admin_header):
    resp = client.post(
        "/tenants/users",
        json={"email": "new@tenant.com", "password": "SuperSecret123!", "role": "analyst"},
        headers=admin_header,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "new@tenant.com"
    assert body["role"] == "analyst"
    assert body["auth_provider"] == "local"


def test_create_user_duplicate_email(client: TestClient, tenant_and_admin, admin_header):
    client.post(
        "/tenants/users",
        json={"email": "dup@tenant.com", "password": "SuperSecret123!"},
        headers=admin_header,
    )
    resp = client.post(
        "/tenants/users",
        json={"email": "dup@tenant.com", "password": "SuperSecret123!"},
        headers=admin_header,
    )
    assert resp.status_code == 400
    assert "already registered" in resp.json()["detail"]


def test_create_user_requires_admin(client: TestClient, viewer_header):
    resp = client.post(
        "/tenants/users",
        json={"email": "x@x.com", "password": "SuperSecret123!"},
        headers=viewer_header,
    )
    assert resp.status_code == 403


def test_create_user_default_role_is_viewer(client: TestClient, tenant_and_admin, admin_header):
    resp = client.post(
        "/tenants/users",
        json={"email": "default@tenant.com", "password": "SuperSecret123!"},
        headers=admin_header,
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "viewer"
