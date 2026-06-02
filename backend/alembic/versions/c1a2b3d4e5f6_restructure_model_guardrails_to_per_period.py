"""restructure_model_guardrails_to_per_period

Phase 3.7 / 3.8 / 3.9: rework to one row per (model, period), add vendor
is_disabled cascade, and add ModelAvailability.

Revision ID: c1a2b3d4e5f6
Revises: b3c9d4e5f6a7
Create Date: 2026-06-01 22:30:00.000000

"""
import json
from collections.abc import Sequence

import sqlalchemy as sa
import uuid
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c1a2b3d4e5f6"
down_revision: str | None = "b3c9d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # ── 1. Enum types ────────────────────────────────────────────────────────
    # The enum types (model_guardrail_period_enum and 
    # model_availability_disabled_reason_enum) are created automatically by
    # SQLAlchemy when the models are imported in env.py. No explicit creation
    # needed here.

    # ── 2. Add vendor is_disabled to model_configs ──────────────────────────
    op.add_column(
        "model_configs",
        sa.Column(
            "is_disabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # ── 3. Restructure model_guardrail_configurations ────────────────────────
    # Drop the four limit columns; add period + limit_value + unique.
    op.add_column(
        "model_guardrail_configurations",
        sa.Column(
            "period",
            postgresql.ENUM(
                "hour", "day", "week", "month",
                name="model_guardrail_period_enum",
                create_type=False,
            ),
            nullable=True,  # populated by backfill below, then set NOT NULL
        ),
    )
    op.add_column(
        "model_guardrail_configurations",
        sa.Column(
            "limit_value",
            sa.Integer(),
            nullable=True,  # populated by backfill below, then set NOT NULL
        ),
    )

    # Backfill: for any existing row, split into per-period rows preserving
    # unit / posture / is_active. Each per-period row takes the limit from
    # the matching usage_limit_<period> column when set; rows whose period
    # had no limit configured are dropped — this matches the new
    # "configure only the periods you want" contract.
    columns = (
        "id",
        "model_id",
        "model_name",
        "unit",
        "enforcement_posture",
        "is_active",
        "details",
        "usage_limit_hour",
        "usage_limit_day",
        "usage_limit_week",
        "usage_limit_month",
        "created_at",
        "updated_at",
    )
    existing_rows = bind.execute(
        sa.text(
            "SELECT id, model_id, model_name, unit, enforcement_posture, is_active, "
            "details, usage_limit_hour, usage_limit_day, usage_limit_week, "
            "usage_limit_month, created_at, updated_at "
            "FROM model_guardrail_configurations"
        )
    ).fetchall()

    for row in existing_rows:
        period_limits = {
            "hour": row.usage_limit_hour,
            "day": row.usage_limit_day,
            "week": row.usage_limit_week,
            "month": row.usage_limit_month,
        }
        # Delete the old row first (cascades to ModelUsagePosture,
        # evaluations, etc.). Posture rollup is recomputed on first refresh.
        bind.execute(
            sa.text("DELETE FROM model_guardrail_configurations WHERE id = :id"),
            {"id": str(row.id)},
        )
        # Insert per-period rows where a limit was configured
        for period_name, limit_val in period_limits.items():
            if limit_val is None:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO model_guardrail_configurations ("
                    "id, model_id, model_name, period, limit_value, unit, "
                    "enforcement_posture, is_active, details, created_at, updated_at"
                    ") VALUES ("
                    ":id, :model_id, :model_name, :period, :limit_value, :unit, "
                    ":enforcement_posture, :is_active, CAST(:details AS jsonb), :created_at, :updated_at"
                    ")"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "model_id": str(row.model_id),
                    "model_name": row.model_name,
                    "period": period_name,
                    "limit_value": int(limit_val),
                    "unit": row.unit,
                    "enforcement_posture": row.enforcement_posture,
                    "is_active": bool(row.is_active),
                    # Existing rows may carry JSON null instead of SQL NULL on
                    # `details` (the JSON literal is distinct from SQL NULL);
                    # coerce to an empty dict and serialize so asyncpg/JSONB
                    # accept the bound parameter. CAST above turns the string
                    # into a JSONB value.
                    "details": json.dumps(row.details if row.details is not None else {}),
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                },
            )

    # Drop the four period-limit columns
    op.drop_column("model_guardrail_configurations", "usage_limit_hour")
    op.drop_column("model_guardrail_configurations", "usage_limit_day")
    op.drop_column("model_guardrail_configurations", "usage_limit_week")
    op.drop_column("model_guardrail_configurations", "usage_limit_month")

    # Enforce NOT NULL on period + limit_value + add unique constraint.
    # Uniqueness is on (model_id, model_name, period) because the same
    # `model_configs` row can host many model_name entries in
    # `enabled_models` (e.g. an OpenAI provider exposing gpt-4o-mini and
    # gpt-4.1-nano).  One guardrail per (vendor, model_name, period).
    op.alter_column(
        "model_guardrail_configurations",
        "period",
        existing_type=sa.Enum(
            "hour", "day", "week", "month",
            name="model_guardrail_period_enum",
            create_type=False,
        ),
        nullable=False,
    )
    op.alter_column(
        "model_guardrail_configurations",
        "limit_value",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_guardrail_vendor_model_period",
        "model_guardrail_configurations",
        ["model_id", "model_name", "period"],
    )

    # ── 4. Create model_availability ─────────────────────────────────────────
    op.create_table(
        "model_availability",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("model_name", sa.String(length=500), nullable=False),
        sa.Column("vendor_model_config_id", sa.UUID(), nullable=False),
        sa.Column("is_disabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "disabled_reason",
            postgresql.ENUM(
                "manual", "vendor_cascaded",
                name="model_availability_disabled_reason_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["vendor_model_config_id"],
            ["model_configs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "vendor_model_config_id",
            "model_name",
            name="uq_availability_vendor_model",
        ),
    )
    op.create_index(
        "ix_model_availability_vendor",
        "model_availability",
        ["vendor_model_config_id"],
    )

    # Backfill ModelAvailability rows for every (vendor, model_name) currently
    # listed in any ModelConfig.enabled_models. Operators expect to see a row
    # to toggle from the start.
    mc_rows = bind.execute(
        sa.text("SELECT id, enabled_models FROM model_configs")
    ).fetchall()
    for mc in mc_rows:
        for model_name in mc.enabled_models or []:
            bind.execute(
                sa.text(
                    "INSERT INTO model_availability ("
                    "id, model_name, vendor_model_config_id, is_disabled, disabled_reason"
                    ") VALUES (:id, :model_name, :vendor_id, false, 'manual')"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "model_name": model_name,
                    "vendor_id": str(mc.id),
                },
            )


def downgrade() -> None:
    bind = op.get_bind()

    # ── 1. Drop model_availability ───────────────────────────────────────────
    op.drop_index("ix_model_availability_vendor", table_name="model_availability")
    op.drop_table("model_availability")
    
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_type WHERE typname = 'model_availability_disabled_reason_enum'"
        )
    )
    if result.scalar() is not None:
        op.execute(
            sa.text("DROP TYPE model_availability_disabled_reason_enum")
        )

    # ── 2. Restore model_guardrail_configurations flat shape ───────────────
    op.add_column(
        "model_guardrail_configurations",
        sa.Column("usage_limit_hour", sa.Integer(), nullable=True),
    )
    op.add_column(
        "model_guardrail_configurations",
        sa.Column("usage_limit_day", sa.Integer(), nullable=True),
    )
    op.add_column(
        "model_guardrail_configurations",
        sa.Column("usage_limit_week", sa.Integer(), nullable=True),
    )
    op.add_column(
        "model_guardrail_configurations",
        sa.Column("usage_limit_month", sa.Integer(), nullable=True),
    )

    # Collapse per-period rows back to one row per model: keep the first row
    # and write its limit into the matching period column, then delete the
    # other rows.
    rows = bind.execute(
        sa.text(
            "SELECT id, model_id, period, limit_value "
            "FROM model_guardrail_configurations ORDER BY model_id, period"
        )
    ).fetchall()
    by_model: dict = {}
    for r in rows:
        by_model.setdefault(r.model_id, []).append(r)
    for model_id, group in by_model.items():
        keep = group[0]
        for r in group[1:]:
            bind.execute(
                sa.text("DELETE FROM model_guardrail_configurations WHERE id = :id"),
                {"id": str(r.id)},
            )
        if keep.period == "hour":
            bind.execute(
                sa.text(
                    "UPDATE model_guardrail_configurations "
                    "SET usage_limit_hour = :limit WHERE id = :id"
                ),
                {"limit": int(keep.limit_value), "id": str(keep.id)},
            )
        elif keep.period == "day":
            bind.execute(
                sa.text(
                    "UPDATE model_guardrail_configurations "
                    "SET usage_limit_day = :limit WHERE id = :id"
                ),
                {"limit": int(keep.limit_value), "id": str(keep.id)},
            )
        elif keep.period == "week":
            bind.execute(
                sa.text(
                    "UPDATE model_guardrail_configurations "
                    "SET usage_limit_week = :limit WHERE id = :id"
                ),
                {"limit": int(keep.limit_value), "id": str(keep.id)},
            )
        elif keep.period == "month":
            bind.execute(
                sa.text(
                    "UPDATE model_guardrail_configurations "
                    "SET usage_limit_month = :limit WHERE id = :id"
                ),
                {"limit": int(keep.limit_value), "id": str(keep.id)},
            )

    op.drop_constraint(
        "uq_guardrail_vendor_model_period",
        "model_guardrail_configurations",
        type_="unique",
    )
    op.drop_column("model_guardrail_configurations", "limit_value")
    op.drop_column("model_guardrail_configurations", "period")
    
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_type WHERE typname = 'model_guardrail_period_enum'"
        )
    )
    if result.scalar() is not None:
        op.execute(
            sa.text("DROP TYPE model_guardrail_period_enum")
        )

    # ── 3. Drop model_configs.is_disabled ────────────────────────────────────
    op.drop_column("model_configs", "is_disabled")
