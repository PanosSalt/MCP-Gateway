from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import AuditLog, User

logger = logging.getLogger(__name__)


def backfill_audit_emails(db: Session, batch_size: int = 1000) -> int:
    """One-time backfill: add user_email to metadata for existing entries.

    Targets rows where user_id is set but metadata lacks user_email.
    Safe to call repeatedly (idempotent).  Returns the count of updated rows.
    Processes in batches to avoid loading the entire table into memory.
    """
    updated = 0
    offset = 0
    while True:
        rows = (
            db.query(AuditLog, User.email)
            .join(User, AuditLog.user_id == User.id)
            .filter(AuditLog.user_id.isnot(None))
            .offset(offset)
            .limit(batch_size)
            .all()
        )
        if not rows:
            break
        batch_updated = 0
        for log, email in rows:
            if not email:
                continue
            meta = dict(log.metadata_) if log.metadata_ else {}
            if "user_email" in meta:
                continue
            meta["user_email"] = email
            log.metadata_ = meta
            batch_updated += 1
        if batch_updated:
            db.commit()
        updated += batch_updated
        offset += batch_size
    if updated:
        logger.info("Backfilled user_email into %d audit log entries", updated)
    return updated


def write_audit_log(
    db: Session,
    event: str,
    user: User | None = None,
    ip: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Write an audit log entry. Never include raw secrets in metadata."""
    try:
        merged = dict(metadata) if metadata else {}
        if user and user.email and "user_email" not in merged:
            merged["user_email"] = user.email
        entry = AuditLog(
            tenant_id=user.tenant_id if user else None,
            user_id=user.id if user else None,
            event=event,
            ip_address=ip,
            metadata_=merged or None,
        )
        db.add(entry)
        db.commit()
    except Exception:
        logger.exception("Failed to write audit log for event=%s", event)
        db.rollback()
