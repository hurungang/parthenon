"""
Test ResultStore: save() creates a ResultRecord; list_records() queries by agent_type_id.
"""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_result_store_save_calls_db_add():
    """ResultStore.save() adds a ResultRecord via db.add() and returns it."""
    from app.services.results.store import ResultStore
    from app.db.models.results import ResultRecord

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
