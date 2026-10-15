"""Decision guardrail scoping: config_source discriminator + decision_provider_id.

FIX-20261014-003000 — embed guardrail management in the Decision Model
Providers module by reusing the existing ``model_guardrail_configurations``
table. Rows are discriminated by ``config_source`` ('model_config' for LLM
vendors, 'decision_provider' for decision providers); decision rows key via
the new nullable ``decision_provider_id`` FK, so ``model_id`` becomes
nullable.

Revision ID: b7d2e9f4a1c8
Revises: 8144e472dce9
Create Date: 2026-10-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b7d2e9f4a1c8"
down_revision = "8144e472dce9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_guardrail_configurations",
        sa.Column(
            "config_source",
            sa.String(length=32),
            nullable=False,
            server_default="model_config",
        ),
    )
    # Backfill (idempotent — server_default already covers new rows).
    op.execute(
        "UPDATE model_guardrail_configurations "
        "SET config_source = 'model_config' WHERE config_source IS NULL"
    )
    op.alter_column("model_guardrail_configurations", "model_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.add_column(
        "model_guardrail_configurations",
        sa.Column("decision_provider_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_model_guardrail_configurations_decision_provider",
        "model_guardrail_configurations",
        ["decision_provider_id"],
    )
    op.create_index(
        "uq_guardrail_decision_model_period",
        "model_guardrail_configurations",
        ["decision_provider_id", "model_name", "period"],
        unique=True,
        postgresql_where=sa.text("decision_provider_id IS NOT NULL"),
    )
    op.create_foreign_key(
        "fk_model_guardrail_configurations_decision_provider",
        "model_guardrail_configurations",
        "system_one_provider_configs",
        ["decision_provider_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Refuse to drop rows that only exist in the decision scope.
    op.execute(
        "DELETE FROM model_guardrail_configurations "
        "WHERE config_source = 'decision_provider'"
    )
    op.drop_constraint(
        "fk_model_guardrail_configurations_decision_provider",
        "model_guardrail_configurations",
        type_="foreignkey",
    )
    op.drop_index(
        "uq_guardrail_decision_model_period", table_name="model_guardrail_configurations"
    )
    op.drop_index(
        "ix_model_guardrail_configurations_decision_provider",
        table_name="model_guardrail_configurations",
    )
    op.drop_column("model_guardrail_configurations", "decision_provider_id")
    op.alter_column("model_guardrail_configurations", "model_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.drop_column("model_guardrail_configurations", "config_source")
