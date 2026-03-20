"""Tests for app.api.auth — local password login endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.auth import hash_password
from app.models import AuthProvider, Role, Tenant, User


@pytest.fixture
def tenant_and_admin(db_session):
    tenant = Tenant(name="Auth Corp", slug="auth-corp")
    db_session.add(tenant)
    db_session.flush()
    admin = User(
        email="admin@auth.com",
        hashed_password=hash_password("correct-password"),
        role=Role.admin,
        tenant_id=tenant.id,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return tenant, admin


def test_login_success(client: TestClient, tenant_and_admin):
    _, admin = tenant_and_admin
    resp = client.post(
        "/auth/login",
        json={"email": admin.email, "password": "correct-password"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 20


def test_login_wrong_password(client: TestClient, tenant_and_admin):
    _, admin = tenant_and_admin
    resp = client.post(
        "/auth/login",
        json={"email": admin.email, "password": "wrong-password"},
    )
    assert resp.status_code == 401
    assert "Invalid" in resp.json()["detail"]


def test_login_unknown_email(client: TestClient, tenant_and_admin):
    resp = client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "anything"},
    )
    assert resp.status_code == 401
    # Same message as wrong password — prevents user enumeration
    assert "Invalid" in resp.json()["detail"]


def test_login_disabled_account(client: TestClient, db_session, tenant_and_admin):
    tenant, admin = tenant_and_admin
    admin.is_active = False
    db_session.commit()

    resp = client.post(
        "/auth/login",
        json={"email": admin.email, "password": "correct-password"},
    )
    assert resp.status_code == 403
    assert "disabled" in resp.json()["detail"].lower()


def test_login_entra_user_has_no_password(client: TestClient, db_session, tenant_and_admin):
    """Entra SSO users have no hashed_password and cannot log in via local auth."""
    tenant, _ = tenant_and_admin
    entra_user = User(
        email="sso@company.com",
        hashed_password=None,
        role=Role.viewer,
        auth_provider=AuthProvider.entra,
        entra_oid="some-oid",
        tenant_id=tenant.id,
    )
    db_session.add(entra_user)
    db_session.commit()

    resp = client.post(
        "/auth/login",
        json={"email": "sso@company.com", "password": "anything"},
    )
    assert resp.status_code == 401


def test_login_token_is_usable(client: TestClient, tenant_and_admin):
    """A token from login must work on a protected endpoint."""
    _, admin = tenant_and_admin
    login_resp = client.post(
        "/auth/login",
        json={"email": admin.email, "password": "correct-password"},
    )
    token = login_resp.json()["access_token"]

    me_resp = client.get(
        "/tenants/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["slug"] == "auth-corp"
