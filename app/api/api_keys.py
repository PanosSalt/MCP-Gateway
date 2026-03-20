from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.api_keys import generate_api_key
from app.core.dependencies import get_current_user
from app.core.limiter import limiter
from app.database import get_db
from app.models import APIKey, User
from app.schemas import APIKeyCreate, APIKeyCreatedResponse, APIKeyResponse
from app.services.audit import write_audit_log

router = APIRouter()


@router.post("", response_model=APIKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def create_api_key(
    payload: APIKeyCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> APIKeyCreatedResponse:
    duplicate = (
        db.query(APIKey)
        .filter(
            APIKey.user_id == current_user.id,
            APIKey.name == payload.name,
            APIKey.revoked_at.is_(None),
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An active API key named '{payload.name}' already exists",
        )

    db.query(APIKey).filter(
        APIKey.user_id == current_user.id,
        APIKey.name == payload.name,
        APIKey.revoked_at.isnot(None),
    ).delete()
    db.flush()

    raw_key, prefix, hashed = generate_api_key()
    key = APIKey(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        name=payload.name,
        prefix=prefix,
        hashed_key=hashed,
        expires_at=payload.expires_at,
    )
    db.add(key)
    db.commit()
    db.refresh(key)

    write_audit_log(
        db,
        event="key.created",
        user=current_user,
        ip=request.client.host if request.client else None,
        metadata={"key_prefix": prefix, "key_name": payload.name},
    )

    return APIKeyCreatedResponse(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        raw_key=raw_key,
        created_at=key.created_at,
    )


@router.get("", response_model=list[APIKeyResponse])
def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[APIKey]:
    return (
        db.query(APIKey)
        .filter(APIKey.user_id == current_user.id)
        .order_by(APIKey.created_at.desc())
        .all()
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_key(
    key_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    key = (
        db.query(APIKey)
        .filter(APIKey.id == key_id, APIKey.user_id == current_user.id)
        .first()
    )
    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

    key.revoked_at = datetime.now(timezone.utc)
    db.commit()

    write_audit_log(
        db,
        event="key.revoked",
        user=current_user,
        ip=request.client.host if request.client else None,
        metadata={"key_prefix": key.prefix},
    )
