"""Financial periods and chart of accounts: validated, audited, least-privilege.

Scope: masters only. No voucher posting exists yet; posting workflows (later)
must refuse inactive accounts and closed periods — enforced there, not here.
"""
import datetime as dt

from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session as DbSession

from app.models.accounting import ACCOUNT_TYPES, Account, FinancialPeriod
from app.models.auth import User, utcnow
from app.services import audit_service


class AccountingError(Exception):
    pass


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
    db.flush()
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
    account = Account(
        code=code, name=name, type=type, parent_id=parent_id,
        description=description, created_by=actor.id,
    )
    db.add(account)
    db.flush()
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
