from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.constants import MAX_AUDIT_PAGE_SIZE
from app.core.dependencies import require_admin, require_analyst
from app.core.limiter import limiter
from app.core.rbac import has_min_role
from app.core.security import decrypt
from app.database import get_db
from app.models import AuditLog, DBConnection, User
from app.schemas import QueryHistoryEntry, QueryRequest, QueryResponse
from app.services import llm, mcp_client
from app.services.audit import write_audit_log

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/", response_model=QueryResponse)
@limiter.limit("30/minute")
async def natural_language_query(
    payload: QueryRequest,
    request: Request,
    current_user: User = Depends(require_analyst),
    db: Session = Depends(get_db),
) -> QueryResponse:
    ip = request.client.host if request.client else None

    conn = (
        db.query(DBConnection)
        .filter(
            DBConnection.id == payload.connection_id,
            DBConnection.tenant_id == current_user.tenant_id,
            DBConnection.is_active.is_(True),
        )
        .first()
    )
    if not conn:
        raise HTTPException(
            status_code=404, detail="Connection not found"
        )

    if not has_min_role(current_user.role, conn.min_role):
        raise HTTPException(
            status_code=403, detail="Insufficient role for this connection"
        )

    connection_string = decrypt(conn.encrypted_conn_str)

    try:
        schema = await mcp_client.get_schema(
            conn.db_type, connection_string
        )
    except Exception:
        logger.error("Schema retrieval failed for connection %s", conn.id, exc_info=False)
        write_audit_log(db, "query.failure", user=current_user, ip=ip, metadata={
            "connection_id": payload.connection_id,
            "question": payload.question[:200],
            "error": "schema_retrieval_failed",
        })
        raise HTTPException(
            status_code=500,
            detail="Failed to connect to database",
        ) from None

    try:
        sql = await llm.generate_sql(
            schema, payload.question, conn.db_type.value
        )
    except ValueError as exc:
        write_audit_log(db, "query.failure", user=current_user, ip=ip, metadata={
            "connection_id": payload.connection_id,
            "question": payload.question[:200],
            "error": str(exc),
        })
        raise HTTPException(
            status_code=400, detail=str(exc)
        ) from None
    except RuntimeError:
        logger.error("LLM SQL generation failed", exc_info=False)
        write_audit_log(db, "query.failure", user=current_user, ip=ip, metadata={
            "connection_id": payload.connection_id,
            "question": payload.question[:200],
            "error": "llm_unavailable",
        })
        raise HTTPException(
            status_code=502, detail="AI service unavailable"
        ) from None

    if sql == "INVALID_QUERY":
        write_audit_log(db, "query.failure", user=current_user, ip=ip, metadata={
            "connection_id": payload.connection_id,
            "question": payload.question[:200],
            "error": "invalid_query",
        })
        raise HTTPException(
            status_code=400,
            detail="Could not generate a valid query for this question.",
        )

    try:
        results = await mcp_client.run_query(
            conn.db_type, connection_string, sql
        )
    except Exception:
        logger.error("Query execution failed for connection %s", conn.id, exc_info=False)
        write_audit_log(db, "query.failure", user=current_user, ip=ip, metadata={
            "connection_id": payload.connection_id,
            "question": payload.question[:200],
            "sql_generated": sql,
            "error": "query_execution_failed",
        })
        raise HTTPException(
            status_code=500, detail="Query execution failed"
        ) from None

    try:
        summary = await llm.summarize_results(
            payload.question, sql, results
        )
    except RuntimeError:
        logger.error("LLM summarization failed", exc_info=False)
        summary = "Could not generate summary."

    write_audit_log(db, "query.success", user=current_user, ip=ip, metadata={
        "connection_id": payload.connection_id,
        "question": payload.question[:200],
        "sql_generated": sql,
    })

    return QueryResponse(
        question=payload.question,
        sql_generated=sql,
        result=results,
        summary=summary,
    )


@router.get("/history", response_model=list[QueryHistoryEntry])
@limiter.limit("60/minute")
def query_history(
    request: Request,
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AuditLog]:
    limit = min(limit, MAX_AUDIT_PAGE_SIZE)
    return (
        db.query(AuditLog)
        .filter(
            AuditLog.tenant_id == current_user.tenant_id,
            AuditLog.event.in_(["query.success", "query.failure"]),
        )
        .order_by(AuditLog.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
