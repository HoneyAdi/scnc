"""0001 auth foundation: users, roles, permissions, sessions, audit, settings + seed.

Revision ID: 0001
Revises: None
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

PERMISSIONS = [
    ("users.view", "users", "view"),
    ("users.create", "users", "create"),
    ("users.edit", "users", "edit"),
    ("users.deactivate", "users", "deactivate"),
    ("roles.view", "roles", "view"),
    ("roles.administer", "roles", "administer"),
    ("audit.view", "audit", "view"),
    ("settings.view", "settings", "view"),
]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failed_logins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("description", sa.String(255), nullable=False, server_default=""),
    )
    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(128), nullable=False, unique=True),
        sa.Column("module", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("permission_id", sa.Integer(), sa.ForeignKey("permissions.id", ondelete="RESTRICT"), primary_key=True),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("entity", sa.String(128), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_audit_log_created", "audit_log", ["created_at"])
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Seed: permission codes + Super Admin role holding all of them. No users, no secrets.
    for code, module, action in PERMISSIONS:
        op.execute(
            sa.text(
                "INSERT INTO permissions (code, module, action) VALUES "
                "(:code, :module, :action) ON CONFLICT (code) DO NOTHING"
            ).bindparams(code=code, module=module, action=action)
        )
    op.execute(
        sa.text(
            "INSERT INTO roles (name, is_system, description) VALUES "
            "('Super Admin', true, 'Full administration') "
            "ON CONFLICT (name) DO NOTHING"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
            "WHERE r.name = 'Super Admin' "
            "ON CONFLICT DO NOTHING"
        )
    )


def downgrade() -> None:
    op.drop_table("system_settings")
    op.drop_index("ix_audit_log_created", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("sessions")
    op.drop_table("role_permissions")
    op.drop_table("user_roles")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_table("users")
