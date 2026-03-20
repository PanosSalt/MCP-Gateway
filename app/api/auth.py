from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.auth import create_access_token, verify_password
from app.core.limiter import limiter
from app.database import get_db
from app.models import Tenant, User
from app.schemas import Token, UserLogin
from app.services.audit import write_audit_log

router = APIRouter()


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
def login(
    payload: UserLogin,
    request: Request,
    db: Session = Depends(get_db),
) -> Token:
    ip = request.client.host if request.client else None

    # Build the user query. When tenant_slug is provided, scope the lookup
    # to that tenant to prevent cross-tenant email ambiguity.
    user_q = db.query(User).filter(User.email == payload.email)
    if payload.tenant_slug:
        tenant = (
            db.query(Tenant).filter(Tenant.slug == payload.tenant_slug).first()
        )
        if not tenant:
            write_audit_log(db, "login.failure", ip=ip, metadata={
                "email": payload.email, "reason": "unknown_tenant",
            })
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        user_q = user_q.filter(User.tenant_id == tenant.id)
    user = user_q.first()

    if not user or not user.hashed_password:
        write_audit_log(db, "login.failure", ip=ip, metadata={"email": payload.email, "reason": "unknown_user_or_no_password"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not verify_password(payload.password, user.hashed_password):
        write_audit_log(db, "login.failure", user=user, ip=ip, metadata={"reason": "wrong_password"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        write_audit_log(db, "login.failure", user=user, ip=ip, metadata={"reason": "account_disabled"})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )
    token = create_access_token(
        user.id, user.tenant_id, user.role.value, email=user.email
    )
    write_audit_log(db, "login.success", user=user, ip=ip)
    return Token(access_token=token)
