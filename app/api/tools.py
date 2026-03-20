from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_admin
from app.core.rbac import has_min_role
from app.database import get_db
from app.models import ToolRoleOverride, User
from app.schemas import ToolInfo, ToolRoleUpdate
from app.tools import ToolContext, get_all_tool_defaults, load_role_overrides

router = APIRouter()


@router.get("/", response_model=list[ToolInfo])
def list_tools(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ToolInfo]:
    ctx = ToolContext(user=current_user, db=db)
    defaults = get_all_tool_defaults(ctx)
    overrides = load_role_overrides(db, current_user.tenant_id)

    result: list[ToolInfo] = []
    for td in defaults:
        effective = overrides.get(td.name, td.default_min_role)
        result.append(ToolInfo(
            tool_name=td.name,
            tool_type=td.tool_type,
            description=td.description,
            connection_id=td.connection_id,
            connection_name=td.connection_name,
            default_min_role=td.default_min_role,
            effective_min_role=effective,
            accessible=has_min_role(current_user.role, effective),
        ))
    return result


@router.patch("/{tool_name:path}")
def update_tool_role(
    tool_name: str,
    payload: ToolRoleUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    ctx = ToolContext(user=current_user, db=db)
    known_names = {td.name for td in get_all_tool_defaults(ctx)}
    if tool_name not in known_names:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown tool: {tool_name}",
        )

    existing = (
        db.query(ToolRoleOverride)
        .filter_by(tenant_id=current_user.tenant_id, tool_name=tool_name)
        .first()
    )

    if payload.min_role is None:
        if existing:
            db.delete(existing)
            db.commit()
        return {"tool_name": tool_name, "min_role": None, "reset": True}

    if existing:
        existing.min_role = payload.min_role
    else:
        existing = ToolRoleOverride(
            tenant_id=current_user.tenant_id,
            tool_name=tool_name,
            min_role=payload.min_role,
        )
        db.add(existing)
    db.commit()
    return {"tool_name": tool_name, "min_role": payload.min_role.value, "reset": False}
