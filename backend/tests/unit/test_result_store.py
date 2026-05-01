"""
Test ResultStore: save() creates a ResultRecord; list_records() queries by agent_type_id.
Also verifies get_mcp_tool_definition() returns a valid MCP tool schema.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_result_store_save_calls_db_add():
    """ResultStore.save() adds a ResultRecord via db.add() and returns it."""
    from app.db.models.results import ResultRecord
    from app.services.results.store import ResultStore

    record = MagicMock(spec=ResultRecord)
    record.id = uuid.uuid4()

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()

    with patch("app.services.results.store.ResultRecord", return_value=record):
        store = ResultStore()
        result = await store.save(payload={"key": "value"}, db=mock_db, title="My Result")

    mock_db.add.assert_called_once_with(record)
    assert result is record


@pytest.mark.asyncio
async def test_result_store_handle_mcp_call():
    """ResultStore.handle_mcp_call() saves the result and returns result_id."""
    from app.db.models.results import ResultRecord
    from app.services.results.store import ResultStore

    record = MagicMock(spec=ResultRecord)
    record.id = uuid.uuid4()

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()

    with patch("app.services.results.store.ResultRecord", return_value=record):
        store = ResultStore()
        response = await store.handle_mcp_call(
            arguments={"payload": {"answer": 42}, "title": "Test"},
            db=mock_db,
        )

    assert response["saved"] is True
    assert "result_id" in response


def test_result_store_mcp_tool_definition():
    """ResultStore.get_mcp_tool_definition() returns valid MCP tool schema."""
    from app.services.results.store import ResultStore

    store = ResultStore()
    definition = store.get_mcp_tool_definition()

    assert definition["name"] == "save_result"
    assert "inputSchema" in definition
    assert "payload" in definition["inputSchema"]["properties"]
