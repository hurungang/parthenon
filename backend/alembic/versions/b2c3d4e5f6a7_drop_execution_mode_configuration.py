"""drop execution mode configuration; add repair attempts and repair lineage

Follow-up revision for the Software 3.0 refinement (data-model.md §1.6/§1.7):

- Drops the ``execution_mode_configurations`` table — there are no execution
  modes; script-first execution with unconditional LLM fallback is fixed
  platform behavior.
- Drops the ``execution_mode`` column from ``script_execution_records`` and
  adds ``identity_parity_confirmed`` (E7/SEC1 evidence).
- Adds the ``repair_attempts`` table and the ``repaired_from_id`` repair
  lineage column on ``script_versions``.

Reversible: the downgrade re-creates everything that upgrade removes.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4f5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Enums are created by model import (see AGENTS.md) — never re-created here.
repair_retry_outcome = postgresql.ENUM(
    "pending",
    "succeeded",
    "failed",
    name="repair_retry_outcome_enum",
    create_type=False,
)
script_execution_mode = postgresql.ENUM(
    "llm",
    "compiled_with_fallback",
    "compiled_only",
    name="script_execution_mode_enum",
    create_type=False,
)


def upgrade() -> None:
    # Create the new enum if it does not exist yet (model import does not
    # guarantee creation in this path — see AGENTS.md migration rules).
    op.execute(
        "DO $$ BEGIN\n"
        "    CREATE TYPE repair_retry_outcome_enum AS ENUM "
        "('pending', 'succeeded', 'failed');\n"
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )

    # ── Drop ExecutionModeConfiguration (no execution modes exist) ─────────
    op.drop_table("execution_mode_configurations")

    # ── Strip the mode attribute from execution records (G2) ───────────────
    op.drop_column("script_execution_records", "execution_mode")
    op.add_column(
        "script_execution_records",
        sa.Column("identity_parity_confirmed", sa.Boolean(), nullable=True),
    )

    # ── Repair lineage on ScriptVersion (E9/E10) ───────────────────────────
    op.add_column(
        "script_versions",
        sa.Column("repaired_from_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_script_versions_repaired_from_id",
        "script_versions",
        "script_versions",
        ["repaired_from_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ── RepairAttempt table (E10, G2) ──────────────────────────────────────
    op.create_table(
        "repair_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=True),
        sa.Column("fallback_event_id", sa.UUID(), nullable=False),
        sa.Column("script_version_id", sa.UUID(), nullable=True),
        sa.Column("repaired_version_id", sa.UUID(), nullable=True),
        sa.Column("defect_diagnosis", sa.Text(), nullable=False),
        sa.Column("diff_applied", sa.Text(), nullable=True),
        sa.Column("retry_outcome", repair_retry_outcome, nullable=False),
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
            ["fallback_event_id"], ["fallback_events.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["script_version_id"], ["script_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["repaired_version_id"], ["script_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_repair_attempts_tenant_id", "repair_attempts", ["tenant_id"]
    )
    op.create_index(
        "ix_repair_attempts_fallback_event_id",
        "repair_attempts",
        ["fallback_event_id"],
    )
    op.create_index(
        "ix_repair_attempts_script_version_id",
        "repair_attempts",
        ["script_version_id"],
    )
    op.create_index(
        "ix_repair_attempts_repaired_version_id",
        "repair_attempts",
        ["repaired_version_id"],
    )


def downgrade() -> None:
    # ── Reverse RepairAttempt ──────────────────────────────────────────────
    op.drop_index(
        "ix_repair_attempts_repaired_version_id", table_name="repair_attempts"
    )
    op.drop_index(
        "ix_repair_attempts_script_version_id", table_name="repair_attempts"
    )
    op.drop_index(
        "ix_repair_attempts_fallback_event_id", table_name="repair_attempts"
    )
    op.drop_index("ix_repair_attempts_tenant_id", table_name="repair_attempts")
    op.drop_table("repair_attempts")

    op.drop_constraint(
        "fk_script_versions_repaired_from_id", "script_versions", type_="foreignkey"
    )
    op.drop_column("script_versions", "repaired_from_id")

    # ── Reverse execution-record changes ───────────────────────────────────
    op.drop_column("script_execution_records", "identity_parity_confirmed")
    op.add_column(
        "script_execution_records",
        sa.Column(
            "execution_mode",
            script_execution_mode,
            nullable=False,
            server_default="llm",
        ),
    )

    # ── Re-create ExecutionModeConfiguration ───────────────────────────────
    op.create_table(
        "execution_mode_configurations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=True),
        sa.Column("agent_type_id", sa.UUID(), nullable=False),
        sa.Column("workflow_skill_id", sa.UUID(), nullable=True),
        sa.Column(
            "execution_mode", script_execution_mode, nullable=False,
            server_default="llm",
        ),
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
            ["agent_type_id"], ["agent_types.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "agent_type_id",
            "workflow_skill_id",
            name="uq_execution_mode_config_agent_workflow",
        ),
    )
    op.create_index(
        "ix_execution_mode_configurations_tenant_id",
        "execution_mode_configurations",
        ["tenant_id"],
    )
    op.create_index(
        "ix_execution_mode_configurations_agent_type_id",
        "execution_mode_configurations",
        ["agent_type_id"],
    )
    op.execute("DROP TYPE IF EXISTS repair_retry_outcome_enum")
