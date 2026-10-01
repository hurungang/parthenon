"""phase 10 licensing quota schema

Phase 10 — Self-Serve Registration, Tenant Root & Licensing (additive only):

- New tables ``tenant_licenses`` (tier + growth limits, latest-active-wins
  history via partial unique index) and ``tenant_quota_usage`` (per-tenant
  calendar-month quota counters).
- ``platform_users.password_credential`` — platform-issued password secret
  stored HASHED only (nullable; OIDC-federated users stay NULL).
- ``tenant_user_memberships.is_root`` — immutable root/owner membership
  flag (server-default false; partial unique index enforces at most one
  root per tenant).
- ``tenant_audit_event_type_enum`` gains the six Phase 10 event values.

Hand-reviewed against AGENTS.md migration best practices: autogenerate
drift (an unrelated ``super_admin_credentials`` drop, agent-role join
unique constraints and an invitation index churn) was EXCLUDED; enum
values are added idempotently via ALTER TYPE ... ADD VALUE IF NOT EXISTS;
no parameterized DDL.  PostgreSQL cannot drop enum values, so the six new
values remain in place on downgrade (unused once the code no longer
writes them — same approach as migration ``b4d7e1a90c2f``).

Revision ID: 6363bb7ee8c3
Revises: d9f3a6c2e7b1
Create Date: 2026-09-26 13:12:32.566034

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6363bb7ee8c3"
down_revision: str | None = "d9f3a6c2e7b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LICENSE_TIER = postgresql.ENUM(
    "free", "team", "enterprise", name="license_tier_enum", create_type=False
)
_QUOTA_TYPE = postgresql.ENUM(
    "users", "agent_types", "monthly_executions", name="quota_type_enum", create_type=False
)

# Phase 10 additions to ``tenant_audit_event_type_enum``
_NEW_AUDIT_EVENT_VALUES = (
    "self_serve_registration",
    "root_protection_rejected",
    "license_assigned",
    "license_changed",
    "license_removed",
    "quota_exhausted",
)


def upgrade() -> None:
    # 1. New enum types (idempotent — models also create them on import
    #    for fresh databases created via metadata.create_all / SQLite).
    _LICENSE_TIER.create(op.get_bind(), checkfirst=True)
    _QUOTA_TYPE.create(op.get_bind(), checkfirst=True)

    # 2. Tenant audit event enum gains the Phase 10 values (PostgreSQL
    #    only; SQLite stores enums as plain strings).  PG 12+ permits
    #    ADD VALUE inside a transaction as long as the value is not used
    #    within the same transaction, which holds here.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for value in _NEW_AUDIT_EVENT_VALUES:
            # PostgreSQL does not support parameterized DDL — the value is
            # interpolated (it is a fixed literal from _NEW_AUDIT_EVENT_VALUES).
            op.execute(
                sa.text(
                    f"ALTER TYPE tenant_audit_event_type_enum "
                    f"ADD VALUE IF NOT EXISTS '{value}'"
                )
            )

    # 3. Tenant licenses (supersede history; at most one active per tenant)
    op.create_table(
        "tenant_licenses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("tier", _LICENSE_TIER, nullable=False),
        sa.Column("max_users", sa.Integer(), nullable=False),
        sa.Column("max_agent_types", sa.Integer(), nullable=False),
        sa.Column("monthly_agent_executions", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("unassigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenant_licenses_tenant_id", "tenant_licenses", ["tenant_id"], unique=False)
    op.create_index(
        "uq_tenant_license_single_active",
        "tenant_licenses",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )

    # 4. Quota usage counters (unique per tenant/quota/month bucket)
    op.create_table(
        "tenant_quota_usage",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("quota_type", _QUOTA_TYPE, nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "quota_type", "period_start",
            name="uq_tenant_quota_usage_tenant_type_period",
        ),
    )

    # 5. Platform-issued password credential (hashed; nullable — existing
    #    OIDC users are unaffected)
    op.add_column(
        "platform_users",
        sa.Column("password_credential", sa.String(length=255), nullable=True),
    )

    # 6. Root membership flag + at-most-one-root-per-tenant partial index
    op.add_column(
        "tenant_user_memberships",
        sa.Column("is_root", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_index(
        "uq_tenant_membership_single_root",
        "tenant_user_memberships",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_root = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_tenant_membership_single_root",
        table_name="tenant_user_memberships",
        postgresql_where=sa.text("is_root = true"),
    )
    op.drop_column("tenant_user_memberships", "is_root")
    op.drop_column("platform_users", "password_credential")
    op.drop_table("tenant_quota_usage")
    op.drop_index(
        "uq_tenant_license_single_active",
        table_name="tenant_licenses",
        postgresql_where=sa.text("is_active = true"),
    )
    op.drop_index("ix_tenant_licenses_tenant_id", table_name="tenant_licenses")
    op.drop_table("tenant_licenses")

    # PostgreSQL cannot drop enum values: the six Phase 10 audit values
    # and the two new enum types are left in place.  They are unused once
    # the application code no longer writes them, so this is safe (same
    # approach as migration b4d7e1a90c2f).
