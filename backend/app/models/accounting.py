"""Financial periods and chart of accounts (Phase B/C foundation; no posting yet)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.auth import utcnow

ACCOUNT_TYPES = ("asset", "liability", "equity", "income", "expense")

# Supported voucher types for the draft foundation. Later types are added by
# their own migration; nothing here invents a college policy.
VOUCHER_TYPES = ("journal", "receipt", "payment", "contra")
# Canonical lifecycle names (DATABASE.md section 2). Only `draft` is reachable
# in this slice; the others are accepted by the schema for forward compatibility
# and no code path sets them (posting/approval do not exist yet).
VOUCHER_STATUSES = (
    "draft", "pending_approval", "edit_requested", "approved_for_posting",
    "posted", "reversed", "rejected", "cancelled",
)
# Human reference prefix per type; the numeric part is the per-(type, FY)
# sequence. A local implementation convention, not a college numbering policy.
VOUCHER_NUMBER_PREFIX = {"journal": "JV", "receipt": "RV", "payment": "PV", "contra": "CV"}


class FinancialPeriod(Base):
    """A configurable financial year (or shorter period). April-March is a
    data choice, never application logic: starts_on/ends_on are free dates."""

    __tablename__ = "financial_periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    starts_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    closed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    closed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("ends_on >= starts_on", name="ck_period_valid_range"),
        CheckConstraint("status IN ('open','closed')", name="ck_period_status"),
    )


class Account(Base):
    """Chart of accounts node. Hierarchy policy: a child's type must equal its
    parent's type; cycles and self-parenting are rejected in service validation.
    Inactive accounts exist for history but must be refused by future posting
    workflows. Accounts are never deleted through the API."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "type IN ('asset','liability','equity','income','expense')",
            name="ck_account_type",
        ),
        CheckConstraint("id <> parent_id", name="ck_account_no_self_parent"),
    )


class NumberSequence(Base):
    """Per-(document type, financial period) counter for human references.

    Incremented inside the same transaction that consumes it, so a failed
    transaction never advances the counter and numbers are never reused.
    """

    __tablename__ = "number_sequences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False)
    fy_id: Mapped[int] = mapped_column(
        ForeignKey("financial_periods.id", ondelete="RESTRICT"), nullable=False
    )
    last_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("doc_type", "fy_id", name="uq_number_sequences_doc_type_fy_id"),
    )


class Voucher(Base):
    """Draft voucher header.

    Only `draft` vouchers are created/read in this foundation slice: there is no
    posting, approval, edit-request, cancel, or reversal path. Drafts are
    excluded from every ledger/report by status; they are deliberately allowed
    to be unbalanced (balance is a POSTING-time rule that is not implemented
    here, so draft and posting validation are never conflated).
    """

    __tablename__ = "vouchers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    voucher_type: Mapped[str] = mapped_column(String(24), nullable=False)
    fy_id: Mapped[int] = mapped_column(
        ForeignKey("financial_periods.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    number: Mapped[str] = mapped_column(String(64), nullable=False)
    voucher_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    narration: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "voucher_type IN ('journal','receipt','payment','contra')",
            name="ck_voucher_type_valid",
        ),
        CheckConstraint(
            "status IN ('draft','pending_approval','edit_requested',"
            "'approved_for_posting','posted','reversed','rejected','cancelled')",
            name="ck_voucher_status_valid",
        ),
        CheckConstraint("number <> ''", name="ck_voucher_number_nonempty"),
        UniqueConstraint(
            "voucher_type", "fy_id", "number", name="uq_vouchers_type_fy_number"
        ),
    )


class VoucherLine(Base):
    """Draft journal line. Row-local checks only (no cross-row balance)."""

    __tablename__ = "voucher_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    voucher_id: Mapped[int] = mapped_column(
        ForeignKey("vouchers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    debit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    credit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    narrative: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        CheckConstraint("debit >= 0 AND credit >= 0", name="ck_voucher_line_nonneg"),
        CheckConstraint(
            "((debit > 0)::int + (credit > 0)::int) = 1",
            name="ck_voucher_line_one_side",
        ),
    )
