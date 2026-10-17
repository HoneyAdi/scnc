"""Draft voucher + journal-line foundation (NO posting).

Scope of this slice: create, retrieve, and list DRAFT vouchers only.

Deliberately absent (not implemented, not stubbed): posting, approval,
edit-requests, cancellation, reversal, trial balance, and any subledger effect.
A draft never feeds the ledger or any report (it is separated purely by
`status`; only a future `posted` voucher would, and no path to `posted` exists).

Draft vs posting validation are kept distinct on purpose:
  * A DRAFT may be unbalanced and may have a single line; it only has to be
    structurally well-formed (valid type, real open period, in-range date,
    existing active accounts, one positive side per line, precise amounts).
  * POSTING-time rules (balanced totals, minimum two lines, period still open
    at posting, duplicate/idempotency checks) belong to the posting function,
    which is NOT built here. They are intentionally NOT enforced on drafts.

Least privilege (honest statement): this slice mutates vouchers/voucher_lines
through the application's normal ORM session, exactly like the existing
periods/accounts foundation. DATABASE.md sections 2A-2C specify a stricter
future design in which the application role holds no direct write grants and
every mutation runs inside migration-owned `SECURITY DEFINER` functions. That
confinement is NOT implemented here; no SECURITY DEFINER function, elevated
credential, or new grant is introduced speculatively. The divergence is tracked
as an UNRESOLVED design item.
"""
import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.models.accounting import (
    VOUCHER_NUMBER_PREFIX,
    VOUCHER_TYPES,
    Account,
    FinancialPeriod,
    NumberSequence,
    Voucher,
    VoucherLine,
)
from app.models.auth import User
from app.services import audit_service


class VoucherError(Exception):
    pass


_TWO_DP = Decimal("0.01")


def _as_amount(value: object, field: str) -> Decimal:
    """Coerce a JSON amount to a precise Decimal and enforce money rules."""
    if value is None:
        raise VoucherError(f"Line {field} is required.")
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise VoucherError(f"Line {field} must be a decimal amount.")
    if not value.is_finite():
        raise VoucherError(f"Line {field} must be a finite amount.")
    if value < 0:
        raise VoucherError(f"Line {field} must not be negative.")
    # At most two decimal places: quantizing and comparing avoids float math.
    if value != value.quantize(_TWO_DP):
        raise VoucherError(f"Line {field} must have at most 2 decimal places.")
    return value


def _next_number(db: DbSession, voucher_type: str, fy_id: int) -> int:
    """Reserve the next per-(type, FY) sequence in the current transaction.

    The advisory lock serializes reservation across processes; because the
    increment shares the caller's transaction, a later failure rolls it back and
    the number is never consumed (no gaps on failure, and never a reuse).
    """
    key = f"scn_voucher_seq_{voucher_type}_{fy_id}"
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": key})
    seq = db.execute(
        select(NumberSequence).where(
            NumberSequence.doc_type == voucher_type,
            NumberSequence.fy_id == fy_id,
        )
    ).scalar_one_or_none()
    if seq is None:
        seq = NumberSequence(doc_type=voucher_type, fy_id=fy_id, last_number=0)
        db.add(seq)
    seq.last_number += 1
    db.add(seq)
    db.flush()
    return seq.last_number


def _validate_lines(
    db: DbSession, lines: Iterable[Mapping]
) -> list[tuple[int, Decimal, Decimal, str]]:
    validated: list[tuple[int, Decimal, Decimal, str]] = []
    for index, line in enumerate(lines, start=1):
        account_id = line.get("account_id")
        account = db.get(Account, account_id) if account_id is not None else None
        if account is None:
            raise VoucherError(f"Line {index}: account not found.")
        if not account.is_active:
            raise VoucherError(f"Line {index}: account is inactive.")
        debit = _as_amount(line.get("debit", Decimal("0")), "debit")
        credit = _as_amount(line.get("credit", Decimal("0")), "credit")
        if (debit > 0) == (credit > 0):
            raise VoucherError(
                f"Line {index}: exactly one of debit or credit must be positive."
            )
        narrative = line.get("narrative") or ""
        validated.append((account.id, debit, credit, str(narrative)))
    return validated


def create_draft_voucher(
    db: DbSession,
    *,
    actor: User,
    voucher_type: str,
    fy_id: int,
    voucher_date: dt.date,
    narration: str = "",
    lines: Iterable[Mapping],
) -> Voucher:
    """Create a DRAFT voucher and its lines atomically (no partial rows)."""
    if voucher_type not in VOUCHER_TYPES:
        raise VoucherError(f"Unsupported voucher type: {voucher_type}.")

    period = db.get(FinancialPeriod, fy_id)
    if period is None:
        raise VoucherError("Financial period not found.")
    if period.status != "open":
        raise VoucherError("Financial period is closed.")
    if voucher_date < period.starts_on or voucher_date > period.ends_on:
        raise VoucherError("Voucher date falls outside the financial period.")

    validated = _validate_lines(db, lines)
    if not validated:
        raise VoucherError("A voucher requires at least one line.")

    seq = _next_number(db, voucher_type, fy_id)
    number = f"{VOUCHER_NUMBER_PREFIX[voucher_type]}-{seq:05d}"

    voucher = Voucher(
        voucher_type=voucher_type,
        fy_id=fy_id,
        number=number,
        voucher_date=voucher_date,
        narration=narration or "",
        status="draft",
        version=1,
        created_by=actor.id,
    )
    db.add(voucher)
    try:
        db.flush()
        for account_id, debit, credit, narrative in validated:
            db.add(
                VoucherLine(
                    voucher_id=voucher.id,
                    account_id=account_id,
                    debit=debit,
                    credit=credit,
                    narrative=narrative,
                )
            )
        db.flush()
    except IntegrityError:
        # Any failure (line CHECK, FK, duplicate number) aborts the whole
        # create: roll back the aborted transaction so the session is reusable
        # and no partial voucher/line persists.
        db.rollback()
        raise VoucherError("Voucher could not be saved (invalid line or duplicate number).")

    audit_service.log_event(
        db,
        actor_id=actor.id,
        action="voucher.create",
        entity="vouchers",
        entity_id=voucher.id,
        details={
            "number": number,
            "voucher_type": voucher_type,
            "fy_id": fy_id,
            "voucher_date": str(voucher_date),
            "line_count": len(validated),
            "status": "draft",
        },
    )
    db.commit()
    db.refresh(voucher)
    return voucher


def get_voucher(db: DbSession, voucher_id: int) -> tuple[Voucher, list[VoucherLine]]:
    voucher = db.get(Voucher, voucher_id)
    if voucher is None:
        raise VoucherError("Voucher not found.")
    lines = (
        db.execute(
            select(VoucherLine)
            .where(VoucherLine.voucher_id == voucher.id)
            .order_by(VoucherLine.id)
        )
        .scalars()
        .all()
    )
    return voucher, list(lines)


def list_vouchers(db: DbSession, *, limit: int, offset: int) -> tuple[int, list[Voucher]]:
    total = db.execute(select(func.count(Voucher.id))).scalar() or 0
    rows = (
        db.execute(
            select(Voucher).order_by(Voucher.id.desc()).limit(limit).offset(offset)
        )
        .scalars()
        .all()
    )
    return int(total), list(rows)
