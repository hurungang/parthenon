"""FIX-20261031-133253 — in-process registry for conversational-turn HITL resume.

Root cause: the Control Center Assistant (a conversational agent) could
REGISTER a human_intervene request (CH → CC persist + WS dispatch), but the
conversational turn path in ``runtime_executor._execute_conversation_turn``
caught ``GraphInterrupt`` and swallowed it with a canned
"I need more information" message — the deep-agent loop was gone, so an
approval could never resume it and the confirmation-before-write contract
was unenforceable.

Design (mirrors the task-agent resume shape, but in-process):

- When the conversational graph raises ``GraphInterrupt`` (the
  ``LangChainHumanInterveneTool`` called ``interrupt()``), the executor
  registers a pending resume future here, emits ``waiting_for_human``,
  and awaits resolution (bounded by
  ``conversation_intervention_timeout_seconds``).
- The InterveneRequest round-trip is unchanged (CC persists the response
  and calls AR ``POST /internal/resume``); the AR resume endpoint checks
  this registry FIRST and resolves the future with ``response_value``
  instead of relaunching a job execution.
- The executor then re-invokes the SAME agent graph with
  ``Command(resume=response_value)`` on the turn's in-memory checkpointer,
  so the ``interrupt()`` call inside the tool returns the operator's
  response and the loop continues.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

#: conv_session_id → future resolving to the operator's response value.
_pending: dict[uuid.UUID, "asyncio.Future[dict[str, Any]]"] = {}


def is_pending(conv_session_id: uuid.UUID | str) -> bool:
    """Return True when a conversational turn is paused on an intervention."""
    try:
        key = uuid.UUID(str(conv_session_id))
    except (ValueError, TypeError):
        return False
    return key in _pending


def register(conv_session_id: uuid.UUID | str) -> "asyncio.Future[dict[str, Any]]":
    """Register a pending conversational intervention and return its future."""
    key = uuid.UUID(str(conv_session_id))
    loop = asyncio.get_event_loop()
    future: "asyncio.Future[dict[str, Any]]" = loop.create_future()
    _pending[key] = future
    return future


def resolve(conv_session_id: uuid.UUID | str, response_value: dict[str, Any]) -> bool:
    """Resolve a pending conversational intervention with the operator response.

    Returns True when a pending future was found and resolved.
    """
    try:
        key = uuid.UUID(str(conv_session_id))
    except (ValueError, TypeError):
        return False
    future = _pending.pop(key, None)
    if future is None or future.done():
        return False
    future.set_result(response_value or {})
    logger.info(
        "Conversational intervention resolved for session %s (response keys=%s)",
        key, sorted((response_value or {}).keys()),
    )
    return True


def unregister(conv_session_id: uuid.UUID | str) -> None:
    """Drop a pending registration (timeout / cancellation cleanup)."""
    try:
        key = uuid.UUID(str(conv_session_id))
    except (ValueError, TypeError):
        return
    _pending.pop(key, None)


async def wait_for_resume(
    conv_session_id: uuid.UUID | str,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    """Await operator resolution of a pending conversational intervention.

    Registers a future, waits up to ``timeout_seconds``, and returns the
    operator's response value — or ``None`` on timeout (the registration is
    cleaned up either way).
    """
    future = register(conv_session_id)
    try:
        return await asyncio.wait_for(future, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.warning(
            "Conversational intervention wait timed out after %.0fs (session=%s)",
            timeout_seconds, conv_session_id,
        )
        return None
    finally:
        unregister(conv_session_id)
