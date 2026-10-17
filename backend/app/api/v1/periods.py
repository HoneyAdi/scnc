"""Financial periods endpoints (permission-gated). No reopen endpoint exists:
a closed period stays closed until a future controlled reopen workflow."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.api import deps, schemas
from app.models.accounting import FinancialPeriod
from app.models.auth import User
from app.services import accounting_service

router = APIRouter(prefix="/periods", tags=["periods"])


def _out(p: FinancialPeriod) -> dict:
    return {
        "id": p.id, "code": p.code, "name": p.name,
        "starts_on": p.starts_on.isoformat(), "ends_on": p.ends_on.isoformat(),
        "status": p.status, "created_by": p.created_by,
        "closed_by": p.closed_by,
        "closed_at": p.closed_at.isoformat() if p.closed_at else None,
    }


@router.get("", dependencies=[Depends(deps.require_permission("periods.view"))])
def list_periods(db: DbSession = Depends(deps.get_db)):
    rows = db.execute(select(FinancialPeriod).order_by(FinancialPeriod.starts_on)).scalars().all()
    return [_out(p) for p in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_period(
    payload: schemas.CreatePeriodRequest,
    db: DbSession = Depends(deps.get_db),
    actor: User = Depends(deps.require_permission("periods.configure")),
):
    try:
        period = accounting_service.create_period(
            db, actor=actor, code=payload.code, name=payload.name,
            starts_on=dt.date.fromisoformat(payload.starts_on),
            ends_on=dt.date.fromisoformat(payload.ends_on),
        )
    except (accounting_service.AccountingError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _out(period)


@router.post("/{period_id}/close")
def close_period(
    period_id: int,
    db: DbSession = Depends(deps.get_db),
    actor: User = Depends(deps.require_permission("periods.configure")),
):
    try:
        period = accounting_service.close_period(db, actor=actor, period_id=period_id)
    except accounting_service.AccountingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return _out(period)
