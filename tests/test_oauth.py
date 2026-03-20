"""Tests for app.api.oauth — MCP OAuth 2.0 endpoints."""
from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.auth import hash_password
from app.models import (
    AuthProvider,
    OAuthAuthorizationCode,
    OAuthRefreshToken,
    OAuthState,
    Role,
    Tenant,
    TenantEntraConfig,
    User,
)

# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tenant_and_admin(db_session):
    tenant = Tenant(name="OAuth Corp", slug="oauth-corp")
    db_session.add(tenant)
    db_session.flush()
    admin = User(
        email="admin@oauth.com",
        hashed_password=hash_password("secret123"),
        role=Role.admin,
        tenant_id=tenant.id,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(tenant)
    db_session.refresh(admin)
    return tenant, admin


def _pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code_verifier and code_challenge (S256)."""
    verifier = secrets.token_urlsafe(32)
    digest = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, digest


# ── Discovery ────────────────────────────────────────────────────────────────


def test_discovery_returns_correct_endpoints(client: TestClient, tenant_and_admin):
    tenant, _ = tenant_and_admin
    resp = client.get(f"/t/{tenant.slug}/.well-known/oauth-authorization-server")
    assert resp.status_code == 200
    body = resp.json()
    assert body["issuer"].endswith(f"/t/{tenant.slug}")
    assert f"/t/{tenant.slug}/oauth/authorize" in body["authorization_endpoint"]
    assert f"/t/{tenant.slug}/oauth/token" in body["token_endpoint"]
    assert f"/t/{tenant.slug}/oauth/register" in body["registration_endpoint"]
    assert "S256" in body["code_challenge_methods_supported"]


def test_discovery_unknown_tenant(client: TestClient):
    resp = client.get("/t/nonexistent/.well-known/oauth-authorization-server")
    assert resp.status_code == 200


# ── Authorize ────────────────────────────────────────────────────────────────


def test_authorize_unknown_tenant_returns_404(client: TestClient):
    _, challenge = _pkce_pair()
    resp = client.get(
        "/t/nonexistent/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "mcp-remote",
            "redirect_uri": "http://localhost:9999/callback",
            "state": "test-state",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 404


def test_authorize_shows_login_form_for_local_tenant(client: TestClient, tenant_and_admin):
    tenant, _ = tenant_and_admin
    _, challenge = _pkce_pair()
    resp = client.get(
        f"/t/{tenant.slug}/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "mcp-remote",
            "redirect_uri": "http://localhost:9999/callback",
            "state": "test-state",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "Sign in" in resp.text
    assert "email" in resp.text


def test_authorize_rejects_non_localhost_redirect(client: TestClient, tenant_and_admin):
    tenant, _ = tenant_and_admin
    _, challenge = _pkce_pair()
    resp = client.get(
        f"/t/{tenant.slug}/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "mcp-remote",
            "redirect_uri": "https://evil.com/callback",
            "state": "test-state",
            "code_challenge": challenge,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400


# ── Login Submit ─────────────────────────────────────────────────────────────


def _setup_state(db_session, tenant, challenge):
    """Create an OAuthState row for testing login/token flows."""
    state = secrets.token_urlsafe(16)
    db_session.add(OAuthState(
        state=state,
        tenant_slug=tenant.slug,
        expires_at=datetime.now(tz=timezone.utc) + timedelta(minutes=10),
        code_challenge=challenge,
        code_challenge_method="S256",
        redirect_uri="http://localhost:9999/callback",
        client_id="mcp-remote",
    ))
    db_session.commit()
    return state


def test_login_submit_invalid_password_shows_error(client: TestClient, db_session, tenant_and_admin):
    tenant, admin = tenant_and_admin
    _, challenge = _pkce_pair()
    state = _setup_state(db_session, tenant, challenge)

    resp = client.post(
        f"/t/{tenant.slug}/oauth/login",
        data={"email": admin.email, "password": "wrong", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "Invalid email or password" in resp.text


def test_login_submit_valid_issues_code_and_redirects(client: TestClient, db_session, tenant_and_admin):
    tenant, admin = tenant_and_admin
    _, challenge = _pkce_pair()
    state = _setup_state(db_session, tenant, challenge)

    resp = client.post(
        f"/t/{tenant.slug}/oauth/login",
        data={"email": admin.email, "password": "secret123", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "code=" in location
    assert f"state={state}" in location
    assert location.startswith("http://localhost:9999/callback")


# ── Token Exchange ───────────────────────────────────────────────────────────


def _create_auth_code(db_session, tenant, admin, challenge):
    """Create a ready-to-exchange authorization code."""
    code = secrets.token_urlsafe(32)
    db_session.add(OAuthAuthorizationCode(
        code=code,
        tenant_id=tenant.id,
        user_id=admin.id,
        redirect_uri="http://localhost:9999/callback",
        code_challenge=challenge,
        code_challenge_method="S256",
        expires_at=datetime.now(tz=timezone.utc) + timedelta(minutes=5),
    ))
    db_session.commit()
    return code


def test_token_exchange_valid_code_returns_tokens(client: TestClient, db_session, tenant_and_admin):
    tenant, admin = tenant_and_admin
    verifier, challenge = _pkce_pair()
    code = _create_auth_code(db_session, tenant, admin, challenge)

    resp = client.post(
        f"/t/{tenant.slug}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": "http://localhost:9999/callback",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0


def test_token_exchange_used_code_rejected(client: TestClient, db_session, tenant_and_admin):
    tenant, admin = tenant_and_admin
    verifier, challenge = _pkce_pair()
    code = _create_auth_code(db_session, tenant, admin, challenge)

    client.post(
        f"/t/{tenant.slug}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": "http://localhost:9999/callback",
        },
    )

    resp = client.post(
        f"/t/{tenant.slug}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": "http://localhost:9999/callback",
        },
    )
    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"].lower() or "invalid" in resp.json()["detail"].lower()


def test_token_exchange_bad_pkce_rejected(client: TestClient, db_session, tenant_and_admin):
    tenant, admin = tenant_and_admin
    _, challenge = _pkce_pair()
    code = _create_auth_code(db_session, tenant, admin, challenge)

    resp = client.post(
        f"/t/{tenant.slug}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": "wrong-verifier",
            "redirect_uri": "http://localhost:9999/callback",
        },
    )
    assert resp.status_code == 400
    assert "pkce" in resp.json()["detail"].lower()


# ── Refresh Token ────────────────────────────────────────────────────────────


def _create_refresh_token(db_session, tenant, admin):
    """Create a refresh token and return the raw value."""
    raw = secrets.token_urlsafe(32)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    db_session.add(OAuthRefreshToken(
        tenant_id=tenant.id,
        user_id=admin.id,
        hashed_token=hashed,
        expires_at=datetime.now(tz=timezone.utc) + timedelta(days=30),
    ))
    db_session.commit()
    return raw


def test_token_refresh_valid_returns_new_tokens(client: TestClient, db_session, tenant_and_admin):
    tenant, admin = tenant_and_admin
    raw_refresh = _create_refresh_token(db_session, tenant, admin)

    resp = client.post(
        f"/t/{tenant.slug}/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": raw_refresh,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["refresh_token"] != raw_refresh


def test_token_refresh_rotates_token(client: TestClient, db_session, tenant_and_admin):
    """Old refresh token is rejected after use (rotation)."""
    tenant, admin = tenant_and_admin
    raw_refresh = _create_refresh_token(db_session, tenant, admin)

    client.post(
        f"/t/{tenant.slug}/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": raw_refresh},
    )

    resp = client.post(
        f"/t/{tenant.slug}/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": raw_refresh},
    )
    assert resp.status_code == 400


def test_token_refresh_revoked_token_rejected(client: TestClient, db_session, tenant_and_admin):
    tenant, admin = tenant_and_admin
    raw = secrets.token_urlsafe(32)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    db_session.add(OAuthRefreshToken(
        tenant_id=tenant.id,
        user_id=admin.id,
        hashed_token=hashed,
        expires_at=datetime.now(tz=timezone.utc) + timedelta(days=30),
        revoked_at=datetime.now(tz=timezone.utc),
    ))
    db_session.commit()

    resp = client.post(
        f"/t/{tenant.slug}/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": raw},
    )
    assert resp.status_code == 400


# ── Dynamic Client Registration (RFC 7591) ──────────────────────────────────


def test_register_returns_namespaced_client_id(client: TestClient, tenant_and_admin):
    tenant, _ = tenant_and_admin
    resp = client.post(
        f"/t/{tenant.slug}/oauth/register",
        json={
            "redirect_uris": ["http://localhost:9999/callback"],
            "client_name": "mcp-remote",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["client_id"] == f"mcp-remote-{tenant.slug}"
    assert body["client_name"] == "mcp-remote"
    assert "client_id_issued_at" in body
    assert isinstance(body["client_id_issued_at"], int)
    assert body["token_endpoint_auth_method"] == "none"
    assert body["redirect_uris"] == ["http://localhost:9999/callback"]


def test_register_defaults_client_name(client: TestClient, tenant_and_admin):
    tenant, _ = tenant_and_admin
    resp = client.post(
        f"/t/{tenant.slug}/oauth/register",
        json={"redirect_uris": []},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["client_id"] == f"mcp-client-{tenant.slug}"


# ── Protected Resource Metadata (RFC 9728) ──────────────────────────────────


def test_protected_resource_metadata(client: TestClient, tenant_and_admin):
    tenant, _ = tenant_and_admin
    resp = client.get(f"/t/{tenant.slug}/.well-known/oauth-protected-resource")
    assert resp.status_code == 200
    body = resp.json()
    assert body["resource"].endswith(f"/t/{tenant.slug}/mcp/sse")
    assert len(body["authorization_servers"]) == 1
    assert body["authorization_servers"][0].endswith(f"/t/{tenant.slug}")


# ── Legacy /mcp/sse endpoint ────────────────────────────────────────────────


def test_legacy_mcp_sse_missing_auth_returns_401(client: TestClient):
    resp = client.get("/mcp/sse")
    assert resp.status_code == 401


def test_legacy_mcp_sse_invalid_api_key_returns_401(client: TestClient):
    from tests.conftest import TestSessionLocal
    with patch("app.api.mcp_sse.get_session", new=lambda: TestSessionLocal()):
        resp = client.get("/mcp/sse", params={"api_key": "garbage"})
    assert resp.status_code == 401


def test_legacy_mcp_sse_invalid_token_returns_401(client: TestClient):
    from tests.conftest import TestSessionLocal
    with patch("app.api.mcp_sse.get_session", new=lambda: TestSessionLocal()):
        resp = client.get("/mcp/sse", params={"token": "bad-token"})
    assert resp.status_code == 401


# ── Entra role sync on token refresh ─────────────────────────────────────────


@pytest.fixture
def entra_setup(db_session):
    """Create a tenant, Entra config, and Entra-provisioned user."""
    from app.core.security import encrypt

    tenant = Tenant(name="Entra Corp", slug="entra-corp")
    db_session.add(tenant)
    db_session.flush()

    config = TenantEntraConfig(
        tenant_id=tenant.id,
        entra_tenant_id="aad-tenant-id",
        client_id="client-123",
        encrypted_client_secret=encrypt("test-secret"),
        admin_group_id="grp-admin",
        analyst_group_id="grp-analyst",
        viewer_group_id="grp-viewer",
    )
    db_session.add(config)

    user = User(
        email="entra@corp.com",
        hashed_password=None,
        role=Role.analyst,
        auth_provider=AuthProvider.entra,
        entra_oid="oid-entra-1",
        tenant_id=tenant.id,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(tenant)
    db_session.refresh(user)
    db_session.refresh(config)
    return tenant, user, config


def _create_entra_refresh(db_session, tenant, user):
    raw = secrets.token_urlsafe(32)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    db_session.add(OAuthRefreshToken(
        tenant_id=tenant.id,
        user_id=user.id,
        hashed_token=hashed,
        expires_at=datetime.now(tz=timezone.utc) + timedelta(days=30),
    ))
    db_session.commit()
    return raw


def test_refresh_entra_role_promotion(client: TestClient, db_session, entra_setup):
    """Entra user promoted from analyst to admin via group change."""
    tenant, user, _ = entra_setup
    assert user.role == Role.analyst
    raw_refresh = _create_entra_refresh(db_session, tenant, user)

    with patch(
        "app.api.oauth.entra_service.get_user_group_ids_by_oid",
        new=AsyncMock(return_value=["grp-admin", "grp-analyst"]),
    ):
        resp = client.post(
            f"/t/{tenant.slug}/oauth/token",
            data={"grant_type": "refresh_token", "refresh_token": raw_refresh},
        )

    assert resp.status_code == 200
    db_session.refresh(user)
    assert user.role == Role.admin


def test_refresh_entra_role_removal_revokes_token(client: TestClient, db_session, entra_setup):
    """Entra user removed from all groups gets 403 and token revoked."""
    tenant, user, _ = entra_setup
    raw_refresh = _create_entra_refresh(db_session, tenant, user)

    with patch(
        "app.api.oauth.entra_service.get_user_group_ids_by_oid",
        new=AsyncMock(return_value=[]),
    ):
        resp = client.post(
            f"/t/{tenant.slug}/oauth/token",
            data={"grant_type": "refresh_token", "refresh_token": raw_refresh},
        )

    assert resp.status_code == 403
    assert "authorised group" in resp.json()["detail"].lower()


def test_refresh_entra_graph_failure_proceeds_with_existing_role(
    client: TestClient, db_session, entra_setup,
):
    """Graph API failure does not block refresh; existing role is kept."""
    tenant, user, _ = entra_setup
    raw_refresh = _create_entra_refresh(db_session, tenant, user)

    with patch(
        "app.api.oauth.entra_service.get_user_group_ids_by_oid",
        new=AsyncMock(side_effect=RuntimeError("Graph unreachable")),
    ):
        resp = client.post(
            f"/t/{tenant.slug}/oauth/token",
            data={"grant_type": "refresh_token", "refresh_token": raw_refresh},
        )

    assert resp.status_code == 200
    db_session.refresh(user)
    assert user.role == Role.analyst


def test_refresh_entra_missing_config_revokes_token(client: TestClient, db_session, entra_setup):
    """If Entra config is deleted, refresh is rejected with 403."""
    tenant, user, config = entra_setup
    raw_refresh = _create_entra_refresh(db_session, tenant, user)

    db_session.delete(config)
    db_session.commit()

    resp = client.post(
        f"/t/{tenant.slug}/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": raw_refresh},
    )
    assert resp.status_code == 403
    assert "re-authenticate" in resp.json()["detail"].lower()


def test_refresh_local_user_unaffected(client: TestClient, db_session, tenant_and_admin):
    """Non-Entra users on the refresh path are not affected by Entra sync."""
    tenant, admin = tenant_and_admin
    raw_refresh = _create_refresh_token(db_session, tenant, admin)

    resp = client.post(
        f"/t/{tenant.slug}/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": raw_refresh},
    )
    assert resp.status_code == 200
    db_session.refresh(admin)
    assert admin.role == Role.admin
