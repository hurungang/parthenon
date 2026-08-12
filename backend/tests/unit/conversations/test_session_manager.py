"""Unit tests for ConversationSessionManager lifecycle transitions."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.agents import AgentInputType
from app.db.models.conversations import ConversationSession, ConversationStatus


def _make_conv_session(
    session_id: uuid.UUID | None = None,
    triggered_by_user_id: uuid.UUID | None = None,
    status: ConversationStatus = ConversationStatus.active,
) -> MagicMock:
    s = MagicMock(spec=ConversationSession)
    s.id = session_id or uuid.uuid4()
    s.triggered_by_user_id = triggered_by_user_id
    s.status = status
    s.agent_type_id = uuid.uuid4()
    return s


def _make_agent_type(input_type: AgentInputType = AgentInputType.conversation) -> MagicMock:
    at = MagicMock()
    at.id = uuid.uuid4()
    at.input_type = input_type
    return at


# ── create ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_rejects_non_conversation_agent_type():
    """create() raises ValueError for agents that are not conversational."""
    from app.services.conversations.manager import ConversationSessionManager

    agent_type = _make_agent_type(input_type=AgentInputType.none)
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=agent_type)

    manager = ConversationSessionManager()
    with pytest.raises(ValueError, match="only conversation agents"):
        await manager.create(
            agent_type_id=agent_type.id,
            triggered_by_user_id=uuid.uuid4(),
            db=mock_db,
        )


@pytest.mark.asyncio
async def test_create_raises_for_missing_agent_type():
    """create() raises ValueError when the agent type does not exist."""
    from app.services.conversations.manager import ConversationSessionManager

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=None)

    manager = ConversationSessionManager()
    with pytest.raises(ValueError, match="not found"):
        await manager.create(
            agent_type_id=uuid.uuid4(),
            triggered_by_user_id=uuid.uuid4(),
            db=mock_db,
        )


@pytest.mark.asyncio
async def test_create_succeeds_for_conversation_agent():
    """create() calls ConversationStore.create_session and returns the new session."""
    from app.services.conversations.manager import ConversationSessionManager

    agent_type = _make_agent_type(input_type=AgentInputType.conversation)
    new_session = _make_conv_session()
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=agent_type)

    manager = ConversationSessionManager()
    with patch("app.services.conversations.manager._store") as mock_store:
        mock_store.create_session = AsyncMock(return_value=new_session)
        result = await manager.create(
            agent_type_id=agent_type.id,
            triggered_by_user_id=uuid.uuid4(),
            db=mock_db,
        )

    assert result is new_session


# ── end ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_end_transitions_status_to_closed():
    """end() delegates to ConversationStore.close_session."""
    from app.services.conversations.manager import ConversationSessionManager

    user_id = uuid.uuid4()
    session = _make_conv_session(triggered_by_user_id=user_id)
    closed_session = _make_conv_session(status=ConversationStatus.closed)
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=session)

    manager = ConversationSessionManager()
    with patch("app.services.conversations.manager._store") as mock_store:
        mock_store.close_session = AsyncMock(return_value=closed_session)
        result = await manager.end(
            session_id=session.id,
            requesting_user_id=user_id,
            db=mock_db,
        )

    mock_store.close_session.assert_awaited_once()
    assert result is closed_session


# ── archive ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_archive_transitions_status_to_archived():
    """archive() delegates to ConversationStore.archive_session."""
    from app.services.conversations.manager import ConversationSessionManager

    user_id = uuid.uuid4()
    session = _make_conv_session(triggered_by_user_id=user_id)
    archived_session = _make_conv_session(status=ConversationStatus.archived)
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=session)

    manager = ConversationSessionManager()
    with patch("app.services.conversations.manager._store") as mock_store:
        mock_store.archive_session = AsyncMock(return_value=archived_session)
        result = await manager.archive(
            session_id=session.id,
            requesting_user_id=user_id,
            db=mock_db,
        )

    mock_store.archive_session.assert_awaited_once()
    assert result is archived_session


# ── resume ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resume_returns_full_turn_history():
    """resume() fetches the session with turns via ConversationStore."""
    from app.services.conversations.manager import ConversationSessionManager

    user_id = uuid.uuid4()
    session_with_turns = _make_conv_session(triggered_by_user_id=user_id)
    session_with_turns.turns = [MagicMock(), MagicMock()]
    mock_db = AsyncMock()

    manager = ConversationSessionManager()
    with patch("app.services.conversations.manager._store") as mock_store:
        mock_store.get_session_with_turns = AsyncMock(return_value=session_with_turns)
        result = await manager.resume(
            session_id=session_with_turns.id,
            requesting_user_id=user_id,
            db=mock_db,
        )

    assert result is session_with_turns
    assert len(result.turns) == 2


# ── ownership validation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ownership_validation_raises_for_mismatched_user():
    """end() raises PermissionError when requesting_user_id does not match session owner."""
    from app.services.conversations.manager import ConversationSessionManager

    owner_id = uuid.uuid4()
    different_user = uuid.uuid4()
    session = _make_conv_session(triggered_by_user_id=owner_id)
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=session)

    manager = ConversationSessionManager()
    with pytest.raises(PermissionError):
        await manager.end(
            session_id=session.id,
            requesting_user_id=different_user,
            db=mock_db,
        )
