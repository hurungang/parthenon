"""Test that _wait_for_receiver_result extends the deadline when the sub-agent is waiting for human input.

Verifies the fix for the conversational human-in-the-loop timeout issue:
  1. When session status is 'waiting_for_human', the deadline is extended so the poll loop keeps
     waiting past the original timeout.
  2. When the async generator subscription is killed by asyncio.wait_for cancellation
     (Python >= 3.11), the function resubscribes rather than returning a premature timeout.
  3. Without a data_client, the function still works (no extensions, no crashes).
"""
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.communication_hub.api import a2a as a2a_module
from app.services.comm_hub.broker import BrokerMessage


# ── Stub brokers ────────────────────────────────────────────────────────────────

class _IdleBroker:
    """Broker that never delivers a message — forces timeout."""
    async def subscribe(self, session_id: str):
        while True:
            await asyncio.sleep(60)
            yield BrokerMessage(
                session_id=session_id,
                sender_role="agent",
                content="{}",
                metadata={"message_type": "agent_result"},
            )


class _DelayedResultBroker:
    """Broker that delivers a completed result after a fixed delay from first subscription.

    Designed to survive asyncio.wait_for cancellation: when a poll times out the
    generator is killed, but a fresh call to ``subscribe()`` on the same instance
    creates a new generator that checks the original start time, so the message
    is eventually delivered on a subsequent poll.
    """
    def __init__(self, delivery_delay: float):
        self._delivery_delay = delivery_delay
        self._first_subscribe_time: float | None = None

    async def subscribe(self, session_id: str):
        if self._first_subscribe_time is None:
            self._first_subscribe_time = asyncio.get_running_loop().time()

        while True:
            elapsed = asyncio.get_running_loop().time() - self._first_subscribe_time
            if elapsed >= self._delivery_delay:
                yield BrokerMessage(
                    session_id=session_id,
                    sender_role="agent",
                    content='{"status":"completed","output_data":{"result":"hitl_ok"}}',
                    metadata={"message_type": "agent_result"},
                )
                # After delivery, idle forever (function will have returned by now).
                await asyncio.sleep(3600)
            else:
                # Yield to the event loop so other coroutines can run.
                await asyncio.sleep(0.05)


# ── Helpers ──────────────────────────────────────────────────────────────────────

class _SequencedDataClient:
    """Mock data_client that returns statuses from a predefined sequence.

    Each call to ``get_session()`` advances to the next status.  Once the
    sequence is exhausted the last value is returned on every subsequent call.
    """
    def __init__(self, statuses: list[str]) -> None:
        self._statuses = statuses
        self._idx = 0
        self.call_count = 0

    async def get_session(self, _session_id):
        i = min(self._idx, len(self._statuses) - 1)
        self._idx += 1
        self.call_count += 1
        return {"status": self._statuses[i]}


# ── Tests ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deadline_extended_when_waiting_for_human() -> None:
    """When session status is 'waiting_for_human', the deadline is extended.

    Uses a short poll window (5 s) and a delivery delay (7 s) that straddles two
    poll intervals.  Without deadline extension the function would time out after
    the first poll; with the fix it resubscribes on generator cancellation and
    captures the result on the second poll.
    """
    receiver_session_id = uuid.uuid4()

    # data_client always reports waiting_for_human.
    data_client = MagicMock()
    data_client.get_session = AsyncMock(
        return_value={"status": "waiting_for_human"}
    )

    # Broker delivers the result after 7 s — after the first 5 s poll times out.
    broker = _DelayedResultBroker(delivery_delay=7.0)

    result = await a2a_module._wait_for_receiver_result(
        receiver_session_id=receiver_session_id,
        timeout_seconds=6.0,
        broker=broker,
        data_client=data_client,
    )

    assert result == {
        "status": "completed",
        "output_data": {"result": "hitl_ok"},
    }
    # data_client.get_session should have been called at least once (status check).
    assert data_client.get_session.await_count >= 1


@pytest.mark.asyncio
async def test_deadline_not_extended_when_running() -> None:
    """When session status is 'running', the deadline is NOT extended.

    The original 2 s timeout should fire, returning a timeout result quickly.
    """
    receiver_session_id = uuid.uuid4()

    # data_client reports 'running' (not waiting_for_human).
    data_client = MagicMock()
    data_client.get_session = AsyncMock(
        return_value={"status": "running"}
    )

    # Idle broker — never delivers a result.
    broker = _IdleBroker()

    result = await a2a_module._wait_for_receiver_result(
        receiver_session_id=receiver_session_id,
        timeout_seconds=2.0,
        broker=broker,
        data_client=data_client,
    )

    assert result == {
        "status": "timeout",
        "error": "Timed out waiting for receiver response",
    }


@pytest.mark.asyncio
async def test_no_extension_without_data_client() -> None:
    """When data_client is None, the function works without extensions or crashes.

    An idle broker + short timeout should return a clean timeout result.
    """
    receiver_session_id = uuid.uuid4()

    result = await a2a_module._wait_for_receiver_result(
        receiver_session_id=receiver_session_id,
        timeout_seconds=0.5,
        broker=_IdleBroker(),
        data_client=None,
    )

    assert result == {
        "status": "timeout",
        "error": "Timed out waiting for receiver response",
    }


@pytest.mark.asyncio
async def test_result_received_after_human_intervention_resume() -> None:
    r"""Verify that _wait_for_receiver_result returns the sub-agent's result after
    the session transitions through **waiting_for_human → running → completed**.

    Simulates the full conversational HITL lifecycle:

    1. Sub-agent starts running (status: ``running``).
    2. Sub-agent calls ``human_intervene`` → status: ``waiting_for_human``
       (the deadline is *not* extended, but the timeout check is bypassed while
       ``is_waiting`` is True).
    3. Human responds → sub-agent resumes → status: ``running``.
    4. Sub-agent finishes → status: ``completed`` + result published to Redis.

    **Bug #1 ― Deadline never extended after HITL resume** (lines 36-68 of
    ``a2a.py``):  ``deadline`` is set once at the top of the function and
    *never* updated.  While the session is ``waiting_for_human`` the
    ``is_waiting`` flag merely *bypasses* the expiry check — it does **not**
    push the deadline forward.  When the session transitions back to
    ``running`` (step 3), ``is_waiting`` becomes ``False`` and the original
    deadline (which may already be in the past) triggers an immediate timeout.

    **Bug #2 ― Premature "expired" on completed/failed/terminated status**
    (lines 55-59):  The status check runs *before* the Redis message poll.  If
    the session status changes to ``completed`` before the result message is
    consumed from Redis, the function returns ``"expired"`` without ever
    reading the result.  This is a race condition between the DB status
    update and the Redis pub/sub delivery.

    **This test targets Bug #1.**  A short timeout (5 s) ensures the deadline
    expires while the session is ``waiting_for_human``.  The broker is
    configured to deliver the completed result at T=12 s — well after the
    original deadline but early enough that a properly-extended deadline would
    still capture it.  With the bug, the function returns ``"timeout"`` at
    ≈T=10 s (status "running" after resume); with the fix it should return
    ``"completed"`` with the broker's output data.

    Expected (after fix):   ``{"status": "completed", "output_data": {"result": "hitl_resume_ok"}}``
    Actual (with bug):      ``{"status": "timeout", "error": "Timed out waiting for receiver response"}``
    """
    receiver_session_id = uuid.uuid4()

    # ── Arrange: data_client that replays the HITL lifecycle ─────────────────
    status_sequence = ["running", "waiting_for_human", "running", "completed"]
    data_client = _SequencedDataClient(status_sequence)

    # ── Arrange: broker delivers *after* the Bug #1 timeout would fire ──────
    # The function returns at ≈T=10 s due to Bug #1.  Delivering at 12 s
    # ensures the result is available IF the deadline had been extended.
    broker = _DelayedResultBroker(delivery_delay=12.0)

    # ── Act ─────────────────────────────────────────────────────────────────
    result = await a2a_module._wait_for_receiver_result(
        receiver_session_id=receiver_session_id,
        timeout_seconds=5.0,
        broker=broker,
        data_client=data_client,
    )

    # ── Assert ───────────────────────────────────────────────────────────────
    # With Bug #1: result == {"status": "timeout", "error": "..."}
    # After fix:   result == {"status": "completed", "output_data": {"result": "hitl_ok"}}
    assert result == {
        "status": "completed",
        "output_data": {"result": "hitl_ok"},
    }, (
        f"Expected completed result after HITL resume, got: {result}. "
        f"This is Bug #1: deadline was never extended when session transitioned "
        f"from 'waiting_for_human' back to 'running'. "
        f"data_client.get_session was called {data_client.call_count} time(s)."
    )

    # Verify the data_client traversed at least the first 3 status values
    # (running → waiting_for_human → running) before the function returned.
    assert data_client.call_count >= 3, (
        f"Expected at least 3 status checks (running→waiting_for_human→running), "
        f"got {data_client.call_count}"
    )
