"""Financial periods and chart of accounts: validated, audited, least-privilege.

Scope: masters only. No voucher posting exists yet; posting workflows (later)
must refuse inactive accounts and closed periods — enforced there, not here.
"""
import datetime as dt
from typing import Callable

from sqlalchemy import and_, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.models.accounting import ACCOUNT_TYPES, Account, FinancialPeriod
from app.models.auth import User, utcnow
from app.services import audit_service


class AccountingError(Exception):
    pass


# Test-only synchronization hook: None under normal operation, and no
# application code ever sets it. A concurrency test may install a callable here
# so that two concurrent create_period/create_account calls both reach the
# post-validation stage before either can complete the competing insert. This
# proves overlap deterministically instead of relying on thread timing; the
# hook is inert in production. See TESTING.md.
_create_barrier: "Callable[[], None] | None" = None


def _hit_create_barrier() -> None:
    barrier = _create_barrier
    if barrier is not None:
        barrier()


# PostgreSQL SQLSTATE for a unique-constraint violation.
_PG_UNIQUE_VIOLATION = "23505"
# The single unique index that means "code already exists" for each table.
_PERIOD_CODE_CONSTRAINT = "uq_financial_periods_code"
_ACCOUNT_CODE_CONSTRAINT = "uq_accounts_code"


def _is_duplicate_code_error(exc: IntegrityError, constraint: str) -> bool:
    """True ONLY when the failed flush violated the named CODE unique index.

    Classifies by the stable server SQLSTATE (23505) and the constraint name
    from the server diagnostic -- never by human-readable message text, which is
    locale/version dependent. Any other integrity failure (foreign key, check,
    or an unforeseen unique index) returns False so it can propagate instead of
    being mislabeled as a duplicate code.
    """
    orig = getattr(exc, "orig", None)
    if getattr(orig, "sqlstate", None) != _PG_UNIQUE_VIOLATION:
        return False
    diag = getattr(orig, "diag", None)
    name = getattr(diag, "constraint_name", None) if diag is not None else None
    return name == constraint


def _period_overlap(db: DbSession, starts_on: dt.date, ends_on: dt.date, exclude_id: int | None = None):
    stmt = select(FinancialPeriod).where(
        and_(FinancialPeriod.starts_on <= ends_on, FinancialPeriod.ends_on >= starts_on)
    )
    if exclude_id is not None:
        stmt = stmt.where(FinancialPeriod.id != exclude_id)
    return db.execute(stmt).scalars().all()


def create_period(
    db: DbSession, *, actor: User, code: str, name: str,
    starts_on: dt.date, ends_on: dt.date,
) -> FinancialPeriod:
    if ends_on < starts_on:
        raise AccountingError("Period end date must be on or after the start date.")
    if db.execute(select(FinancialPeriod).where(FinancialPeriod.code == code)).scalar_one_or_none():
        raise AccountingError("Period code already exists.")
    _hit_create_barrier()
    # Serialize concurrent creations: the overlap check and the insert must be
    # atomic with respect to each other across processes.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('scn_periods'))"))
    if _period_overlap(db, starts_on, ends_on):
        raise AccountingError("Period overlaps an existing financial period.")
    period = FinancialPeriod(
        code=code, name=name, starts_on=starts_on, ends_on=ends_on,
        status="open", created_by=actor.id,
    )
    db.add(period)
    try:
        db.flush()
    except IntegrityError as exc:
        # Roll back the aborted transaction before the session is reused. Only a
        # concurrent SAME-CODE insert (unique index on code) is translated into
        # the clean rejection a sequential caller sees; every other integrity
        # failure propagates and is handled by the app's normal error path.
        db.rollback()
        if _is_duplicate_code_error(exc, _PERIOD_CODE_CONSTRAINT):
            raise AccountingError("Period code already exists.")
        raise
    audit_service.log_event(
        db, actor_id=actor.id, action="period.create", entity="financial_periods",
        entity_id=period.id,
        details={"code": code, "name": name, "starts_on": str(starts_on), "ends_on": str(ends_on)},
    )
    db.commit()
    db.refresh(period)
    return period


def close_period(db: DbSession, *, actor: User, period_id: int) -> FinancialPeriod:
    period = db.get(FinancialPeriod, period_id)
    if period is None:
        raise AccountingError("Period not found.")
    if period.status == "closed":
        raise AccountingError("Period is already closed.")
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('scn_periods'))"))
    db.refresh(period)
    if period.status == "closed":
        raise AccountingError("Period is already closed.")
    period.status = "closed"
    period.closed_by = actor.id
    period.closed_at = utcnow()
    db.add(period)
    db.flush()
    audit_service.log_event(
        db, actor_id=actor.id, action="period.close", entity="financial_periods",
        entity_id=period.id, details={"code": period.code},
    )
    db.commit()
    db.refresh(period)
    return period


def _assert_no_cycle(db: DbSession, account_id: int | None, parent_id: int | None) -> None:
    seen = set()
    current = parent_id
    while current is not None:
        if account_id is not None and current == account_id:
            raise AccountingError("Circular account hierarchy is not allowed.")
        if current in seen:
            raise AccountingError("Circular account hierarchy is not allowed.")
        seen.add(current)
        parent = db.get(Account, current)
        if parent is None:
            break
        current = parent.parent_id


def create_account(
    db: DbSession, *, actor: User, code: str, name: str, type: str,
    parent_id: int | None = None, description: str = "",
) -> Account:
    if type not in ACCOUNT_TYPES:
        raise AccountingError(f"Invalid account type: {type}.")
    if db.execute(select(Account).where(Account.code == code)).scalar_one_or_none():
        raise AccountingError("Account code already exists.")
    parent = None
    if parent_id is not None:
        parent = db.get(Account, parent_id)
        if parent is None:
            raise AccountingError("Parent account not found.")
        if not parent.is_active:
            raise AccountingError("Parent account is inactive.")
        if parent.type != type:
            raise AccountingError("Child account type must equal its parent's type.")
    _hit_create_barrier()
    account = Account(
        code=code, name=name, type=type, parent_id=parent_id,
        description=description, created_by=actor.id,
    )
    db.add(account)
    try:
        db.flush()
    except IntegrityError as exc:
        # Roll back the aborted transaction before the session is reused. Only a
        # concurrent SAME-CODE insert (unique index on code) becomes the clean
        # duplicate rejection; any other integrity failure (FK, check, or an
        # unforeseen unique index) propagates instead of being masked as a 400.
        db.rollback()
        if _is_duplicate_code_error(exc, _ACCOUNT_CODE_CONSTRAINT):
            raise AccountingError("Account code already exists.")
        raise
    _assert_no_cycle(db, account.id, parent_id)
    audit_service.log_event(
        db, actor_id=actor.id, action="account.create", entity="accounts",
        entity_id=account.id,
        details={"code": code, "name": name, "type": type, "parent_id": parent_id},
    )
    db.commit()
    db.refresh(account)
    return account


def update_account(
    db: DbSession, *, actor: User, account_id: int,
    name: str | None = None, is_active: bool | None = None,
) -> Account:
    """Limited edits only (name, active flag). No deletion endpoint exists:
    accounts referenced by future accounting records must never disappear, and
    history must survive deactivation."""
    account = db.get(Account, account_id)
    if account is None:
        raise AccountingError("Account not found.")
    before = {"name": account.name, "is_active": account.is_active}
    if name is not None:
        account.name = name
    if is_active is not None:
        account.is_active = is_active
    db.add(account)
    db.flush()
    audit_service.log_event(
        db, actor_id=actor.id, action="account.edit", entity="accounts",
        entity_id=account.id,
        details={"before": before, "after": {"name": account.name, "is_active": account.is_active}},
    )
    db.commit()
    db.refresh(account)
    return account
