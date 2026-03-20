from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.constants import MAX_LIST_PAGE_SIZE
from app.core.dependencies import require_admin, require_viewer
from app.core.rbac import ROLE_RANK
from app.core.security import encrypt
from app.database import get_db
from app.models import DBConnection, Role, User
from app.schemas import ConnectionCreate, ConnectionOut, ConnectionUpdate
from app.services.audit import write_audit_log

router = APIRouter()


@router.post("/", response_model=ConnectionOut)
def create_connection(
    payload: ConnectionCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DBConnection:
    conn = DBConnection(
        name=payload.name,
        db_type=payload.db_type,
        encrypted_conn_str=encrypt(payload.connection_string),
        description=payload.description,
        min_role=payload.min_role,
        tenant_id=current_user.tenant_id,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    write_audit_log(db, "connection.created", user=current_user, metadata={
        "connection_id": conn.id,
        "db_type": conn.db_type.value,
        "name": conn.name,
    })
    return conn


@router.get("/", response_model=list[ConnectionOut])
def list_connections(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(require_viewer),
    db: Session = Depends(get_db),
) -> list[DBConnection]:
    user_rank = ROLE_RANK[current_user.role]
    accessible_roles = [r for r in Role if ROLE_RANK[r] <= user_rank]
    conns = (
        db.query(DBConnection)
        .filter(
            DBConnection.tenant_id == current_user.tenant_id,
            DBConnection.is_active.is_(True),
            DBConnection.min_role.in_(accessible_roles),
        )
        .offset(skip)
        .limit(min(limit, MAX_LIST_PAGE_SIZE))
        .all()
    )
    return conns


@router.patch("/{connection_id}", response_model=ConnectionOut)
def update_connection(
    connection_id: str,
    payload: ConnectionUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DBConnection:
    conn = (
        db.query(DBConnection)
        .filter(
            DBConnection.id == connection_id,
            DBConnection.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if not conn:
        raise HTTPException(
            status_code=404, detail="Connection not found"
        )
    updates = payload.model_dump(exclude_none=True)
    if "connection_string" in updates:
        updates["encrypted_conn_str"] = encrypt(updates.pop("connection_string"))
    for attr, value in updates.items():
        setattr(conn, attr, value)
    db.commit()
    db.refresh(conn)
    write_audit_log(db, "connection.updated", user=current_user, metadata={
        "connection_id": connection_id,
        "fields_changed": list(payload.model_dump(exclude_none=True).keys()),
    })
    return conn


@router.delete("/{connection_id}")
def delete_connection(
    connection_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    conn = (
        db.query(DBConnection)
        .filter(
            DBConnection.id == connection_id,
            DBConnection.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if not conn:
        raise HTTPException(
            status_code=404, detail="Connection not found"
        )
    conn.is_active = False
    db.commit()
    write_audit_log(db, "connection.deleted", user=current_user, metadata={
        "connection_id": connection_id,
    })
    return {"detail": "Connection removed"}
