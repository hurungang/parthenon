"""Agent Runtime — Resume Endpoint for Human Intervene.

Allows the Control Center to signal that a human has responded to an
intervene request and the agent session can resume.

Route: POST /internal/resume

Security:
    ControlCenterCertificateMiddleware is applied globally in AR main.py and
    rejects any request whose inbound TLS certificate is not
    ``service:control-center`` before this handler runs.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.agent_runtime.api.execute import _execute_session

logger = logging.getLogger(__name__)

resume_router = APIRouter(tags=["internal"])


class ResumeRequest(BaseModel):
    """Request body for resuming a session after human intervention."""

    session_id: uuid.UUID
    response_value: dict | None = None


class ResumeResponse(BaseModel):
    """Response confirming the session has been marked for resume."""

    session_id: uuid.UUID
    status: str


@resume_router.post(
    "/internal/resume",
    response_model=ResumeResponse,
    summary="Resume a session after human intervention (Control Center → Agent Runtime)",
)
async def resume_session(
    body: ResumeRequest,
    request: Request,
) -> ResumeResponse:
    """Mark a session for resume after human intervention response.

    Transitions the session back to ``running`` status and launches a new
    background execution task.  The executor receives the human's response
    value so it can inject it as follow-up context without re-querying
    the database.

    Authentication is enforced by ControlCenterCertificateMiddleware.
    """
    data_client = getattr(request.app.state, "data_client", None)
    if data_client is None:
        logger.error(
            "resume_session: no data_client on app.state for session %s",
            body.session_id,
        )
        raise HTTPException(status_code=503, detail="Agent Runtime not ready")

    # Transition session back to running status
    await data_client.mark_session_running(body.session_id)
    logger.info(
        "resume_session: session %s transitioned to running after human intervention (response_value=%s)",
        body.session_id,
        body.response_value,
    )

    # Launch a new execution as a background task so the executor re-enters
    # the observe-reason-act loop and continues where it left off.
    semaphore: asyncio.Semaphore | None = getattr(
        request.app.state, "execution_semaphore", None
    )
    task = asyncio.create_task(
        _execute_session(
            body.session_id,
            data_client,
            semaphore,
            response_value=body.response_value,
        ),
        name=f"resume-{body.session_id}",
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
        "resume_session: launched execution task for session %s",
        body.session_id,
    )

    return ResumeResponse(
        session_id=body.session_id,
        status="resumed",
    )
