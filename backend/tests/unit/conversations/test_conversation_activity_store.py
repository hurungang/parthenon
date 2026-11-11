"""Unit tests — ConversationActivityStore upsert / read / terminal-resolution.

Covers the persistent-agent-activity-state change (Control Center is the only
writer of ``conversation_activities``):

- upsert creates the single live row and updates it in place (one row per
  session — the unique-key invariant)
- terminal states stamp ``is_terminal`` / ``finished_at``; non-terminal
  transitions clear them again (heartbeat refresh)
- ``resolve_terminal`` clears the resume checkpoint fields and is a no-op
  (returns None) when the session has no live activity row
- unknown session raises ``LookupError``; non-terminal state passed to
  ``resolve_terminal`` raises ``ValueError``
- the ``ConversationSession.activity`` back-reference resolves
"""
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation_activity import (
    TERMINAL_ACTIVITY_STATES,
    ActivityState,
    ConversationActivity,
)
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.services.conversations.activity_store import ConversationActivityStore


@pytest.fixture
def store() -> ConversationActivityStore:
    return ConversationActivityStore()


async def _make_session(db: AsyncSession) -> ConversationSession:
    session = ConversationSession(status=ConversationStatus.active)
    db.add(session)
    await db.flush()
    return session


class TestActivityStateEnum:
    def test_all_seven_states_present(self):
        assert {s.value for s in ActivityState} == {
            "thinking",
            "using_tool",
            "delegating",
            "waiting_for_human",
            "finished",
            "failed",
            "timed_out",
        }

    def test_terminal_set_is_exactly_the_three_terminal_states(self):
        assert TERMINAL_ACTIVITY_STATES == {
            ActivityState.finished,
            ActivityState.failed,
            ActivityState.timed_out,
        }


class TestUpsert:
    @pytest.mark.asyncio
    async def test_upsert_creates_single_live_row(self, db_session: AsyncSession, store):
        conv = await _make_session(db_session)
        activity = await store.upsert(conv.id, db_session, state=ActivityState.thinking)
        assert activity.id is not None
        assert activity.state == ActivityState.thinking
        assert activity.is_terminal is False

        rows = (
            (
                await db_session.execute(
                    select(ConversationActivity).where(
                        ConversationActivity.conversation_session_id == conv.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_upsert_updates_in_place_on_transitions(self, db_session: AsyncSession, store):
        """thinking → using_tool → delegating must update the SAME row."""
        conv = await _make_session(db_session)
        first = await store.upsert(conv.id, db_session, state=ActivityState.thinking)
        second = await store.upsert(
            conv.id, db_session, state=ActivityState.using_tool, tool_name="cc____list_agents"
        )
        third = await store.upsert(
            conv.id, db_session, state=ActivityState.delegating, target_agent_type_id=uuid.uuid4()
        )

        assert second.id == first.id
        assert third.id == first.id
        assert third.state == ActivityState.delegating
        assert third.tool_name is None  # context cleared on transition away
        assert third.is_terminal is False

    @pytest.mark.asyncio
    async def test_upsert_terminal_stamps_is_terminal_and_finished_at(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        await store.upsert(conv.id, db_session, state=ActivityState.thinking)
        terminal = await store.upsert(conv.id, db_session, state=ActivityState.finished)
        assert terminal.is_terminal is True
        assert terminal.finished_at is not None

    @pytest.mark.asyncio
    async def test_non_terminal_transition_after_terminal_reopens_the_row(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        await store.upsert(conv.id, db_session, state=ActivityState.finished)
        reopened = await store.upsert(conv.id, db_session, state=ActivityState.thinking)
        assert reopened.is_terminal is False
        assert reopened.finished_at is None

    @pytest.mark.asyncio
    async def test_upsert_unknown_session_raises_lookup_error(
        self, db_session: AsyncSession, store
    ):
        with pytest.raises(LookupError):
            await store.upsert(uuid.uuid4(), db_session, state=ActivityState.thinking)

    @pytest.mark.asyncio
    async def test_detail_round_trips_status_only_context(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        activity = await store.upsert(
            conv.id,
            db_session,
            state=ActivityState.using_tool,
            tool_name="cc____list_agents",
            detail={"agent_type": "assistant"},
        )
        assert activity.tool_name == "cc____list_agents"
        assert activity.detail == {"agent_type": "assistant"}
        # No secret material in the persisted record.
        serialized = str(activity.detail) + str(activity.tool_name)
        for forbidden in ("token", "credential", "password", "api_key"):
            assert forbidden not in serialized.lower()


class TestResolveTerminal:
    @pytest.mark.asyncio
    async def test_resolve_terminal_clears_checkpoint_fields(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        turn_id = uuid.uuid4()
        await store.upsert(
            conv.id,
            db_session,
            state=ActivityState.waiting_for_human,
            current_turn_id=turn_id,
            pending_intervene_request_id=uuid.uuid4(),
            tool_name="human_intervene",
            target_agent_type_id=uuid.uuid4(),
        )
        resolved = await store.resolve_terminal(
            conv.id, db_session, state=ActivityState.timed_out
        )
        assert resolved is not None
        assert resolved.state == ActivityState.timed_out
        assert resolved.is_terminal is True
        assert resolved.finished_at is not None
        assert resolved.current_turn_id is None
        assert resolved.pending_intervene_request_id is None
        assert resolved.tool_name is None
        assert resolved.target_agent_type_id is None

    @pytest.mark.asyncio
    async def test_resolve_terminal_returns_none_when_idle(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        assert (
            await store.resolve_terminal(conv.id, db_session, state=ActivityState.finished)
            is None
        )

    @pytest.mark.asyncio
    async def test_resolve_terminal_rejects_non_terminal_state(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        await store.upsert(conv.id, db_session, state=ActivityState.thinking)
        with pytest.raises(ValueError):
            await store.resolve_terminal(conv.id, db_session, state=ActivityState.thinking)


class TestGetAndBackReference:
    @pytest.mark.asyncio
    async def test_get_returns_none_when_idle(self, db_session: AsyncSession, store):
        conv = await _make_session(db_session)
        assert await store.get(conv.id, db_session) is None

    @pytest.mark.asyncio
    async def test_session_back_reference_resolves(self, db_session: AsyncSession, store):
        conv = await _make_session(db_session)
        activity = await store.upsert(conv.id, db_session, state=ActivityState.thinking)
        assert activity.conversation_session_id == conv.id
        # The model declares the bidirectional back-reference.
        assert ConversationSession.activity.property.back_populates == "conversation_session"
