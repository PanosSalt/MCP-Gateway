from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.constants import MAX_LIST_PAGE_SIZE
from app.core.auth import hash_password
from app.core.dependencies import get_current_user, require_admin
from app.core.limiter import limiter
from app.database import get_db
from app.models import AuditLog, OAuthAuthorizationCode, OAuthRefreshToken, Role, Tenant, User
from app.schemas import TenantCreate, TenantOut, UserCreate, UserOut, UserRoleUpdate
from app.services.audit import write_audit_log

router = APIRouter()


@router.post(
    "/", response_model=TenantOut, summary="Register a new tenant (public)"
)
@limiter.limit("5/minute")
def create_tenant(
    payload: TenantCreate, request: Request, db: Session = Depends(get_db)
) -> Tenant:
    if (
        db.query(Tenant)
        .filter(Tenant.slug == payload.slug)
        .first()
    ):
        raise HTTPException(
            status_code=400, detail="Slug already taken"
        )
    tenant = Tenant(name=payload.name, slug=payload.slug)
    db.add(tenant)
    db.flush()
    admin = User(
        email=payload.admin_email,
        hashed_password=hash_password(payload.admin_password),
        role=Role.admin,
        tenant_id=tenant.id,
    )
    db.add(admin)
    db.commit()
    db.refresh(tenant)
    write_audit_log(db, "tenant.created", user=admin, metadata={
        "tenant_id": tenant.id,
        "slug": tenant.slug,
    })
    return tenant


@router.get("/me", response_model=TenantOut)
def get_my_tenant(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.get("/users", response_model=list[UserOut])
def list_users(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[User]:
    return (
        db.query(User)
        .filter(User.tenant_id == current_user.tenant_id)
        .offset(skip)
        .limit(min(limit, MAX_LIST_PAGE_SIZE))
        .all()
    )


@router.post("/users", response_model=UserOut)
def create_user(
    payload: UserCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    if (
        db.query(User)
        .filter(
            User.email == payload.email,
            User.tenant_id == current_user.tenant_id,
        )
        .first()
    ):
        raise HTTPException(
            status_code=400,
            detail="Email already registered in this tenant",
        )
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        tenant_id=current_user.tenant_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    if user_id == current_user.id:
        raise HTTPException(
            status_code=400, detail="Cannot delete your own account"
        )
    user = (
        db.query(User)
        .filter(
            User.id == user_id,
            User.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        db.query(OAuthRefreshToken).filter(OAuthRefreshToken.user_id == user_id).delete()
        db.query(OAuthAuthorizationCode).filter(OAuthAuthorizationCode.user_id == user_id).delete()
        db.query(AuditLog).filter(AuditLog.user_id == user_id).update({"user_id": None})
        db.delete(user)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete user")
    write_audit_log(db, "user.deleted", user=current_user, metadata={
        "target_user_id": user_id,
    })


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user_role(
    user_id: str,
    payload: UserRoleUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    if user_id == current_user.id:
        raise HTTPException(
            status_code=400, detail="Cannot change your own role"
        )
    user = (
        db.query(User)
        .filter(
            User.id == user_id,
            User.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.role = payload.role
    db.commit()
    db.refresh(user)
    write_audit_log(db, "user.role_updated", user=current_user, metadata={
        "target_user_id": user_id,
        "new_role": payload.role.value,
    })
    return user
