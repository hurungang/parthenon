"""Conversation session end-time termination (FIX-20261031-091657, Defect B).

``POST /conversations/{id}/end`` previously only flipped the session's DB
status — any in-flight agent execution bound to that session kept running (a
hung/slow turn would run to its own eventual failure). This helper reuses the
existing termination machinery (Control Center → Communication Hub
``/internal/agent/terminate/{id}`` → Agent Runtime ``/terminate/{id}``) so the
CH-side pending turn task and the AR-side conversation task are cancelled.

Strictly best-effort and logged: a termination failure must never fail the
end call — the session is already closed by the time this runs.
"""
from __future__ import annotations

import logging
import uuid

from app.core.tenant_context import get_current_tenant_context
from app.services.control_center.agent_runtime_client import AgentRuntimeClient

logger = logging.getLogger(__name__)


def _get_agent_runtime_client() -> AgentRuntimeClient:
    """Build an AgentRuntimeClient (Communication Hub control-plane caller)."""
    from app.core.config import get_settings

    settings = get_settings()
    return AgentRuntimeClient(
        communication_hub_url=settings.communication_hub_url,
    )


async def terminate_in_flight_conversation_execution(
    session_id: uuid.UUID,
    reason: str = "conversation session ended by user",
) -> dict | None:
    """Best-effort termination of any in-flight execution for ``session_id``.

    Routes through Communication Hub, which first cancels the CH-side pending
    conversational turn task and then forwards to Agent Runtime, whose
    ``/terminate/{session_id}`` also cancels in-flight conversation turn
    tasks (FIX-20261031-091657).

    Returns the termination response dict, or None when nothing was in
    flight or the call failed (logged, never raised).
    """
    tenant_context = get_current_tenant_context()
    try:
        client = _get_agent_runtime_client()
        result = await client.terminate_session(
            session_id=session_id,
            reason=reason,
            tenant_context=tenant_context,
        )
        if result is not None:
            logger.info(
                "In-flight conversation execution terminated for session %s: %s",
                session_id,
                result,
            )
        else:
            logger.info(
                "No in-flight execution to terminate for conversation session %s",
                session_id,
            )
        return result
    except Exception as exc:  # noqa: BLE001 — strictly best-effort
        logger.warning(
            "Best-effort termination failed for conversation session %s: %s",
            session_id,
            exc,
        )
        return None
