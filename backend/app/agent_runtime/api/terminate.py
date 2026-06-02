"""Agent Runtime — Session Termination Endpoint.

Allows the Control Center to cancel an in-flight session's background
task.  The runtime keeps a ``session_id → asyncio.Task`` map on
``app.state.session_tasks`` (populated by ``/execute``); this endpoint
looks up the task for the given session and cancels it.

Route: POST /terminate/{session_id}

Security:
    ControlCenterCertificateMiddleware is applied globally in AR main.py and
    rejects any request whose inbound TLS certificate is not
    ``service:control-center`` before this handler runs.

Phase 3.11: closes the cross-process termination gap exposed when an
operator hits "Terminate" in the UI but the agent kept running because
no one was telling the Agent Runtime to stop the in-memory task.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

terminate_router = APIRouter(tags=["internal"])


class TerminateRequest(BaseModel):
    """Termination request body.  ``reason`` is recorded in the
    session's failure metadata by the Control Center side.
    """

    reason: str | None = None


class TerminateResponse(BaseModel):
    """Result of a session termination request."""

    session_id: uuid.UUID
    cancelled: bool
    already_terminal: bool = False
    reason: str | None = None


@terminate_router.post(
    "/terminate/{session_id}",
    response_model=TerminateResponse,
    summary="Cancel an in-flight session task (Control Center → Agent Runtime)",
)
async def terminate_session(
    session_id: uuid.UUID,
    request: Request,
) -> TerminateResponse:
    """Cancel the background task running the given session.

    Looks up ``app.state.session_tasks[session_id]`` and calls
    ``Task.cancel()`` on it.  The task's ``_execute_session`` wrapper
    is expected to re-raise ``CancelledError`` so asyncio can unwind
    cleanly; the calling Control Center side is the source of truth
    for the session's terminal status.

    Authentication is enforced by ControlCenterCertificateMiddleware —
    any request without a valid ``service:control-center`` certificate
    is rejected with 401 before this handler is called.

    Returns:
        ``TerminateResponse(session_id, cancelled=True)`` on success.

    Raises:
        404 — no in-flight task for the given session.
    """
    session_tasks: dict[uuid.UUID, asyncio.Task] = getattr(
        request.app.state, "session_tasks", None
    )
    if session_tasks is None:
        logger.warning(
            "terminate_session: no session_tasks registry on app.state (session %s)",
            session_id,
        )
        raise HTTPException(
            status_code=404,
            detail=f"No in-flight task for session {session_id}",
        )
    task = session_tasks.get(session_id)
    if task is None:
        logger.info(
            "terminate_session: no in-flight task for session %s (already completed?)",
            session_id,
        )
        raise HTTPException(
            status_code=404,
            detail=f"No in-flight task for session {session_id}",
        )

    # Cancel the task.  asyncio.CancelledError will propagate into the
    # executor's main loop at the next checkpoint; we deliberately do
    # NOT await the cancelled coroutine here — that would require
    # blocking the API response, and the executor's own
    # mark_session_failed call (made by the orchestrator on the CC
    # side) is the authoritative terminal transition.
    task.cancel()
    logger.info(
        "terminate_session: cancelled task for session %s (task name=%s)",
        session_id,
        task.get_name(),
    )
    return TerminateResponse(
        session_id=session_id,
        cancelled=True,
        reason="Cancelled by Control Center operator request",
    )
