"""Unit tests for SessionAutoNamer title generation and write-back."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── generate_and_save ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_and_save_calls_update_title_with_llm_result():
    """generate_and_save() writes the LLM-generated title to the database."""
    from app.services.conversations.auto_namer import SessionAutoNamer

    session_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()
    first_message = "How do I set up a CI pipeline for my project?"
    llm_title = "Setting Up CI Pipeline"

    mock_db = AsyncMock()
    # title=None so generate_and_save proceeds past the early-return check
    mock_db.get = AsyncMock(return_value=MagicMock(model_id="gpt-4o", input_type=None, title=None))
    mock_db.commit = AsyncMock()

    namer = SessionAutoNamer()

    with (
        patch.object(namer, "_try_generate_via_llm", new=AsyncMock(return_value=llm_title)),
        patch("app.services.conversations.auto_namer._store") as mock_store,
    ):
        mock_store.update_title = AsyncMock(return_value=MagicMock())
        result = await namer.generate_and_save(
            session_id=session_id,
            first_user_message=first_message,
            agent_type_id=agent_type_id,
            db=mock_db,
        )

    mock_store.update_title.assert_awaited_once_with(session_id, llm_title, mock_db)
    assert result == llm_title


@pytest.mark.asyncio
async def test_generate_and_save_falls_back_when_llm_raises():
    """generate_and_save() uses a truncated first message if the LLM fails."""
    from app.services.conversations.auto_namer import SessionAutoNamer

    session_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()
    first_message = "Short message"

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=None)  # no existing session → proceed to generate
    mock_db.commit = AsyncMock()

    namer = SessionAutoNamer()

    with (
        patch.object(namer, "_try_generate_via_llm", new=AsyncMock(return_value=None)),
        patch("app.services.conversations.auto_namer._store") as mock_store,
    ):
        mock_store.update_title = AsyncMock(return_value=MagicMock())
        result = await namer.generate_and_save(
            session_id=session_id,
            first_user_message=first_message,
            agent_type_id=agent_type_id,
            db=mock_db,
        )

    # Fallback title should be the first message (it's short)
    assert result == first_message
    mock_store.update_title.assert_awaited_once_with(session_id, first_message, mock_db)


@pytest.mark.asyncio
async def test_fallback_truncates_long_message():
    """_fallback_title() truncates messages longer than 60 chars."""
    from app.services.conversations.auto_namer import SessionAutoNamer

    long_message = "x" * 100
    namer = SessionAutoNamer()
    title = namer._fallback_title(long_message)

    assert len(title) <= 63  # 60 chars + ellipsis
    assert title.endswith("…")


@pytest.mark.asyncio
async def test_empty_llm_response_produces_fallback_title():
    """When the LLM returns an empty string, a non-empty fallback title is used."""
    from app.services.conversations.auto_namer import SessionAutoNamer

    session_id = uuid.uuid4()
    first_message = "Hello agent, can you help me?"

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=None)  # no existing session → proceed to generate
    mock_db.commit = AsyncMock()

    namer = SessionAutoNamer()

    with (
        patch.object(namer, "_try_generate_via_llm", new=AsyncMock(return_value=None)),
        patch("app.services.conversations.auto_namer._store") as mock_store,
    ):
        mock_store.update_title = AsyncMock(return_value=MagicMock())
        result = await namer.generate_and_save(
            session_id=session_id,
            first_user_message=first_message,
            agent_type_id=None,
            db=mock_db,
        )

    assert result  # Non-empty
    assert result == first_message
