"""Tests for app.api.connections — database connection CRUD."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_access_token, hash_password
from app.core.security import decrypt
from app.models import DBConnection, DBType, Role, Tenant, User

# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tenant_and_admin(db_session):
    tenant = Tenant(name="Conn Corp", slug="conn-corp")
    db_session.add(tenant)
    db_session.flush()
    admin = User(
        email="admin@conn.com",
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
        email="viewer@conn.com",
        hashed_password=hash_password("pw"),
        role=Role.viewer,
        tenant_id=tenant.id,
    )
    db_session.add(viewer)
    db_session.commit()
    db_session.refresh(viewer)
    token = create_access_token(viewer.id, tenant.id, viewer.role.value)
    return {"Authorization": f"Bearer {token}"}


# ── POST /connections/ ────────────────────────────────────────────────────────


def test_create_connection_success(client: TestClient, tenant_and_admin, admin_header):
    resp = client.post(
        "/connections/",
        json={
            "name": "Prod DB",
            "db_type": "postgres",
            "connection_string": "postgresql://user:pass@host/db",
            "description": "Production database",
        },
        headers=admin_header,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Prod DB"
    assert body["db_type"] == "postgres"
    assert body["is_active"] is True
    assert "id" in body
    # Connection string must NOT appear in the response (it's encrypted at rest)
    assert "postgresql://" not in str(body)


def test_create_connection_stores_encrypted(client: TestClient, db_session, tenant_and_admin, admin_header):
    """The raw connection string must not be stored in plain text."""
    resp = client.post(
        "/connections/",
        json={
            "name": "Secret DB",
            "db_type": "sqlite",
            "connection_string": "/tmp/secret.db",
        },
        headers=admin_header,
    )
    conn_id = resp.json()["id"]
    row = db_session.query(DBConnection).filter(DBConnection.id == conn_id).first()
    assert row is not None
    assert row.encrypted_conn_str != "/tmp/secret.db"
    # But decryption must recover the original
    assert decrypt(row.encrypted_conn_str) == "/tmp/secret.db"


def test_create_connection_requires_admin(client: TestClient, viewer_header):
    resp = client.post(
        "/connections/",
        json={"name": "X", "db_type": "sqlite", "connection_string": "/x"},
        headers=viewer_header,
    )
    assert resp.status_code == 403


def test_create_connection_requires_auth(client: TestClient):
    resp = client.post(
        "/connections/",
        json={"name": "X", "db_type": "sqlite", "connection_string": "/x"},
    )
    assert resp.status_code in (401, 403)


# ── GET /connections/ ─────────────────────────────────────────────────────────


def test_list_connections_admin(client: TestClient, db_session, tenant_and_admin, admin_header):
    tenant, _ = tenant_and_admin
    db_session.add(DBConnection(
        name="DB1", db_type=DBType.sqlite,
        encrypted_conn_str="enc", tenant_id=tenant.id,
    ))
    db_session.add(DBConnection(
        name="DB2", db_type=DBType.postgres,
        encrypted_conn_str="enc", tenant_id=tenant.id,
    ))
    db_session.commit()

    resp = client.get("/connections/", headers=admin_header)
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert "DB1" in names
    assert "DB2" in names


def test_list_connections_viewer_allowed(client: TestClient, db_session, tenant_and_admin, viewer_header):
    """Viewers can list connections (read-only access)."""
    tenant, _ = tenant_and_admin
    db_session.add(DBConnection(
        name="ViewerVisible", db_type=DBType.sqlite,
        encrypted_conn_str="enc", tenant_id=tenant.id,
    ))
    db_session.commit()

    resp = client.get("/connections/", headers=viewer_header)
    assert resp.status_code == 200
    assert any(c["name"] == "ViewerVisible" for c in resp.json())


def test_list_connections_excludes_inactive(client: TestClient, db_session, tenant_and_admin, admin_header):
    tenant, _ = tenant_and_admin
    db_session.add(DBConnection(
        name="Active", db_type=DBType.sqlite,
        encrypted_conn_str="enc", is_active=True, tenant_id=tenant.id,
    ))
    db_session.add(DBConnection(
        name="Deleted", db_type=DBType.sqlite,
        encrypted_conn_str="enc", is_active=False, tenant_id=tenant.id,
    ))
    db_session.commit()

    resp = client.get("/connections/", headers=admin_header)
    names = [c["name"] for c in resp.json()]
    assert "Active" in names
    assert "Deleted" not in names


def test_list_connections_cross_tenant_isolation(client: TestClient, db_session, tenant_and_admin, admin_header):
    """Connections from another tenant must not appear in the list."""
    other = Tenant(name="Other", slug="other-conn")
    db_session.add(other)
    db_session.flush()
    db_session.add(DBConnection(
        name="OtherDB", db_type=DBType.postgres,
        encrypted_conn_str="enc", tenant_id=other.id,
    ))
    db_session.commit()

    resp = client.get("/connections/", headers=admin_header)
    names = [c["name"] for c in resp.json()]
    assert "OtherDB" not in names


# ── PATCH /connections/{id} ───────────────────────────────────────────────────


def test_update_connection_partial(client: TestClient, db_session, tenant_and_admin, admin_header):
    """Partial update (name only) succeeds and leaves other fields unchanged."""
    tenant, _ = tenant_and_admin
    conn = DBConnection(
        name="Original", db_type=DBType.sqlite,
        encrypted_conn_str="enc", description="old desc", tenant_id=tenant.id,
    )
    db_session.add(conn)
    db_session.commit()
    db_session.refresh(conn)

    resp = client.patch(
        f"/connections/{conn.id}",
        json={"name": "Renamed"},
        headers=admin_header,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["db_type"] == "sqlite"
    assert body["description"] == "old desc"


def test_update_connection_reencrypts_conn_str(client: TestClient, db_session, tenant_and_admin, admin_header):
    """Updating connection_string re-encrypts the value."""
    tenant, _ = tenant_and_admin
    conn = DBConnection(
        name="EncTest", db_type=DBType.postgres,
        encrypted_conn_str="enc", tenant_id=tenant.id,
    )
    db_session.add(conn)
    db_session.commit()
    db_session.refresh(conn)

    resp = client.patch(
        f"/connections/{conn.id}",
        json={"connection_string": "postgresql://new:secret@host/db"},
        headers=admin_header,
    )
    assert resp.status_code == 200
    db_session.refresh(conn)
    assert conn.encrypted_conn_str != "postgresql://new:secret@host/db"
    assert decrypt(conn.encrypted_conn_str) == "postgresql://new:secret@host/db"


def test_update_connection_requires_admin(client: TestClient, db_session, tenant_and_admin, viewer_header):
    tenant, _ = tenant_and_admin
    conn = DBConnection(
        name="NoEdit", db_type=DBType.sqlite,
        encrypted_conn_str="enc", tenant_id=tenant.id,
    )
    db_session.add(conn)
    db_session.commit()
    db_session.refresh(conn)

    resp = client.patch(
        f"/connections/{conn.id}",
        json={"name": "Hacked"},
        headers=viewer_header,
    )
    assert resp.status_code == 403


def test_update_connection_not_found(client: TestClient, admin_header):
    resp = client.patch(
        "/connections/nonexistent-id",
        json={"name": "Ghost"},
        headers=admin_header,
    )
    assert resp.status_code == 404


def test_update_connection_cross_tenant_blocked(client: TestClient, db_session, tenant_and_admin, admin_header):
    """An admin cannot update another tenant's connection."""
    other = Tenant(name="OtherPatch", slug="other-patch")
    db_session.add(other)
    db_session.flush()
    other_conn = DBConnection(
        name="OtherConn", db_type=DBType.postgres,
        encrypted_conn_str="enc", tenant_id=other.id,
    )
    db_session.add(other_conn)
    db_session.commit()
    db_session.refresh(other_conn)

    resp = client.patch(
        f"/connections/{other_conn.id}",
        json={"name": "Stolen"},
        headers=admin_header,
    )
    assert resp.status_code == 404


# ── DELETE /connections/{id} ──────────────────────────────────────────────────


def test_delete_connection_soft_deletes(client: TestClient, db_session, tenant_and_admin, admin_header):
    tenant, _ = tenant_and_admin
    conn = DBConnection(
        name="ToDelete", db_type=DBType.sqlite,
        encrypted_conn_str="enc", tenant_id=tenant.id,
    )
    db_session.add(conn)
    db_session.commit()
    db_session.refresh(conn)

    resp = client.delete(f"/connections/{conn.id}", headers=admin_header)
    assert resp.status_code == 200
    assert "removed" in resp.json()["detail"].lower()

    db_session.refresh(conn)
    assert conn.is_active is False


def test_delete_connection_not_found(client: TestClient, admin_header):
    resp = client.delete("/connections/nonexistent-id", headers=admin_header)
    assert resp.status_code == 404


def test_delete_connection_cross_tenant_blocked(client: TestClient, db_session, tenant_and_admin, admin_header):
    """An admin cannot delete another tenant's connection."""
    other = Tenant(name="Other2", slug="other-del")
    db_session.add(other)
    db_session.flush()
    other_conn = DBConnection(
        name="OtherConn", db_type=DBType.postgres,
        encrypted_conn_str="enc", tenant_id=other.id,
    )
    db_session.add(other_conn)
    db_session.commit()
    db_session.refresh(other_conn)

    resp = client.delete(f"/connections/{other_conn.id}", headers=admin_header)
    assert resp.status_code == 404


def test_delete_connection_requires_admin(client: TestClient, db_session, tenant_and_admin, viewer_header):
    tenant, _ = tenant_and_admin
    conn = DBConnection(
        name="Protected", db_type=DBType.sqlite,
        encrypted_conn_str="enc", tenant_id=tenant.id,
    )
    db_session.add(conn)
    db_session.commit()
    db_session.refresh(conn)

    resp = client.delete(f"/connections/{conn.id}", headers=viewer_header)
    assert resp.status_code == 403
