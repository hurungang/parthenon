"""FIX-20261031-133253 — in-process registry for conversational-turn HITL resume.

.. deprecated:: resumable-agent-turn-persistence
   Paused conversational turns are now durably resumable: the pause point is a
   Control Center–owned LangGraph checkpoint loaded by
   :mod:`app.agent_runtime.durable_checkpointer`, and resume is
   ``Command(resume=…)`` after a claim (see
   :mod:`app.agent_runtime.turn_resume_service`).  Nothing in the durable path
   awaits an in-process future.

   This module survives only as a compatibility shim: the Agent Runtime
   executor uses it **solely** when the Communication Hub checkpoint relay is
   not deployed (the pre-Phase-4 rollout window), and the legacy
   ``/internal/resume`` route consults it only for such an in-process pause.
   New code must not depend on it.

Original design notes (kept for context):

- When the conversational graph raised ``GraphInterrupt`` the executor
  registered a pending future here and awaited the operator response.
- The AR ``/internal/resume`` route resolved the future instead of relaunching
  a job execution.
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
