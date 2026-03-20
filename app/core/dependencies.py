from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.auth import decode_token
from app.database import get_db
from app.models import APIKey, Role, User


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return _user_from_jwt(auth_header[7:], db)
    api_key = request.query_params.get("api_key")
    if api_key:
        return _user_from_api_key(api_key, db)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )


def _user_from_jwt(token: str, db: Session) -> User:
    token_data = decode_token(token)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    user = db.query(User).filter(User.id == token_data.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


def _user_from_api_key(raw_key: str, db: Session) -> User:
    from app.core.api_keys import hash_api_key

    now = datetime.now(timezone.utc)
    hashed = hash_api_key(raw_key)
    key = (
        db.query(APIKey)
        .filter(
            APIKey.hashed_key == hashed,
            APIKey.revoked_at.is_(None),
            or_(APIKey.expires_at.is_(None), APIKey.expires_at > now),
        )
        .first()
    )
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key",
        )
    key.last_used_at = now
    db.commit()

    user = db.query(User).filter(User.id == key.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


def require_role(*roles: Role):
    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role: {[r.value for r in roles]}",
            )
        return user

    return _check


require_admin   = require_role(Role.admin)
require_analyst = require_role(Role.admin, Role.analyst)
require_viewer  = require_role(Role.admin, Role.analyst, Role.viewer)
