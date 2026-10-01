"""add tenant invitation token_hash

Adds a nullable, indexed ``token_hash`` column (SHA-256 hex of the
single-use acceptance token) to ``tenant_invitations`` so invitees can
accept via a public token endpoint.  The raw token is shown once at
creation and never stored.  Additive and backward-compatible.

Revision ID: d9f3a6c2e7b1
Revises: c8e2f5b17a93
Create Date: 2026-09-21 09:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d9f3a6c2e7b1"
down_revision: str | None = "c8e2f5b17a93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.add_column(
            "tenant_invitations",
            sa.Column("token_hash", sa.String(length=64), nullable=True),
        )
        op.create_index(
            "ix_tenant_invitations_token_hash",
            "tenant_invitations",
            ["token_hash"],
            unique=True,
            postgresql_where=sa.text("token_hash IS NOT NULL"),
        )
    else:
        # SQLite (test suite): plain column + unique index
        op.add_column(
            "tenant_invitations",
            sa.Column("token_hash", sa.String(length=64), nullable=True),
        )
        op.create_index(
            "ix_tenant_invitations_token_hash",
            "tenant_invitations",
            ["token_hash"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_index("ix_tenant_invitations_token_hash", table_name="tenant_invitations")
    else:
        op.drop_index("ix_tenant_invitations_token_hash", table_name="tenant_invitations")
    op.drop_column("tenant_invitations", "token_hash")
