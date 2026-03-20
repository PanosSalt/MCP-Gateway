"""Tests for app.api.auth_entra — Entra ID SSO routes."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_access_token, hash_password
from app.models import OAuthState, Role, Tenant, User


@pytest.fixture
def admin_setup(db_session):
    tenant = Tenant(name="SSO Corp", slug="sso-corp")
    db_session.add(tenant)
    db_session.flush()
    admin = User(
        email="admin@sso.com",
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
def admin_auth(admin_setup):
    _, admin = admin_setup
    token = create_access_token(admin.id, admin.tenant_id, admin.role.value)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def entra_config_payload():
    return {
        "entra_tenant_id": "aad-tenant-123",
        "client_id": "client-abc",
        "client_secret": "super-secret",
        "admin_group_id": "grp-admin",
        "analyst_group_id": "grp-analyst",
        "viewer_group_id": "grp-viewer",
    }


# ── Config CRUD ──────────────────────────────────────────────────────


def test_create_entra_config(client: TestClient, admin_auth, entra_config_payload):
    resp = client.post(
        "/auth/entra/config",
        json=entra_config_payload,
        headers=admin_auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["entra_tenant_id"] == "aad-tenant-123"
    assert body["client_id"] == "client-abc"
    assert "encrypted_client_secret" not in body


def test_update_entra_config(
    client: TestClient, admin_auth, entra_config_payload
):
    client.post(
        "/auth/entra/config", json=entra_config_payload, headers=admin_auth
    )
    updated = entra_config_payload.copy()
    updated["client_id"] = "new-client-id"
    resp = client.post(
        "/auth/entra/config", json=updated, headers=admin_auth
    )
    assert resp.status_code == 200
    assert resp.json()["client_id"] == "new-client-id"


def test_get_entra_config(client: TestClient, admin_auth, entra_config_payload):
    client.post(
        "/auth/entra/config", json=entra_config_payload, headers=admin_auth
    )
    resp = client.get("/auth/entra/config", headers=admin_auth)
    assert resp.status_code == 200
    assert resp.json()["admin_group_id"] == "grp-admin"


def test_get_entra_config_not_found(client: TestClient, admin_auth):
    resp = client.get("/auth/entra/config", headers=admin_auth)
    assert resp.status_code == 404


def test_delete_entra_config(
    client: TestClient, admin_auth, entra_config_payload
):
    client.post(
        "/auth/entra/config", json=entra_config_payload, headers=admin_auth
    )
    resp = client.delete("/auth/entra/config", headers=admin_auth)
    assert resp.status_code == 200
    assert "removed" in resp.json()["detail"].lower()

    resp = client.get("/auth/entra/config", headers=admin_auth)
    assert resp.status_code == 404


def test_delete_entra_config_not_found(client: TestClient, admin_auth):
    resp = client.delete("/auth/entra/config", headers=admin_auth)
    assert resp.status_code == 404


def test_entra_config_requires_admin(client: TestClient, db_session, admin_setup):
    tenant, _ = admin_setup
    viewer = User(
        email="viewer@sso.com",
        hashed_password=hash_password("pw"),
        role=Role.viewer,
        tenant_id=tenant.id,
    )
    db_session.add(viewer)
    db_session.commit()
    db_session.refresh(viewer)
    token = create_access_token(viewer.id, tenant.id, viewer.role.value)
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/auth/entra/config", headers=headers)
    assert resp.status_code == 403


# ── Login flow ───────────────────────────────────────────────────────


def test_entra_login_returns_authorization_url(
    client: TestClient, db_session, admin_setup, entra_config_payload, admin_auth
):
    client.post(
        "/auth/entra/config", json=entra_config_payload, headers=admin_auth
    )
    # The endpoint redirects (302) to the Entra authorization URL.
    # Use follow_redirects=False so we can inspect the Location header directly.
    resp = client.get(
        "/auth/entra/login",
        params={"tenant_slug": "sso-corp"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers.get("location", "")
    # The redirect URL always carries the client_id from the stored config.
    assert "client_id=client-abc" in location
    assert location.startswith("http")


def test_entra_login_unknown_tenant(client: TestClient):
    resp = client.get(
        "/auth/entra/login", params={"tenant_slug": "nope"}
    )
    assert resp.status_code == 404


def test_entra_login_no_config(client: TestClient, admin_setup):
    resp = client.get(
        "/auth/entra/login", params={"tenant_slug": "sso-corp"}
    )
    assert resp.status_code == 400
    assert "not configured" in resp.json()["detail"]


# ── Callback ─────────────────────────────────────────────────────────


def test_entra_callback_invalid_state(client: TestClient):
    resp = client.get(
        "/auth/entra/callback",
        params={"code": "authcode", "state": "bogus"},
    )
    assert resp.status_code == 400
    assert "Invalid or expired" in resp.json()["detail"]


def test_entra_callback_success(
    client: TestClient, db_session, admin_setup, entra_config_payload, admin_auth
):
    client.post(
        "/auth/entra/config", json=entra_config_payload, headers=admin_auth
    )
    login_resp = client.get(
        "/auth/entra/login", params={"tenant_slug": "sso-corp"}, follow_redirects=False
    )
    assert login_resp.status_code == 302
    url = login_resp.headers["location"]
    state = url.split("state=")[-1].split("&")[0]

    with (
        patch(
            "app.services.entra.exchange_code_for_token",
            new_callable=AsyncMock,
            return_value={"access_token": "ms-token-123"},
        ),
        patch(
            "app.services.entra.get_entra_profile",
            new_callable=AsyncMock,
            return_value={
                "id": "oid-abc",
                "mail": "sso-user@test.com",
            },
        ),
        patch(
            "app.services.entra.get_user_group_ids",
            new_callable=AsyncMock,
            return_value=["grp-analyst"],
        ),
    ):
        resp = client.get(
            "/auth/entra/callback",
            params={"code": "authcode", "state": state},
            follow_redirects=False,
        )
    assert resp.status_code == 200
    assert "sso-user@test.com" in resp.text
    assert "analyst" in resp.text


def test_entra_callback_no_role_match(
    client: TestClient, db_session, admin_setup, entra_config_payload, admin_auth
):
    client.post(
        "/auth/entra/config", json=entra_config_payload, headers=admin_auth
    )
    login_resp = client.get(
        "/auth/entra/login", params={"tenant_slug": "sso-corp"}, follow_redirects=False
    )
    assert login_resp.status_code == 302
    url = login_resp.headers["location"]
    state = url.split("state=")[-1].split("&")[0]

    with (
        patch(
            "app.services.entra.exchange_code_for_token",
            new_callable=AsyncMock,
            return_value={"access_token": "ms-token-123"},
        ),
        patch(
            "app.services.entra.get_entra_profile",
            new_callable=AsyncMock,
            return_value={"id": "oid-xyz", "mail": "nobody@test.com"},
        ),
        patch(
            "app.services.entra.get_user_group_ids",
            new_callable=AsyncMock,
            return_value=["grp-unrelated"],
        ),
    ):
        resp = client.get(
            "/auth/entra/callback",
            params={"code": "authcode", "state": state},
        )
    assert resp.status_code == 403


def test_entra_callback_missing_profile_id(
    client: TestClient, db_session, admin_setup, entra_config_payload, admin_auth
):
    client.post(
        "/auth/entra/config", json=entra_config_payload, headers=admin_auth
    )
    login_resp = client.get(
        "/auth/entra/login", params={"tenant_slug": "sso-corp"}, follow_redirects=False
    )
    assert login_resp.status_code == 302
    url = login_resp.headers["location"]
    state = url.split("state=")[-1].split("&")[0]

    with (
        patch(
            "app.services.entra.exchange_code_for_token",
            new_callable=AsyncMock,
            return_value={"access_token": "ms-token"},
        ),
        patch(
            "app.services.entra.get_entra_profile",
            new_callable=AsyncMock,
            return_value={"mail": "no-id@test.com"},
        ),
        patch(
            "app.services.entra.get_user_group_ids",
            new_callable=AsyncMock,
            return_value=["grp-admin"],
        ),
    ):
        resp = client.get(
            "/auth/entra/callback",
            params={"code": "authcode", "state": state},
        )
    assert resp.status_code == 502
    assert "missing user identifier" in resp.json()["detail"]


def test_entra_callback_xss_safe(
    client: TestClient, db_session, admin_setup, entra_config_payload, admin_auth
):
    """Ensure email from Entra is HTML-escaped in the response."""
    client.post(
        "/auth/entra/config", json=entra_config_payload, headers=admin_auth
    )
    login_resp = client.get(
        "/auth/entra/login", params={"tenant_slug": "sso-corp"}, follow_redirects=False
    )
    assert login_resp.status_code == 302
    url = login_resp.headers["location"]
    state = url.split("state=")[-1].split("&")[0]

    with (
        patch(
            "app.services.entra.exchange_code_for_token",
            new_callable=AsyncMock,
            return_value={"access_token": "tok"},
        ),
        patch(
            "app.services.entra.get_entra_profile",
            new_callable=AsyncMock,
            return_value={
                "id": "oid-xss",
                "mail": "<script>alert(1)</script>@evil.com",
            },
        ),
        patch(
            "app.services.entra.get_user_group_ids",
            new_callable=AsyncMock,
            return_value=["grp-viewer"],
        ),
    ):
        resp = client.get(
            "/auth/entra/callback",
            params={"code": "code", "state": state},
        )
    assert resp.status_code == 200
    assert "<script>alert(1)</script>" not in resp.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in resp.text


# ── OAuthState persistence tests ─────────────────────────────────────


def test_entra_login_creates_oauth_state(
    client: TestClient, db_session, admin_setup, entra_config_payload, admin_auth
):
    """GET /auth/entra/login should persist an OAuthState row in the DB."""
    client.post("/auth/entra/config", json=entra_config_payload, headers=admin_auth)

    before = db_session.query(OAuthState).count()
    resp = client.get("/auth/entra/login", params={"tenant_slug": "sso-corp"}, follow_redirects=False)
    assert resp.status_code == 302
    after = db_session.query(OAuthState).count()
    assert after == before + 1


def test_entra_callback_with_expired_state_returns_400(
    client: TestClient, db_session, admin_setup, entra_config_payload, admin_auth
):
    """Callback with an expired state token should return 400."""
    client.post("/auth/entra/config", json=entra_config_payload, headers=admin_auth)

    expired_state = OAuthState(
        state="expiredtoken123",
        tenant_slug="sso-corp",
        expires_at=datetime.now(tz=timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(expired_state)
    db_session.commit()

    resp = client.get(
        "/auth/entra/callback",
        params={"code": "authcode", "state": "expiredtoken123"},
    )
    assert resp.status_code == 400
    assert "Invalid or expired" in resp.json()["detail"]


def test_entra_callback_deletes_state_after_use(
    client: TestClient, db_session, admin_setup, entra_config_payload, admin_auth
):
    """After a successful callback, the OAuthState row should be deleted (one-time use)."""
    client.post("/auth/entra/config", json=entra_config_payload, headers=admin_auth)

    login_resp = client.get("/auth/entra/login", params={"tenant_slug": "sso-corp"}, follow_redirects=False)
    assert login_resp.status_code == 302
    url = login_resp.headers["location"]
    state = url.split("state=")[-1].split("&")[0]

    with (
        patch(
            "app.services.entra.exchange_code_for_token",
            new_callable=AsyncMock,
            return_value={"access_token": "ms-token"},
        ),
        patch(
            "app.services.entra.get_entra_profile",
            new_callable=AsyncMock,
            return_value={"id": "oid-del", "mail": "del@test.com"},
        ),
        patch(
            "app.services.entra.get_user_group_ids",
            new_callable=AsyncMock,
            return_value=["grp-admin"],
        ),
    ):
        resp = client.get(
            "/auth/entra/callback",
            params={"code": "authcode", "state": state},
        )
    assert resp.status_code == 200

    remaining = db_session.query(OAuthState).filter(OAuthState.state == state).first()
    assert remaining is None


def test_entra_callback_state_cannot_be_reused(
    client: TestClient, db_session, admin_setup, entra_config_payload, admin_auth
):
    """The same state token cannot be used twice."""
    client.post("/auth/entra/config", json=entra_config_payload, headers=admin_auth)

    login_resp = client.get("/auth/entra/login", params={"tenant_slug": "sso-corp"}, follow_redirects=False)
    assert login_resp.status_code == 302
    url = login_resp.headers["location"]
    state = url.split("state=")[-1].split("&")[0]

    with (
        patch(
            "app.services.entra.exchange_code_for_token",
            new_callable=AsyncMock,
            return_value={"access_token": "ms-token"},
        ),
        patch(
            "app.services.entra.get_entra_profile",
            new_callable=AsyncMock,
            return_value={"id": "oid-reuse", "mail": "reuse@test.com"},
        ),
        patch(
            "app.services.entra.get_user_group_ids",
            new_callable=AsyncMock,
            return_value=["grp-viewer"],
        ),
    ):
        first = client.get(
            "/auth/entra/callback",
            params={"code": "code1", "state": state},
        )
        second = client.get(
            "/auth/entra/callback",
            params={"code": "code2", "state": state},
        )
    assert first.status_code == 200
    assert second.status_code == 400
