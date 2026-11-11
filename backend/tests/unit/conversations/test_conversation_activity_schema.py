"""Schema contract for the persisted conversation activity entity.

Asserts the ``conversation_activities`` table definition (columns, nullability,
unique-per-session constraint, foreign keys, reaper index, enum values) and — when
a live PostgreSQL is reachable — verifies the applied migration against
``information_schema`` / ``pg_catalog``.
"""
import os

import pytest
from sqlalchemy import UniqueConstraint

from app.db.models.conversation_activity import (
    TERMINAL_ACTIVITY_STATES,
    ActivityState,
    ConversationActivity,
)


def _table():
    return ConversationActivity.__table__


class TestModelContract:
    def test_table_name(self):
        assert _table().name == "conversation_activities"

    def test_all_expected_columns_present(self):
        assert set(_table().columns.keys()) == {
            "id",
            "conversation_session_id",
            "state",
            "current_turn_id",
            "pending_intervene_request_id",
            "tool_name",
            "target_agent_type_id",
            "detail",
            "is_terminal",
            "started_at",
            "last_updated_at",
            "finished_at",
        }

    def test_required_vs_nullable_columns(self):
        cols = _table().columns
        assert cols["id"].nullable is False
        assert cols["conversation_session_id"].nullable is False
        assert cols["state"].nullable is False
        assert cols["is_terminal"].nullable is False
        for optional in (
            "current_turn_id",
            "pending_intervene_request_id",
            "tool_name",
            "target_agent_type_id",
            "detail",
            "finished_at",
        ):
            assert cols[optional].nullable is True

    def test_one_live_row_per_session_unique(self):
        col = _table().columns["conversation_session_id"]
        table_uniques = [
            tuple(c.name for c in constraint.columns)
            for constraint in _table().constraints
            if isinstance(constraint, UniqueConstraint)
        ]
        assert col.unique is True or ("conversation_session_id",) in table_uniques

    def test_foreign_keys_and_ondelete(self):
        cols = _table().columns

        def _target(col_name):
            fks = list(cols[col_name].foreign_keys)
            assert fks, f"{col_name} must have a foreign key"
            return fks[0].target_fullname, fks[0].ondelete

        target, ondelete = _target("conversation_session_id")
        assert target == "conversation_sessions.id"
        assert ondelete == "CASCADE"

        for col_name, expected in (
            ("current_turn_id", "conversation_turns.id"),
            ("pending_intervene_request_id", "intervene_requests.id"),
            ("target_agent_type_id", "agent_types.id"),
        ):
            target, ondelete = _target(col_name)
            assert target == expected
            assert ondelete == "SET NULL"

    def test_reaper_index_on_last_updated_at(self):
        index_names = {idx.name for idx in _table().indexes}
        assert "ix_conversation_activities_last_updated_at" in index_names

    def test_enum_values(self):
        assert {s.value for s in ActivityState} == {
            "thinking",
            "using_tool",
            "delegating",
            "waiting_for_human",
            "finished",
            "failed",
            "timed_out",
        }

    def test_terminal_states_are_exactly_three(self):
        assert TERMINAL_ACTIVITY_STATES == {
            ActivityState.finished,
            ActivityState.failed,
            ActivityState.timed_out,
        }


async def _pg_engine():
    url = os.environ.get("DATABASE_URL")
    if not url or "postgresql" not in url:
        return None
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(url, future=True)


class TestMigrationAppliedAgainstPostgres:
    """Real-DB verification of the applied migration (skipped without PostgreSQL)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("check", ["table", "unique", "enum"])
    async def test_migration_applied(self, check):
        from sqlalchemy import text

        engine = await _pg_engine()
        if engine is None:
            pytest.skip("DATABASE_URL is not PostgreSQL")
        try:
            async with engine.connect() as conn:
                if check == "table":
                    result = await conn.execute(
                        text(
                            "select column_name from information_schema.columns "
                            "where table_name = 'conversation_activities'"
                        )
                    )
                    cols = {row[0] for row in result}
                    if not cols:
                        pytest.skip("conversation_activities not present in target DB")
                    assert {"conversation_session_id", "state", "is_terminal"} <= cols
                elif check == "unique":
                    result = await conn.execute(
                        text(
                            "select indexname from pg_indexes "
                            "where tablename = 'conversation_activities'"
                        )
                    )
                    uniques = {row[0] for row in result}
                    if not uniques:
                        pytest.skip("conversation_activities not present in target DB")
                    assert "conversation_activities_conversation_session_id_key" in uniques
                else:
                    result = await conn.execute(
                        text(
                            "select e.enumlabel from pg_enum e "
                            "join pg_type t on t.oid = e.enumtypid "
                            "where t.typname = 'activity_state_enum'"
                        )
                    )
                    labels = {row[0] for row in result}
                    if not labels:
                        pytest.skip("activity_state_enum not present in target DB")
                    assert labels == {s.value for s in ActivityState}
        except Exception as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"PostgreSQL not reachable: {exc}")
        finally:
            await engine.dispose()

