"""0003 draft voucher foundation: vouchers, voucher_lines, number_sequences, permissions.

Draft-only slice: no posting/approval/reversal tables or triggers. No new
grants are created and no SECURITY DEFINER object is introduced; vouchers are
written through the application role exactly like the periods/accounts
foundation. The stricter DATABASE.md 2A-2C privilege confinement remains an
unresolved design item.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

PERMISSIONS = [
    ("vouchers.view", "vouchers", "view"),
    ("vouchers.create", "vouchers", "create"),
]


def upgrade() -> None:
    op.create_table(
        "number_sequences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doc_type", sa.String(32), nullable=False),
        sa.Column("fy_id", sa.Integer(), sa.ForeignKey("financial_periods.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("doc_type", "fy_id", name="uq_number_sequences_doc_type_fy_id"),
    )
    op.create_table(
        "vouchers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("voucher_type", sa.String(24), nullable=False),
        sa.Column("fy_id", sa.Integer(), sa.ForeignKey("financial_periods.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("number", sa.String(64), nullable=False),
        sa.Column("voucher_date", sa.Date(), nullable=False),
        sa.Column("narration", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "voucher_type IN ('journal','receipt','payment','contra')",
            name="ck_voucher_type_valid",
        ),
        sa.CheckConstraint(
            "status IN ('draft','pending_approval','edit_requested',"
            "'approved_for_posting','posted','reversed','rejected','cancelled')",
            name="ck_voucher_status_valid",
        ),
        sa.CheckConstraint("number <> ''", name="ck_voucher_number_nonempty"),
        sa.UniqueConstraint("voucher_type", "fy_id", "number", name="uq_vouchers_type_fy_number"),
    )
    op.create_index("ix_vouchers_fy_id", "vouchers", ["fy_id"])
    op.create_index("ix_vouchers_created_by", "vouchers", ["created_by"])
    op.create_table(
        "voucher_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("voucher_id", sa.Integer(), sa.ForeignKey("vouchers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("debit", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("credit", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("narrative", sa.Text(), nullable=False, server_default=""),
        sa.CheckConstraint("debit >= 0 AND credit >= 0", name="ck_voucher_line_nonneg"),
        sa.CheckConstraint(
            "((debit > 0)::int + (credit > 0)::int) = 1",
            name="ck_voucher_line_one_side",
        ),
    )
    op.create_index("ix_voucher_lines_voucher_id", "voucher_lines", ["voucher_id"])
    op.create_index("ix_voucher_lines_account_id", "voucher_lines", ["account_id"])

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
            "AND p.code IN ('vouchers.view', 'vouchers.create')"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE code IN ('vouchers.view', 'vouchers.create'))"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM permissions WHERE code IN ('vouchers.view', 'vouchers.create')"
        )
    )
    op.drop_index("ix_voucher_lines_account_id", table_name="voucher_lines")
    op.drop_index("ix_voucher_lines_voucher_id", table_name="voucher_lines")
    op.drop_table("voucher_lines")
    op.drop_index("ix_vouchers_created_by", table_name="vouchers")
    op.drop_index("ix_vouchers_fy_id", table_name="vouchers")
    op.drop_table("vouchers")
    op.drop_table("number_sequences")
