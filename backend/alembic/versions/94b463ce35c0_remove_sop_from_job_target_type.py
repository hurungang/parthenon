"""remove_sop_from_job_target_type

Revision ID: 94b463ce35c0
Revises: 7fa64c41714b
Create Date: 2026-06-08 20:55:11.841298

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '94b463ce35c0'
down_revision: str | None = '7fa64c41714b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ENUM = "job_target_type_enum"
NEW_ENUM = "job_target_type_enum_v2"
COLUMNS = [("scheduled_jobs", "target_type")]


def upgrade() -> None:
    # Migrate any existing 'sop' rows to 'agent'
    op.execute("UPDATE scheduled_jobs SET target_type = 'agent' WHERE target_type = 'sop'")

    # Create new enum type without 'sop'
    op.execute(f"CREATE TYPE {NEW_ENUM} AS ENUM ('agent')")

    # Update columns to use new type via text cast
    for table, col in COLUMNS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE {NEW_ENUM} USING {col}::text::{NEW_ENUM}")

    # Drop old enum and rename new one
    op.execute(f"DROP TYPE {OLD_ENUM}")
    op.execute(f"ALTER TYPE {NEW_ENUM} RENAME TO {OLD_ENUM}")


def downgrade() -> None:
    # Create old enum type with both values
    op.execute(f"CREATE TYPE {NEW_ENUM} AS ENUM ('agent', 'sop')")

    # Update columns to use old type
    for table, col in COLUMNS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE {NEW_ENUM} USING {col}::text::{NEW_ENUM}")

    # Drop new enum and rename old one
    op.execute(f"DROP TYPE {OLD_ENUM}")
    op.execute(f"ALTER TYPE {NEW_ENUM} RENAME TO {OLD_ENUM}")
