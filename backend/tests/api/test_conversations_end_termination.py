"""FIX-20261031-091657 (Defect B.1) — ending a conversation session terminates
any in-flight agent execution bound to that session (best-effort through the
existing CC → CH → AR termination machinery) and never fails the end call.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.conversations.termination import terminate_in_flight_conversation_execution


@pytest.mark.asyncio
async def test_end_termination_forwards_through_agent_runtime_client() -> None:
    session_id = uuid.uuid4()
    fake_client = SimpleNamespace()
    fake_client.terminate_session = AsyncMock(return_value={"cancelled": True})

    with patch(
        "app.services.conversations.termination._get_agent_runtime_client",
        return_value=fake_client,
    ):
        result = await terminate_in_flight_conversation_execution(session_id)

    fake_client.terminate_session.assert_awaited_once()
    assert result is not None


@pytest.mark.asyncio
async def test_end_termination_is_silent_best_effort_on_failure() -> None:
    session_id = uuid.uuid4()
    fake_client = SimpleNamespace()
    fake_client.terminate_session = AsyncMock(side_effect=RuntimeError("CH down"))

    with patch(
        "app.services.conversations.termination._get_agent_runtime_client",
        return_value=fake_client,
    ):
        # Must not raise — ending a session must never fail because of this.
        result = await terminate_in_flight_conversation_execution(session_id)

    assert result is None
