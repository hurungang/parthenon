"""Token preflight gate — Communication Hub Agent Gateway execution gate.

Before ANY agent execution is forwarded to Agent Runtime, the Communication
Hub calls the Control Center execution preflight endpoint
(``POST /api/v1/internal/token-health/preflight``) using
:func:`internal_httpx_client` — the ONLY approved internal HTTP client
(signed ``X-Internal-Tenant-*`` headers are auto-forwarded; CH is a
forward-only receiver and never signs).

Outcomes:
- ``blocked``  → execution MUST NOT start; an ``AgentPreflightBlocked``
  exception carries an actionable message naming the identity/session to
  refresh or re-authenticate.
- ``proceed_with_warnings`` → execution starts; the warnings travel with
  the response as user-facing notices.
- ``proceed``  → unchanged behaviour.

Unreachable preflight endpoint ⇒ FAIL CLOSED (raise) — an execution whose
token health cannot be evaluated is never started.

No token material crosses the CH/AR or CH/UI boundary — agents and callers
observe only the outcome and messages.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.internal_http import internal_httpx_client

logger = logging.getLogger(__name__)

PREFLIGHT_ENDPOINT = "/api/v1/internal/token-health/preflight"


class AgentPreflightBlocked(Exception):
    """Raised when the preflight verdict is BLOCKED (execution must not start)."""

    def __init__(self, message: str, blocked: list[str] | None = None) -> None:
        super().__init__(message)
        self.blocked = blocked or [message]


class AgentPreflightUnavailable(Exception):
    """Raised when the preflight endpoint cannot be reached (fail closed)."""


async def run_execution_preflight(
    agent_type_id: uuid.UUID,
    session_id: uuid.UUID | None,
) -> dict[str, Any]:
    """Call the CC preflight endpoint and return the parsed result.

    Raises:
        AgentPreflightUnavailable: if CC is unreachable or errors (fail closed).
    """
    settings = get_settings()
    cc_base = settings.control_center_url or "http://localhost:8000"
    payload: dict[str, Any] = {"agent_type_id": str(agent_type_id)}
    if session_id is not None:
        payload["session_id"] = str(session_id)

    try:
        async with internal_httpx_client(timeout=15.0) as client:
            response = await client.post(f"{cc_base}{PREFLIGHT_ENDPOINT}", json=payload)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Preflight endpoint rejected request (HTTP %d): %s",
            exc.response.status_code,
            exc.response.text[:200],
        )
        raise AgentPreflightUnavailable(
            f"Token preflight failed: HTTP {exc.response.status_code}"
        ) from exc
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Preflight endpoint unreachable: %s", exc)
        raise AgentPreflightUnavailable(
            "Token preflight endpoint unreachable — refusing to start execution"
        ) from exc


async def enforce_execution_preflight(
    agent_type_id: uuid.UUID,
    session_id: uuid.UUID | None,
) -> list[str]:
    """Enforce the preflight gate before starting an execution.

    Returns the list of user-facing warning messages (empty when PROCEED).
    Raises:
        AgentPreflightBlocked: verdict BLOCKED — message names the
            identity/session to refresh or re-authenticate.
        AgentPreflightUnavailable: preflight unreachable (fail closed).
    """
    result = await run_execution_preflight(agent_type_id, session_id)
    verdict = result.get("verdict")
    if verdict == "blocked":
        blocked = result.get("blocked") or []
        message = (
            "Execution blocked: "
            + ("; ".join(blocked) if blocked else "a required token has expired")
        )
        logger.warning(
            "Preflight BLOCKED execution: agent_type=%s session=%s — %s",
            agent_type_id,
            session_id,
            message,
        )
        raise AgentPreflightBlocked(message, blocked=blocked)
    warnings = result.get("warnings") or []
    if warnings:
        logger.info(
            "Preflight WARN for execution: agent_type=%s session=%s — %s",
            agent_type_id,
            session_id,
            "; ".join(warnings),
        )
    return warnings
