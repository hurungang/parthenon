"""FIX-20260930-075014: JIT default tenant role on identity provider configs

Additive, reversible: adds the nullable ``default_tenant_role`` column to
``identity_provider_configs`` — a non-native enum (VARCHAR + CHECK) over the
four seeded preset role keys (tenant_system_admin / agent_manager /
agent_executor / agent_viewer).  NULL (the default for every existing row)
means "no JIT" — first OIDC sign-ins without a membership keep the existing
``no_access_to_workspace`` 403 semantics.

The enum deliberately does NOT create a PostgreSQL type (``native_enum=
False``) per project migration conventions — no ``CREATE TYPE``/``ALTER
TYPE`` handling is needed and the downgrade is a plain column drop.

Revision ID: a1f2c3d4e5b6
Revises: 6363bb7ee8c3
Create Date: 2026-09-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1f2c3d4e5b6"
down_revision: Union[str, None] = "6363bb7ee8c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "identity_provider_configs"
_CHECK = "ck_identity_provider_configs_default_tenant_role"
_ALLOWED = (
    "tenant_system_admin",
    "agent_manager",
    "agent_executor",
    "agent_viewer",
)


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("default_tenant_role", sa.String(length=50), nullable=True),
    )
    op.create_check_constraint(
        _CHECK,
        _TABLE,
        sa.or_(
            sa.column("default_tenant_role").is_(None),
            sa.column("default_tenant_role").in_(_ALLOWED),
        ),
    )


def downgrade() -> None:
    op.drop_constraint(_CHECK, _TABLE, type_="check")
    op.drop_column(_TABLE, "default_tenant_role")
