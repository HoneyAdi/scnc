"""0002 accounting foundation: financial periods, chart of accounts, permissions.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

PERMISSIONS = [
    ("periods.view", "periods", "view"),
    ("periods.configure", "periods", "configure"),
    ("accounts.view", "accounts", "view"),
    ("accounts.configure", "accounts", "configure"),
]


def upgrade() -> None:
    op.create_table(
        "financial_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("ends_on >= starts_on", name="ck_period_valid_range"),
        sa.CheckConstraint("status IN ('open','closed')", name="ck_period_status"),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "type IN ('asset','liability','equity','income','expense')",
            name="ck_account_type",
        ),
        sa.CheckConstraint("id <> parent_id", name="ck_account_no_self_parent"),
    )
    for code, module, action in PERMISSIONS:
        op.execute(
            sa.text(
                "INSERT INTO permissions (code, module, action) VALUES "
                "(:code, :module, :action) ON CONFLICT (code) DO NOTHING"
            ).bindparams(code=code, module=module, action=action)
        )
    op.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
            "WHERE r.name = 'Super Admin' "
            "AND p.code IN ('periods.view','periods.configure','accounts.view','accounts.configure') "
            "ON CONFLICT DO NOTHING"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE code IN "
            "('periods.view','periods.configure','accounts.view','accounts.configure'))"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM permissions WHERE code IN "
            "('periods.view','periods.configure','accounts.view','accounts.configure')"
        )
    )
    op.drop_table("accounts")
    op.drop_table("financial_periods")
