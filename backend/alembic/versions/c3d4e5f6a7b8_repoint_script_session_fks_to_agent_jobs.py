"""Repoint script session FKs from conversation_sessions to agent_jobs.

Agent executions are AgentJob rows; conversational agents are never compiled,
so the script registry's session references were pointing at the wrong table —
every auto-compiled candidate from a real agent run failed the foreign key.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-18
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None

# Postgres default constraint naming: <table>_<column>_fkey (the original
# FKs were created unnamed in migration a1b2c3d4f5e6).
_REPOINTS = [
    ("script_definitions", "source_session_id"),
    ("verification_runs", "reference_execution_id"),
    ("script_execution_records", "session_id"),
]


def upgrade() -> None:
    for table, column in _REPOINTS:
        op.drop_constraint(f"{table}_{column}_fkey", table, type_="foreignkey")
        op.create_foreign_key(
            f"{table}_{column}_fkey", table, "agent_jobs", [column], ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for table, column in _REPOINTS:
        op.drop_constraint(f"{table}_{column}_fkey", table, type_="foreignkey")
        op.create_foreign_key(
            f"{table}_{column}_fkey", table, "conversation_sessions", [column], ["id"],
            ondelete="SET NULL",
        )
