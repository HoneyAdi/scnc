"""Financial periods and chart of accounts (Phase B/C foundation; no posting yet)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.auth import utcnow

ACCOUNT_TYPES = ("asset", "liability", "equity", "income", "expense")


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
