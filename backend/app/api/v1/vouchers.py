"""Draft voucher endpoints (permission-gated, NO posting).

Only draft create/read/list exist. There is deliberately no update, delete,
submit, approve, post, reverse, or cancel endpoint: drafts are corrected by
creating a new draft and a future controlled workflow, and posting does not
exist yet. Posting-time rules (balance, minimum two lines) are NOT enforced
here because a draft is not a posting.
"""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session as DbSession

from app.api import deps, schemas
from app.models.accounting import Voucher, VoucherLine
from app.models.auth import User
from app.services import voucher_service

router = APIRouter(prefix="/vouchers", tags=["vouchers"])


def _line_out(line: VoucherLine) -> dict:
    # Money is emitted as a precise decimal string, never a float.
    return {
        "id": line.id, "account_id": line.account_id,
        "debit": str(line.debit), "credit": str(line.credit),
        "narrative": line.narrative,
    }


def _voucher_out(v: Voucher) -> dict:
    return {
        "id": v.id, "voucher_type": v.voucher_type, "fy_id": v.fy_id,
        "number": v.number, "voucher_date": v.voucher_date.isoformat(),
        "narration": v.narration, "status": v.status, "version": v.version,
        "created_by": v.created_by,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


@router.get("", dependencies=[Depends(deps.require_permission("vouchers.view"))])
def list_vouchers(
    db: DbSession = Depends(deps.get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    total, rows = voucher_service.list_vouchers(db, limit=limit, offset=offset)
    return {"total": total, "items": [_voucher_out(v) for v in rows]}


@router.get("/{voucher_id}", dependencies=[Depends(deps.require_permission("vouchers.view"))])
def get_voucher(voucher_id: int, db: DbSession = Depends(deps.get_db)):
    try:
        voucher, lines = voucher_service.get_voucher(db, voucher_id)
    except voucher_service.VoucherError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    payload = _voucher_out(voucher)
    payload["lines"] = [_line_out(line) for line in lines]
    return payload


@router.post("", status_code=status.HTTP_201_CREATED)
def create_voucher(
    payload: schemas.CreateVoucherRequest,
    db: DbSession = Depends(deps.get_db),
    actor: User = Depends(deps.require_permission("vouchers.create")),
):
    try:
        voucher_date = dt.date.fromisoformat(payload.voucher_date)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="voucher_date must be an ISO calendar date (YYYY-MM-DD).",
        )
    try:
        voucher = voucher_service.create_draft_voucher(
            db, actor=actor, voucher_type=payload.voucher_type, fy_id=payload.fy_id,
            voucher_date=voucher_date, narration=payload.narration,
            lines=[line.model_dump() for line in payload.lines],
        )
    except voucher_service.VoucherError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _voucher_out(voucher)
