"""Chart of accounts endpoints (permission-gated). No delete endpoint exists:
accounts with history must never disappear; deactivation preserves history."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.api import deps, schemas
from app.models.accounting import Account
from app.models.auth import User
from app.services import accounting_service

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _out(a: Account) -> dict:
    return {
        "id": a.id, "code": a.code, "name": a.name, "type": a.type,
        "parent_id": a.parent_id, "is_active": a.is_active, "is_system": a.is_system,
        "description": a.description,
    }


@router.get("", dependencies=[Depends(deps.require_permission("accounts.view"))])
def list_accounts(
    db: DbSession = Depends(deps.get_db),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    total = db.execute(select(func.count(Account.id))).scalar() or 0
    rows = db.execute(select(Account).order_by(Account.code).limit(limit).offset(offset)).scalars().all()
    return {"total": total, "items": [_out(a) for a in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_account(
    payload: schemas.CreateAccountRequest,
    db: DbSession = Depends(deps.get_db),
    actor: User = Depends(deps.require_permission("accounts.configure")),
):
    try:
        account = accounting_service.create_account(
            db, actor=actor, code=payload.code, name=payload.name,
            type=payload.type, parent_id=payload.parent_id,
            description=payload.description,
        )
    except accounting_service.AccountingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _out(account)


@router.patch("/{account_id}")
def update_account(
    account_id: int,
    payload: schemas.UpdateAccountRequest,
    db: DbSession = Depends(deps.get_db),
    actor: User = Depends(deps.require_permission("accounts.configure")),
):
    try:
        account = accounting_service.update_account(
            db, actor=actor, account_id=account_id,
            name=payload.name, is_active=payload.is_active,
        )
    except accounting_service.AccountingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _out(account)
