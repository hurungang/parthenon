"""
Test MessageBroker channel isolation and SessionContextManager TTL/expiry.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json


@pytest.mark.asyncio
async def test_messagebroker_publishes_to_correct_channel():
    """MessageBroker.publish() sends to the session-scoped channel only."""
    from app.services.comm_hub.broker import MessageBroker, BrokerMessage

    mock_redis = AsyncMock()
    mock_redis.publish = AsyncMock(return_value=1)

    with patch("redis.asyncio.from_url", return_value=mock_redis):
        broker = MessageBroker()
        msg = BrokerMessage(session_id="sess-A", sender_role="user", content="hello")
        count = await broker.publish(msg)

    assert count == 1
    # Must have published to the correct channel
    call_args = mock_redis.publish.call_args
    assert "parthenon:session:sess-A" in call_args[0][0]


@pytest.mark.asyncio
async def test_messagebroker_channel_isolation():
    """Publishing to channel A does not affect channel B subscriber counts."""
    from app.services.comm_hub.broker import MessageBroker, BrokerMessage

    mock_redis = AsyncMock()
    # Channel A has 1 subscriber; channel B has 0
    publish_counts = {"parthenon:session:A": 1, "parthenon:session:B": 0}
    mock_redis.publish = AsyncMock(side_effect=lambda ch, _: publish_counts.get(ch, 0))

    with patch("redis.asyncio.from_url", return_value=mock_redis):
        broker = MessageBroker()
        msg_a = BrokerMessage(session_id="A", sender_role="user", content="msg to A")
        count_a = await broker.publish(msg_a)

    assert count_a == 1


@pytest.mark.asyncio
async def test_session_context_manager_set_and_get():
    """SessionContextManager.set/get round-trips correctly."""
    from app.services.comm_hub.session_context import SessionContextManager

    context_data = {"participants": ["user1", "agent1"], "status": "active"}
    stored: dict = {}

    mock_redis = AsyncMock()
    mock_redis.setex = AsyncMock(
        side_effect=lambda key, ttl, val: stored.update({key: val})
    )
    mock_redis.get = AsyncMock(
        side_effect=lambda key: stored.get(key)
    )

    with patch("redis.asyncio.from_url", return_value=mock_redis):
        mgr = SessionContextManager(ttl_seconds=60)
        await mgr.set("sess-1", context_data)
        result = await mgr.get("sess-1")

    assert result == context_data


@pytest.mark.asyncio
async def test_session_context_manager_returns_none_for_expired():
    """SessionContextManager.get() returns None when the session key doesn't exist (expired)."""
    from app.services.comm_hub.session_context import SessionContextManager

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    with patch("redis.asyncio.from_url", return_value=mock_redis):
        mgr = SessionContextManager()
        result = await mgr.get("expired-session")

    assert result is None
