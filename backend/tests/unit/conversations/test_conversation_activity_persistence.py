"""Persistence / restart-failover semantics for the conversation activity record.

The persisted activity is the single source of truth, so a *different* store
instance (simulating a new process / a conversation served by another service
instance) must read back exactly what a prior instance wrote.
"""
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation_activity import ActivityState
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.services.conversations.activity_store import ConversationActivityStore


async def _make_session(db: AsyncSession) -> ConversationSession:
    conv = ConversationSession(status=ConversationStatus.active)
    db.add(conv)
    await db.flush()
    return conv


@pytest.mark.asyncio
async def test_activity_survives_store_instance_change(db_session: AsyncSession):
    conv = await _make_session(db_session)
    writer = ConversationActivityStore()
    await writer.upsert(
        conv.id,
        db_session,
        state=ActivityState.using_tool,
        tool_name="cc____list_agents",
    )

    reader = ConversationActivityStore()  # a fresh instance = new process / other instance
    activity = await reader.get(conv.id, db_session)
    assert activity is not None
    assert activity.state == ActivityState.using_tool
    assert activity.tool_name == "cc____list_agents"


@pytest.mark.asyncio
async def test_waiting_for_human_is_readable_on_reconnect(db_session: AsyncSession):
    conv = await _make_session(db_session)
    turn_id = uuid.uuid4()
    intervention_id = uuid.uuid4()
    await ConversationActivityStore().upsert(
        conv.id,
        db_session,
        state=ActivityState.waiting_for_human,
        current_turn_id=turn_id,
        pending_intervene_request_id=intervention_id,
    )

    hydrated = await ConversationActivityStore().get(conv.id, db_session)
    assert hydrated is not None
    assert hydrated.state == ActivityState.waiting_for_human
    assert hydrated.current_turn_id == turn_id
    assert hydrated.pending_intervene_request_id == intervention_id


@pytest.mark.asyncio
async def test_terminal_resolution_is_visible_to_other_instance(db_session: AsyncSession):
    conv = await _make_session(db_session)
    await ConversationActivityStore().upsert(conv.id, db_session, state=ActivityState.thinking)

    await ConversationActivityStore().resolve_terminal(
        conv.id, db_session, state=ActivityState.finished
    )

    hydrated = await ConversationActivityStore().get(conv.id, db_session)
    assert hydrated is not None
    assert hydrated.state == ActivityState.finished
    assert hydrated.is_terminal is True
    assert hydrated.current_turn_id is None


@pytest.mark.asyncio
async def test_activity_is_scoped_per_session(db_session: AsyncSession):
    first = await _make_session(db_session)
    second = await _make_session(db_session)
    store = ConversationActivityStore()
    await store.upsert(first.id, db_session, state=ActivityState.thinking)
    await store.upsert(second.id, db_session, state=ActivityState.delegating)

    assert (await store.get(first.id, db_session)).state == ActivityState.thinking
    assert (await store.get(second.id, db_session)).state == ActivityState.delegating
