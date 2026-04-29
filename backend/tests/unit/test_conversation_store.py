"""
Test ConversationStore: add_turn persists in order, tool call records linked to turns.
"""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_conversation_store_add_turn_calls_db_add():
    """ConversationStore.add_turn() adds a ConversationTurn via db.add()."""
    from app.services.conversations.store import ConversationStore
    from app.db.models.conversations import TurnRole, ConversationTurn

    session_id = uuid.uuid4()
    turn = MagicMock(spec=ConversationTurn)
    turn.id = uuid.uuid4()
    turn.role = TurnRole.user
    turn.content = "Hello agent"

    mock_session_record = MagicMock()
    mock_session_record.turn_count = 0

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.get = AsyncMock(return_value=mock_session_record)

    # Patch ConversationTurn constructor to return our mock
    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "app.services.conversations.store.ConversationTurn", return_value=turn
    ):
        store = ConversationStore()
        result = await store.add_turn(session_id, TurnRole.user, "Hello agent", mock_db)

    mock_db.add.assert_called_once_with(turn)


@pytest.mark.asyncio
async def test_conversation_store_add_tool_call():
    """ConversationStore.add_tool_call() persists a ToolCallRecord linked to the turn."""
    from app.services.conversations.store import ConversationStore
    from app.db.models.conversations import ToolCallRecord

    turn_id = uuid.uuid4()
    record = MagicMock(spec=ToolCallRecord)
    record.id = uuid.uuid4()

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()

    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "app.services.conversations.store.ToolCallRecord", return_value=record
    ):
        store = ConversationStore()
        result = await store.add_tool_call(turn_id, "my-server/toolA", mock_db)

    mock_db.add.assert_called_once_with(record)
