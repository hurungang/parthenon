"""Round two: decision tool data types.

Replace the inline input/output JSON schema columns on ``decision_tools``
with nullable FK references to ``agent_data_types`` (``input_data_type_id``
/ ``output_data_type_id``). Referenced data types are protected from
deletion at the service layer; the FK uses RESTRICT as a DB-level backstop.

Revision ID: d5e6a7b8c9d0
Revises: c3f7a1d92e40
Create Date: 2026-10-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "d5e6a7b8c9d0"
down_revision = "c3f7a1d92e40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "decision_tools",
        sa.Column(
            "input_data_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_data_types.id", ondelete="RESTRICT"),
            nullable=True,
            comment="Input contract: AgentDataType reference (nullable — state-only tools)",
        ),
    )
    op.add_column(
        "decision_tools",
        sa.Column(
            "output_data_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_data_types.id", ondelete="RESTRICT"),
            nullable=True,
            comment="Output contract: AgentDataType reference (nullable)",
        ),
    )
    op.drop_column("decision_tools", "input_schema")
    op.drop_column("decision_tools", "output_schema")


def downgrade() -> None:
    op.add_column(
        "decision_tools",
        sa.Column(
            "output_schema",
            sa.JSON(),
            nullable=True,
            comment="Structured output schema (system-tool aligned)",
        ),
    )
    op.add_column(
        "decision_tools",
        sa.Column(
            "input_schema",
            sa.JSON(),
            nullable=True,
            comment="Structured input schema (system-tool aligned)",
        ),
    )
    op.drop_column("decision_tools", "output_data_type_id")
    op.drop_column("decision_tools", "input_data_type_id")
