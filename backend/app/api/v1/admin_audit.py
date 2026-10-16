"""Audit-log review (read-only, permission-gated)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.api import deps, schemas
from app.models.auth import AuditLog

router = APIRouter(prefix="/admin/audit-log", tags=["admin-audit"])


@router.get("", dependencies=[Depends(deps.require_permission("audit.view"))])
def audit_log(
    db: DbSession = Depends(deps.get_db),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    total = db.execute(select(func.count(AuditLog.id))).scalar() or 0
    rows = (
        db.execute(
            select(AuditLog).order_by(AuditLog.id.desc()).limit(limit).offset(offset)
        )
        .scalars()
        .all()
    )
    return {
        "total": total,
        "items": [
            schemas.AuditOut(
                id=r.id, created_at=r.created_at.isoformat(), actor_id=r.actor_id,
                action=r.action, entity=r.entity, entity_id=r.entity_id, details=r.details,
                prev_hash=r.prev_hash, hash=r.hash,
            )
            for r in rows
        ],
    }
