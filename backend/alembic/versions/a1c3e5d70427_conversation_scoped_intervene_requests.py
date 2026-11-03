"""FIX-20261031-133253 — allow conversation-scoped intervene requests (nullable agent_session_id).

The Control Center Assistant is a conversational agent type: conversation
sessions have no ``agent_jobs`` row, so ``intervene_requests.agent_session_id``
(NOT NULL, FK → agent_jobs.id) made ``human_intervene`` from a conversational
turn impossible (HTTP 404 "Session <conv-id> not found"). Conversation-scoped
requests now carry ``agent_session_id = NULL`` plus the mandatory
``conversation_session_id``, and the resume path keys off the conversation
session id in that case.

Revision ID: a1c3e5d70427
Revises: 6fba31147599
Create Date: 2026-11-01
"""
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c3e5d70427"
down_revision: str | None = "6fba31147599"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL does not support parameterized DDL — plain string statement.
    op.execute(
        "ALTER TABLE intervene_requests ALTER COLUMN agent_session_id DROP NOT NULL"
    )


def downgrade() -> None:
    # Only re-apply NOT NULL when no conversation-scoped rows exist.
    op.execute(
        "ALTER TABLE intervene_requests ALTER COLUMN agent_session_id "
        "SET NOT NULL WHERE agent_session_id IS NOT NULL"
    )
    op.execute(
        "DELETE FROM intervene_requests WHERE agent_session_id IS NULL"
    )
    op.execute(
        "ALTER TABLE intervene_requests ALTER COLUMN agent_session_id SET NOT NULL"
    )
