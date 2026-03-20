from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.models import AuthProvider, Role
from app.services.entra import (
    MAX_GROUP_PAGES,
    build_authorization_url,
    exchange_code_for_token,
    get_entra_profile,
    get_user_group_ids,
    jit_provision_user,
    resolve_role,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_config(**overrides):
    """Build a fake TenantEntraConfig using SimpleNamespace to avoid ORM instrumentation."""
    defaults = dict(
        id="cfg-1",
        tenant_id="t-1",
        entra_tenant_id="aad-tenant-id",
        client_id="client-123",
        encrypted_client_secret="encrypted-secret",
        admin_group_id="grp-admin",
        analyst_group_id="grp-analyst",
        viewer_group_id="grp-viewer",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# build_authorization_url
# ---------------------------------------------------------------------------

def test_build_authorization_url_contains_required_params():
    config = _make_config()
    with patch("app.services.entra.get_settings") as mock_settings:
        mock_settings.return_value = SimpleNamespace(
            entra_authority_url="https://login.microsoftonline.com",
            base_url="http://localhost:8000",
        )
        url = build_authorization_url(config, state="random-state")
    assert "aad-tenant-id" in url
    assert "client-123" in url
    assert "random-state" in url
    assert "response_type=code" in url
    assert "/oauth2/v2.0/authorize" in url


def test_build_authorization_url_encodes_params():
    config = _make_config()
    url = build_authorization_url(config, state="st ate")
    assert "st+ate" in url or "st%20ate" in url
    assert " " not in url.split("?", 1)[1]


# ---------------------------------------------------------------------------
# exchange_code_for_token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exchange_code_for_token_success():
    config = _make_config()
    mock_response = MagicMock()
    mock_response.json.return_value = {"access_token": "at-123"}
    mock_response.raise_for_status = MagicMock()

    with (
        patch("app.services.entra.decrypt", return_value="plain-secret"),
        patch("app.services.entra.httpx.AsyncClient") as MockClient,
    ):
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_http

        result = await exchange_code_for_token(config, code="auth-code")

    assert result == {"access_token": "at-123"}
    mock_http.post.assert_called_once()


@pytest.mark.asyncio
async def test_exchange_code_for_token_wraps_http_error():
    config = _make_config()
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 400
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "bad", request=MagicMock(), response=mock_response
    )

    with (
        patch("app.services.entra.decrypt", return_value="plain-secret"),
        patch("app.services.entra.httpx.AsyncClient") as MockClient,
    ):
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_http

        with pytest.raises(RuntimeError, match="Token exchange failed"):
            await exchange_code_for_token(config, code="bad-code")


# ---------------------------------------------------------------------------
# get_entra_profile
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_entra_profile_returns_dict():
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "id": "oid-1",
        "mail": "user@corp.com",
    }
    mock_response.raise_for_status = MagicMock()

    with patch("app.services.entra.httpx.AsyncClient") as MockClient:
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_http

        profile = await get_entra_profile("bearer-token")

    assert profile["id"] == "oid-1"
    assert profile["mail"] == "user@corp.com"


@pytest.mark.asyncio
async def test_get_entra_profile_wraps_http_error():
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 401
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "unauth", request=MagicMock(), response=mock_response
    )

    with patch("app.services.entra.httpx.AsyncClient") as MockClient:
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_http

        with pytest.raises(RuntimeError, match="Profile fetch failed"):
            await get_entra_profile("bad-token")


# ---------------------------------------------------------------------------
# get_user_group_ids
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_user_group_ids_paginates():
    page1 = MagicMock()
    page1.json.return_value = {
        "value": [{"id": "g1"}, {"id": "g2"}],
        "@odata.nextLink": "https://graph.microsoft.com/next-page",
    }
    page1.raise_for_status = MagicMock()

    page2 = MagicMock()
    page2.json.return_value = {
        "value": [{"id": "g3"}],
    }
    page2.raise_for_status = MagicMock()

    with patch("app.services.entra.httpx.AsyncClient") as MockClient:
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(side_effect=[page1, page2])
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_http

        ids = await get_user_group_ids("bearer-token")

    assert ids == ["g1", "g2", "g3"]
    assert mock_http.get.call_count == 2


@pytest.mark.asyncio
async def test_get_user_group_ids_respects_page_cap():
    """Ensure pagination stops at MAX_GROUP_PAGES even if nextLink keeps coming."""
    def _make_page(idx):
        resp = MagicMock()
        resp.json.return_value = {
            "value": [{"id": f"g-{idx}"}],
            "@odata.nextLink": "https://graph.microsoft.com/next",
        }
        resp.raise_for_status = MagicMock()
        return resp

    pages = [_make_page(i) for i in range(MAX_GROUP_PAGES + 5)]

    with patch("app.services.entra.httpx.AsyncClient") as MockClient:
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(side_effect=pages)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_http

        ids = await get_user_group_ids("bearer-token")

    assert mock_http.get.call_count == MAX_GROUP_PAGES
    assert len(ids) == MAX_GROUP_PAGES


# ---------------------------------------------------------------------------
# resolve_role
# ---------------------------------------------------------------------------

def test_resolve_role_admin_wins():
    config = _make_config()
    role = resolve_role(["grp-admin", "grp-viewer"], config)
    assert role == Role.admin


def test_resolve_role_analyst():
    config = _make_config()
    role = resolve_role(["grp-analyst"], config)
    assert role == Role.analyst


def test_resolve_role_viewer():
    config = _make_config()
    role = resolve_role(["grp-viewer"], config)
    assert role == Role.viewer


def test_resolve_role_none_when_no_match():
    config = _make_config()
    role = resolve_role(["grp-other"], config)
    assert role is None


def test_resolve_role_skips_unconfigured_groups():
    config = _make_config(admin_group_id=None, analyst_group_id=None)
    role = resolve_role(["grp-admin", "grp-analyst", "grp-viewer"], config)
    assert role == Role.viewer


# ---------------------------------------------------------------------------
# jit_provision_user
# ---------------------------------------------------------------------------

def test_jit_provision_creates_new_user(db_session):
    from app.models import Tenant

    tenant = Tenant(id="t-1", name="Corp", slug="corp")
    db_session.add(tenant)
    db_session.commit()

    user = jit_provision_user(
        db_session, "t-1", "oid-new", "new@corp.com", Role.analyst
    )
    assert user.email == "new@corp.com"
    assert user.role == Role.analyst
    assert user.auth_provider == AuthProvider.entra
    assert user.entra_oid == "oid-new"
    assert user.tenant_id == "t-1"
    assert user.hashed_password is None


def test_jit_provision_updates_existing_user(db_session):
    from app.models import Tenant

    tenant = Tenant(id="t-1", name="Corp", slug="corp")
    db_session.add(tenant)
    db_session.commit()

    first = jit_provision_user(
        db_session, "t-1", "oid-1", "old@corp.com", Role.viewer
    )
    updated = jit_provision_user(
        db_session, "t-1", "oid-1", "new@corp.com", Role.admin
    )
    assert first.id == updated.id
    assert updated.email == "new@corp.com"
    assert updated.role == Role.admin
