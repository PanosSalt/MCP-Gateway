from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.constants import MAX_AUDIT_PAGE_SIZE
from app.core.dependencies import require_admin
from app.core.limiter import limiter
from app.database import get_db
from app.models import AuditLog, User
from app.schemas import AuditLogEntry

router = APIRouter()


def _escape_like(s: str) -> str:
    """Escape LIKE metacharacters so user-supplied prefixes match literally."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/", response_model=list[AuditLogEntry])
@limiter.limit("60/minute")
def list_audit_logs(
    request: Request,
    skip: int = 0,
    limit: int = 50,
    event_prefix: str | None = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AuditLog]:
    limit = min(limit, MAX_AUDIT_PAGE_SIZE)
    q = db.query(AuditLog, User.email.label("user_email")).outerjoin(
        User, AuditLog.user_id == User.id
    ).filter(AuditLog.tenant_id == current_user.tenant_id)
    if event_prefix:
        prefixes = [p.strip() for p in event_prefix.split(",") if p.strip()]
        if prefixes:
            q = q.filter(or_(*(
                AuditLog.event.like(_escape_like(p) + "%", escape="\\") for p in prefixes
            )))
    rows = q.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit).all()
    results = []
    for log, email in rows:
        log.user_email = email  # type: ignore[attr-defined]
        results.append(log)
    return results
