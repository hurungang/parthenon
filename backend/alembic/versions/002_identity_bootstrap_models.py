"""Add identity bootstrap models.

Adds:
  - identity_provider_configs table
  - identity_provider_setup_state table
  - identities.idp_subject column (nullable string, indexed)

Revision ID: 002_identity_bootstrap_models
Revises: 001_baseline
Create Date: 2024-01-02 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "002_identity_bootstrap_models"
down_revision: str | None = "001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── IdentityProviderConfig ───────────────────────────────────────────────
    op.create_table(
        "identity_provider_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "provider_type",
            sa.String(50),
            nullable=False,
            comment="keycloak_bundled | keycloak_external | azure_entraid",
        ),
        sa.Column("oidc_provider_url", sa.String(2048), nullable=False),
        sa.Column("client_id", sa.String(500), nullable=False),
        sa.Column(
            "client_secret",
            sa.String(2048),
            nullable=True,
            comment="AES-256-GCM encrypted client secret",
        ),
        sa.Column("realm_name", sa.String(200), nullable=True),
        sa.Column("audience", sa.String(500), nullable=True),
        sa.Column(
            "is_setup_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("setup_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("setup_completed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["setup_completed_by_id"],
            ["identities.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── IdentityProviderSetupState ───────────────────────────────────────────
    op.create_table(
        "identity_provider_setup_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "is_setup_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["completed_by_id"],
            ["identities.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── identities.idp_subject ───────────────────────────────────────────────
    op.add_column(
        "identities",
        sa.Column("idp_subject", sa.String(500), nullable=True),
    )
    op.create_index(
        "ix_identities_idp_subject",
        "identities",
        ["idp_subject"],
        unique=False,
    )


def downgrade() -> None:
    # Remove index and column from identities
    op.drop_index("ix_identities_idp_subject", table_name="identities")
    op.drop_column("identities", "idp_subject")

    # Drop new tables
    op.drop_table("identity_provider_setup_state")
    op.drop_table("identity_provider_configs")
