"""Agent Runtime — Execution Trigger Endpoint.

Accepts execution trigger requests from Communication Hub (mTLS-authenticated)
and immediately executes the session without polling or queuing.

Route: POST /execute

Security:
    ControlCenterCertificateMiddleware is applied globally in AR main.py and
    rejects any request whose inbound TLS certificate is not
    ``service:control-center`` before this handler runs.

Phase 5.1 — Control Flow Implementation.

Phase 3.11: the background task is registered in
``app.state.session_tasks`` so the Control Center can cancel it via
``POST /terminate/{session_id}`` when an operator requests termination.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

execute_router = APIRouter(tags=["internal"])


class ExecuteRequest(BaseModel):
    """Execution trigger payload sent by Control Center."""

    session_id: uuid.UUID
    agent_type_id: uuid.UUID
    input_data: dict[str, Any] | None = None


class ExecuteResponse(BaseModel):
    """Response confirming the session was accepted for execution."""

    session_id: uuid.UUID
    status: str


@execute_router.post(
    "/execute",
    response_model=ExecuteResponse,
    summary="Trigger agent execution (Control Center → Agent Runtime)",
)
async def trigger_execution(
    body: ExecuteRequest,
    request: Request,
) -> ExecuteResponse:
    """Immediately execute an agent session triggered by Control Center.

    Transitions the session from ``queued`` → ``running`` and launches the
    executor as a background asyncio task.  Returns ``accepted`` once the
    status transition is confirmed — execution continues asynchronously.

    The background task is registered in
    ``app.state.session_tasks[session_id]`` so the Control Center's
    termination orchestrator can cancel it via
    ``POST /terminate/{session_id}``.

    Authentication is enforced by ControlCenterCertificateMiddleware — any
    request without a valid ``service:control-center`` certificate is rejected
    with 401 before this handler is called.

    Returns:
        ``{"session_id": ..., "status": "accepted"}`` on success.

    Raises:
        503 — data client not initialised (AR startup incomplete).
        502 — failed to transition session to running state.
    """
    data_client = getattr(request.app.state, "data_client", None)
    if data_client is None:
        logger.error(
            "data_client not initialised on app.state — cannot execute session %s",
            body.session_id,
        )
        raise HTTPException(
            status_code=503,
            detail="Agent Runtime not ready; startup may be incomplete",
        )

    semaphore: asyncio.Semaphore | None = getattr(request.app.state, "execution_semaphore", None)

    # Transition session queued → running immediately
    try:
        await data_client.mark_session_running(body.session_id)
    except Exception as exc:
        logger.error(
            "Failed to mark session %s as running: %s", body.session_id, exc
        )
        raise HTTPException(
            status_code=502,
            detail=f"Failed to transition session to running: {exc}",
        )

    # Launch execution as a background task (non-blocking) and register
    # it in ``app.state.session_tasks`` so the Control Center can cancel
    # it via ``POST /terminate/{session_id}`` when an operator requests
    # termination.  Without this registry, the in-memory task would
    # outlive the operator's intent and continue running the agent until
    # the natural completion path.
    task = asyncio.create_task(
        _execute_session(body.session_id, data_client, semaphore),
        name=f"execute-{body.session_id}",
    )
    session_tasks: dict[uuid.UUID, asyncio.Task] = getattr(
        request.app.state, "session_tasks", None
    )
    if session_tasks is None:
        session_tasks = {}
        request.app.state.session_tasks = session_tasks
    session_tasks[body.session_id] = task
    task.add_done_callback(lambda t: session_tasks.pop(body.session_id, None))

    logger.info(
        "Execution trigger received: session=%s agent_type=%s — started immediately",
        body.session_id,
        body.agent_type_id,
    )
    return ExecuteResponse(session_id=body.session_id, status="accepted")


async def _execute_session(
    session_id: uuid.UUID,
    data_client: Any,
    semaphore: asyncio.Semaphore | None,
    response_value: dict | None = None,
) -> None:
    """Run a single session to completion, optionally bounded by the concurrency semaphore.

    Args:
        session_id:      UUID of the session to execute.
        data_client:     Control Center data client for all DB interactions.
        semaphore:       Optional concurrency limiter.
        response_value:  When set (resume after human intervention), the executor
                         injects this as follow-up context so the LLM can continue.
    """
    from opentelemetry import trace
    tracer = trace.get_tracer(__name__)

    async def _run() -> None:
        with tracer.start_as_current_span(
            "execute.run_session",
            attributes={"session_id": str(session_id)},
        ):
            try:
                from app.services.agents.runtime_executor import AgentRuntimeExecutor
                executor = AgentRuntimeExecutor(data_client=data_client)
                await executor.run(session_id, data_client, response_value=response_value)
            except asyncio.CancelledError:
                # Operator-requested termination.  Re-raise so the parent
                # task wrapper (and asyncio) see the cancellation, but
                # the session state has already been marked failed by
                # the caller of terminate.  We do NOT mark the session
                # as failed here because the terminate endpoint is the
                # single source of truth for that attribution.
                logger.info(
                    "Session %s execution task was cancelled (operator termination)",
                    session_id,
                )
                raise
            except Exception as exc:
                logger.exception("Session %s failed: %s", session_id, exc)
                try:
                    await data_client.mark_session_failed(
                        session_id,
                        str(exc),
                        stop_category="functional_failure",
                    )
                except Exception:
                    logger.exception("Failed to mark session %s as failed", session_id)

    if semaphore is not None:
        async with semaphore:
            await _run()
    else:
        await _run()
