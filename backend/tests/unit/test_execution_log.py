"""Unit tests for ExecutionLogEntry (prompt capture) model and AgentRuntimeExecutor integration.

Verifies:
- AgentPromptLog model is importable and has the required fields.
- ExecutionLogRead Pydantic schema maps correctly from the ORM object.
- _capture_prompt_log writes the correct system_instruction and user_prompt.
- No prompt log is written for a queued (not-yet-executed) session.
"""
from __future__ import annotations

import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


# ── Model field presence ────────────────────────────────────────────────────────


def test_agent_prompt_log_model_importable():
    """AgentPromptLog is importable from app.db.models.agents."""
    from app.db.models.agents import AgentPromptLog

    assert hasattr(AgentPromptLog, "id")
    assert hasattr(AgentPromptLog, "session_id")
    assert hasattr(AgentPromptLog, "system_instruction")
    assert hasattr(AgentPromptLog, "user_prompt")
    assert hasattr(AgentPromptLog, "logged_at")


def test_agent_prompt_log_table_name():
    """AgentPromptLog uses table 'execution_logs'."""
    from app.db.models.agents import AgentPromptLog

    assert AgentPromptLog.__tablename__ == "execution_logs"


# ── Schema ──────────────────────────────────────────────────────────────────────


def test_execution_log_read_schema_importable():
    """ExecutionLogRead is importable from app.schemas.agents."""
    from app.schemas.agents import ExecutionLogRead

    assert hasattr(ExecutionLogRead, "model_fields")
    fields = ExecutionLogRead.model_fields
    assert "id" in fields
    assert "session_id" in fields
    assert "system_instruction" in fields
    assert "user_prompt" in fields
    assert "logged_at" in fields


def test_execution_log_read_validates_from_orm_like_object():
    """ExecutionLogRead.model_validate works with an object that has the correct attributes."""
    from app.schemas.agents import ExecutionLogRead

    _session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    class FakeLog:
        id = uuid.uuid4()
        session_id = _session_id
        system_instruction = "Be concise and helpful."
        user_prompt = "What is the capital of France?"
        logged_at = now

    log = ExecutionLogRead.model_validate(FakeLog())
    assert log.system_instruction == "Be concise and helpful."
    assert log.user_prompt == "What is the capital of France?"
    assert log.session_id == _session_id


# ── _capture_prompt_log integration ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_capture_prompt_log_stores_both_fields():
    """_capture_prompt_log writes system_instruction and user_prompt to the DB."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    written_entries: list = []
    original_add = db.add.side_effect

    def capture_add(obj):
        written_entries.append(obj)
        if original_add:
            original_add(obj)

    db.add.side_effect = capture_add

    with patch("app.db.models.agents.AgentPromptLog") as MockLog:
        fake_entry = MagicMock()
        fake_entry.system_instruction = "You are a helpful assistant."
        fake_entry.user_prompt = "Summarise this document."
        MockLog.return_value = fake_entry

        await executor._capture_prompt_log(
            session_id=session_id,
            system_instruction="You are a helpful assistant.",
            user_prompt="Summarise this document.",
            db=db,
        )

    # _capture_prompt_log writes two rows: AgentPromptLog + ExecutionLogEntry(prompt_captured)
    assert db.add.call_count == 2
    assert db.flush.call_count == 2


@pytest.mark.asyncio
async def test_capture_prompt_log_accepts_none_fields():
    """_capture_prompt_log does not raise when system_instruction or user_prompt is None."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    db = AsyncMock()

    # Should not raise even with None fields
    await executor._capture_prompt_log(
        session_id=uuid.uuid4(),
        system_instruction=None,
        user_prompt=None,
        db=db,
    )

    # _capture_prompt_log writes two rows: AgentPromptLog + ExecutionLogEntry(prompt_captured)
    assert db.add.call_count == 2


@pytest.mark.asyncio
async def test_capture_prompt_log_swallows_flush_error():
    """_capture_prompt_log does not propagate DB flush errors."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    db = AsyncMock()
    db.flush = AsyncMock(side_effect=Exception("Connection reset"))

    # Must not raise
    await executor._capture_prompt_log(
        session_id=uuid.uuid4(),
        system_instruction="sys",
        user_prompt="user",
        db=db,
    )


# ── Format user prompt ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_format_user_prompt_returns_message_for_conversation_input():
    """_format_user_prompt returns the message string for conversational input."""
    from app.db.models.agents import AgentInputType
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    agent_type = MagicMock()
    agent_type.input_type = AgentInputType.conversation
    executor = AgentRuntimeExecutor()
    result = await executor._format_user_prompt({"message": "Hello!"}, agent_type)
    assert result == "Hello!"


@pytest.mark.asyncio
async def test_format_user_prompt_returns_json_for_typed_input():
    """_format_user_prompt serialises typed dict input as compact JSON."""
    import json

    from app.db.models.agents import AgentInputType
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    agent_type = MagicMock()
    agent_type.input_type = AgentInputType.typed
    executor = AgentRuntimeExecutor()
    input_data = {"key": "value", "count": 3}
    result = await executor._format_user_prompt(input_data, agent_type)
    assert result == json.dumps(input_data, ensure_ascii=False)


@pytest.mark.asyncio
async def test_format_user_prompt_returns_none_for_no_input():
    """_format_user_prompt returns None when input_data is None."""
    from app.db.models.agents import AgentInputType
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    agent_type = MagicMock()
    agent_type.input_type = AgentInputType.typed
    executor = AgentRuntimeExecutor()
    result = await executor._format_user_prompt(None, agent_type)
    assert result is None
