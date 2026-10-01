"""add platform_setting_updated tenant audit event type

Extends ``tenant_audit_event_type_enum`` with a
``platform_setting_updated`` value so platform settings writes (including
the ``multi_tenancy_enabled`` switch) are auditable through
``TenantAuditEvent`` alongside tenant lifecycle events.

Additive only — no table or column changes, no existing values removed.

Revision ID: b4d7e1a90c2f
Revises: 31c0e0bc9990
Create Date: 2026-09-20 16:40:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4d7e1a90c2f"
down_revision: str | None = "31c0e0bc9990"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres-style ALTER TYPE for ``tenant_audit_event_type_enum``.
    # The new value is added idempotently; SQLite (test suite) stores
    # enums as plain strings — nothing to alter there.  PostgreSQL 12+
    # permits ADD VALUE inside a transaction as long as the new value is
    # not used within the same transaction, which holds here.
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute(
            sa.text(
                "ALTER TYPE tenant_audit_event_type_enum "
                "ADD VALUE IF NOT EXISTS 'platform_setting_updated'"
            )
        )
    else:
        # SQLite stores enums as plain strings — nothing to alter.
        pass


def downgrade() -> None:
    # PostgreSQL cannot drop enum values; the additive value is left in
    # place on downgrade.  It is unused once the application code no
    # longer writes it, so this is safe.
    pass
