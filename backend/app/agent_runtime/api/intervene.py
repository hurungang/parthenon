"""Agent Runtime — Resume Endpoint for Human Intervene.

Allows Control Center to signal that a human has responded to an intervene
request and the agent session can resume.

Route: POST /internal/resume

Security:
    ControlCenterCertificateMiddleware is applied globally in AR main.py and
    rejects any request whose inbound TLS certificate is not
    ``service:communication-hub`` before this handler runs (the Communication
    Hub forwards the Control Center dispatch).

Two kinds of session id arrive here:

* an **AgentJob** id — the task-agent path, unchanged: mark the job running and
  relaunch the execution with the operator's response injected;
* a **conversation session** id — delegated to the durable conversational
  resume handler (:mod:`app.agent_runtime.turn_resume_service`), which claims
  the paused turn, loads its Control Center–owned checkpoint and continues it.
  The legacy in-process registry is consulted first only as a compatibility
  fallback for a pause created while the checkpoint relay was unavailable.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.agent_runtime.api.execute import _execute_session
from app.agent_runtime.checkpoint_transport import (
    CheckpointTransportError,
    CheckpointTransportUnavailableError,
    ResumeClaimContentionError,
)
from app.agent_runtime.turn_resume_service import (
    build_resume_service,
)

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
    #: Machine-readable reason for ``unresumable`` / ``already_resolved``.
    reason: str | None = None


@resume_router.post(
    "/internal/resume",
    response_model=ResumeResponse,
    summary="Resume a session after human intervention (Control Center → Agent Runtime)",
)
async def resume_session(
    body: ResumeRequest,
    request: Request,
) -> ResumeResponse:
    """Resume a session after a human intervention response.

    For an AgentJob session this transitions the job back to ``running`` and
    launches the execution task (unchanged).  For a conversation session it
    delegates to the durable conversational resume path and returns one of
    ``resumed | already_resolved | unresumable | not_awaiting``.

    Authentication is enforced by ControlCenterCertificateMiddleware.
    """
    data_client = getattr(request.app.state, "data_client", None)

    conv_session_id = body.session_id

    # DEPRECATED compatibility only: a pause created while the checkpoint relay
    # was unavailable is still waiting in this process.  Resolve it in-place so
    # that deployment window keeps today's conversational UX.  The durable
    # path never uses this registry.
    from app.agent_runtime import conversation_resume

    if conversation_resume.is_pending(conv_session_id):
        delivered = conversation_resume.resolve(
            conv_session_id, body.response_value or {}
        )
        if delivered:
            logger.info(
                "resume_session: legacy in-process conversational intervention "
                "resolved for session %s",
                conv_session_id,
            )
            return ResumeResponse(
                session_id=body.session_id,
                status="resumed",
                reason="in_process_fallback",
            )

    if data_client is None:
        logger.error(
            "resume_session: no data_client on app.state for session %s",
            body.session_id,
        )
        raise HTTPException(status_code=503, detail="Agent Runtime not ready")

    # Distinguish a task-agent job (has an AgentJob row) from a conversation
    # session.  A lookup failure is treated as conversation-scoped so a resume
    # can never run the job path against a conversation id.
    try:
        agent_job = await data_client.get_session(body.session_id)
    except Exception:
        logger.warning(
            "resume_session: could not verify AgentJob for session %s — "
            "treating as conversation-scoped resume",
            body.session_id,
            exc_info=True,
        )
        agent_job = None

    if agent_job is None:
        return await _resume_conversation_session(
            request=request,
            data_client=data_client,
            conv_session_id=conv_session_id,
            response_value=body.response_value,
        )

    # ── Task-agent path (unchanged) ──────────────────────────────────────────
    await data_client.mark_session_running(body.session_id)
    logger.info(
        "resume_session: session %s transitioned to running after human intervention (response_value=%s)",
        body.session_id,
        body.response_value,
    )

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


async def _resume_conversation_session(
    *,
    request: Request,
    data_client,
    conv_session_id: uuid.UUID,
    response_value: dict | None,
) -> ResumeResponse:
    """Delegate a conversation-scoped resume to the durable resume service."""
    service = build_resume_service(request.app.state, data_client)

    try:
        claim = await service.claim(conv_session_id)
    except ResumeClaimContentionError as exc:
        # Another instance is already continuing this turn.  Report ``resumed``
        # so the caller does not emit a spurious terminal/orphaned notice.
        logger.info(
            "resume_session: conversation %s is already being resumed by %s",
            conv_session_id,
            exc.holder_instance_id,
        )
        return ResumeResponse(
            session_id=conv_session_id,
            status="resumed",
            reason="claim_held_elsewhere",
        )
    except CheckpointTransportUnavailableError as exc:
        logger.warning(
            "resume_session: checkpoint relay unavailable for conversation %s (%s)",
            conv_session_id,
            exc,
        )
        return ResumeResponse(
            session_id=conv_session_id,
            status="unresumable",
            reason="checkpoint_relay_unavailable",
        )
    except CheckpointTransportError as exc:
        logger.error(
            "resume_session: failed to claim conversation %s: %s",
            conv_session_id,
            exc,
        )
        return ResumeResponse(
            session_id=conv_session_id,
            status="unresumable",
            reason="resume_failed",
        )

    terminal = service.outcome_for_claim(claim)
    if terminal is not None:
        logger.info(
            "resume_session: conversation %s is %s (%s)",
            conv_session_id,
            terminal.status,
            terminal.reason,
        )
        return ResumeResponse(
            session_id=conv_session_id,
            status=terminal.status,
            reason=terminal.reason,
        )

    # The turn runs out-of-band: this legacy route only reports that the resume
    # was accepted (the streaming resume route owns delivery/outcome
    # persistence during the CH rollout).
    resume_tasks: dict[uuid.UUID, asyncio.Task] = getattr(
        request.app.state, "conversation_resume_tasks", None
    )
    if resume_tasks is None:
        resume_tasks = {}
        request.app.state.conversation_resume_tasks = resume_tasks

    async def _run() -> None:
        try:
            outcome = await service.resume_claimed(
                conv_session_id, claim, response_value
            )
            logger.info(
                "resume_session: conversation %s resume finished with %s%s",
                conv_session_id,
                outcome.status,
                f" ({outcome.reason})" if outcome.reason else "",
            )
        except Exception:
            logger.exception(
                "resume_session: conversation %s resume failed", conv_session_id
            )

    task = asyncio.create_task(_run(), name=f"conversation-resume-{conv_session_id}")
    resume_tasks[conv_session_id] = task
    task.add_done_callback(lambda t: resume_tasks.pop(conv_session_id, None))
    return ResumeResponse(session_id=conv_session_id, status="resumed")
