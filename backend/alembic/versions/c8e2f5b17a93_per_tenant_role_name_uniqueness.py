"""per-tenant role name uniqueness

Multi-tenancy: role names become unique **per tenant** instead of
platform-wide, so identical role names in different tenants do not
collide (PermissionEngine tenant binding).  Global (tenant-less) roles
keep platform-wide unique names via a partial unique index.

- Drop: roles_name_key (UNIQUE (name))
- Add:  uq_roles_tenant_name (UNIQUE (tenant_id, name)) — NULL tenant_id
        rows are exempt (NULLs distinct), covered by:
- Add:  uq_roles_global_name (UNIQUE (name) WHERE tenant_id IS NULL)

Additive and backward-compatible: existing rows (tenant_id NULL) satisfy
the partial global-name index because platform-wide names were already
unique.

Revision ID: c8e2f5b17a93
Revises: b4d7e1a90c2f
Create Date: 2026-09-20 16:55:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8e2f5b17a93"
down_revision: str | None = "b4d7e1a90c2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite (unit tests) stores unique constraints inline — the
        # models' table_args carry the new semantics for fresh schemas.
        return
    # PostgreSQL does not support parameterized DDL — plain SQL per
    # project migration conventions.
    op.execute("ALTER TABLE roles DROP CONSTRAINT IF EXISTS roles_name_key")
    op.execute(
        "ALTER TABLE roles ADD CONSTRAINT uq_roles_tenant_name "
        "UNIQUE (tenant_id, name)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_roles_global_name "
        "ON roles (name) WHERE tenant_id IS NULL"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # Reversing to platform-wide name uniqueness could fail if duplicate
    # names were created across tenants while multi-tenant mode was on;
    # that is an operator-visible data condition and not silently
    # destroyed here.
    op.execute("DROP INDEX IF EXISTS uq_roles_global_name")
    op.execute("ALTER TABLE roles DROP CONSTRAINT IF EXISTS uq_roles_tenant_name")
    op.execute("ALTER TABLE roles ADD CONSTRAINT roles_name_key UNIQUE (name)")
