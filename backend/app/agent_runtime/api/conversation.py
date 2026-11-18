"""Agent Runtime conversation execution endpoints.

Accepts websocket conversation-turn execution requests from Communication Hub.
Communication Hub remains transport-only and delegates all conversational
agent execution to Agent Runtime.

Two surfaces:

* ``POST /internal/conversation/turn`` — start a conversational turn.  The
  stream can now end with a ``paused`` chunk (a ``human_intervene`` pause whose
  durable checkpoint + resume index were persisted) instead of a ``final``.
* ``POST /internal/conversation/resume`` — continue a paused turn from its
  Control Center–owned checkpoint on *any* Agent Runtime instance: claim, load,
  rebuild, ``Command(resume=<operator response>)``, stream status events and a
  ``final`` (or a new ``paused``) chunk.  Claim contention is a distinct HTTP
  409 so the resume router can de-duplicate instead of double-applying.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent_runtime.checkpoint_transport import (
    CheckpointTransportError,
    ResumeClaimContentionError,
)
from app.agent_runtime.turn_resume_service import (
    ConversationResumeOutcome,
    build_resume_service,
)
from app.services.agents.runtime_executor import AgentRuntimeExecutor

logger = logging.getLogger(__name__)

conversation_router = APIRouter(prefix="/internal/conversation", tags=["internal"])

#: Terminal NDJSON chunk types.
_TERMINAL_CHUNK_TYPES = frozenset({"final", "error", "paused", "resume_status"})


class ConversationTurnRequest(BaseModel):
    """Payload for one conversation turn execution."""

    conv_session_id: uuid.UUID
    agent_type_id: uuid.UUID
    messages: list[dict[str, Any]]
    stream_status_events: bool = False
    #: Optional opaque paused-turn key supplied by the transport layer.  When
    #: absent a fresh one is generated for the turn (never from user input).
    turn_idempotency_key: str | None = None


class ConversationTurnResponse(BaseModel):
    """Final text response for one conversation turn (or a pause)."""

    response: str
    guardrail_usage: dict[str, Any] | None = None
    status_events: list[dict[str, str]] = Field(default_factory=list)
    #: True when the turn paused on ``human_intervene``.  The client must not
    #: render ``response`` as a reply; it waits for the operator instead.
    paused: bool = False
    pause: dict[str, Any] | None = None


class ConversationResumeRequest(BaseModel):
    """Payload for resuming a paused conversation turn."""

    conv_session_id: uuid.UUID
    response_value: dict[str, Any] | None = None
    stream_status_events: bool = False


class ConversationResumeResponse(BaseModel):
    """Non-streaming resume result (terminal / non-resumed outcomes)."""

    status: str
    reason: str | None = None
    response: str = ""
    guardrail_usage: dict[str, Any] | None = None
    status_events: list[dict[str, str]] = Field(default_factory=list)
    pause: dict[str, Any] | None = None
    resume_id: str | None = None
    write_applied: bool = False


def _register_conversation_task(request: Request, conv_session_id: uuid.UUID, task: asyncio.Task) -> dict:
    conversation_tasks: dict = getattr(request.app.state, "conversation_tasks", None)
    if conversation_tasks is None:
        conversation_tasks = {}
        request.app.state.conversation_tasks = conversation_tasks
    conversation_tasks[conv_session_id] = task
    return conversation_tasks


async def _stream_queue(
    request: Request,
    conv_session_id: uuid.UUID,
    queue: "asyncio.Queue[dict[str, Any]]",
    task: asyncio.Task,
):
    """Yield queued NDJSON chunks until a terminal chunk is produced."""
    conversation_tasks = _register_conversation_task(request, conv_session_id, task)
    try:
        while True:
            item = await queue.get()
            yield json.dumps(item) + "\n"
            if item.get("type") in _TERMINAL_CHUNK_TYPES:
                break
    finally:
        conversation_tasks.pop(conv_session_id, None)
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


@conversation_router.post("/turn", response_model=ConversationTurnResponse)
async def execute_conversation_turn(
    body: ConversationTurnRequest,
    request: Request,
) -> ConversationTurnResponse | StreamingResponse:
    """Execute one conversation turn in Agent Runtime.

    Security is enforced by Agent Runtime certificate middleware, which allows
    Communication Hub service certificates for this service boundary.
    """
    data_client = getattr(request.app.state, "data_client", None)
    if data_client is None:
        raise HTTPException(
            status_code=503,
            detail="Agent Runtime not ready; startup may be incomplete",
        )

    try:
        agent_context = await data_client.get_agent_context(
            body.agent_type_id, conv_session_id=body.conv_session_id
        )
    except Exception as exc:
        # Structured CC refusals (e.g. 412 optimizer_model_unavailable for an
        # optimization conversation) must not be flattened into a generic
        # "not found": re-raise them with their own status + detail so the
        # transport can surface the documented reason.
        status_code = getattr(exc, "status_code", None)
        detail = getattr(exc, "detail", None)
        if status_code == 412 and detail is not None:
            raise HTTPException(status_code=412, detail=detail) from exc
        raise HTTPException(status_code=404, detail=f"Agent context not found: {exc}") from exc

    if not agent_context.get("is_active", False):
        raise HTTPException(status_code=400, detail="Agent type is not active")
    if not agent_context.get("identity_role_valid", False):
        raise HTTPException(status_code=403, detail="Agent identity is not assigned to role")

    model_id = agent_context.get("model_id")
    model_config_id = agent_context.get("model_config_id")
    if not model_id or not model_config_id:
        raise HTTPException(status_code=400, detail="Agent model is not configured")

    try:
        model_config = await data_client.get_model_config(uuid.UUID(str(model_config_id)))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to resolve model config: {exc}") from exc

    cert_manager = getattr(request.app.state, "certificate_manager", None)
    cert_path = str(cert_manager.cert_path) if cert_manager and cert_manager.cert_path else None
    key_path = str(cert_manager.key_path) if cert_manager and cert_manager.key_path else None

    # The turn idempotency key is generated by the runtime (opaque, per turn)
    # and stays stable for the whole paused turn — it is never derived from
    # user input and never regenerated per attempt.
    turn_idempotency_key = body.turn_idempotency_key or uuid.uuid4().hex

    executor = AgentRuntimeExecutor(data_client=data_client)
    if body.stream_status_events:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def on_status_event(event: dict[str, str]) -> None:
            await queue.put({"type": "status_event", "event": event})

        async def run_turn() -> None:
            try:
                response_text, guardrail_usage, status_events = await executor.execute_conversation_turn_from_context(
                    agent_type_id=body.agent_type_id,
                    agent_context=agent_context,
                    model_config=model_config,
                    messages=body.messages,
                    conv_session_id=body.conv_session_id,
                    cert_path=cert_path,
                    key_path=key_path,
                    status_event_callback=on_status_event,
                    turn_idempotency_key=turn_idempotency_key,
                )
                pause = executor.pop_conversation_pause()
                if pause is not None:
                    await queue.put({"type": "paused", "pause": pause.as_dict()})
                    return
                await queue.put(
                    {
                        "type": "final",
                        "response": response_text,
                        "guardrail_usage": guardrail_usage,
                        "status_events": status_events,
                    }
                )
            except Exception as exc:
                logger.error(
                    "Conversation streaming execution failed: session=%s agent_type=%s error=%s",
                    body.conv_session_id,
                    body.agent_type_id,
                    exc,
                    exc_info=True,
                )
                # FIX-20261101-111439: guardrail stops carry a machine-readable
                # reason + details so Control Center can surface a clear,
                # user-comprehensible error turn instead of the generic
                # "An error occurred" fallback.
                from app.services.agents.guardrail_callback import GuardrailStop as CallbackGuardrailStop
                from app.services.agents.guardrails import GuardrailStop as ExecutorGuardrailStop

                if isinstance(exc, (CallbackGuardrailStop, ExecutorGuardrailStop)):
                    await queue.put(
                        {
                            "type": "error",
                            "error_type": exc.reason,
                            "error_details": exc.details or {},
                        }
                    )
                    return
                await queue.put({"type": "error"})

        task = asyncio.create_task(run_turn())
        # FIX-20261031-091657 (Defect B): register the in-flight conversation
        # turn so ``/terminate/{conv_session_id}`` can cancel a hung/slow turn.
        return StreamingResponse(
            _stream_queue(request, body.conv_session_id, queue, task),
            media_type="application/x-ndjson",
        )

    response_text, guardrail_usage, status_events = await executor.execute_conversation_turn_from_context(
        agent_type_id=body.agent_type_id,
        agent_context=agent_context,
        model_config=model_config,
        messages=body.messages,
        conv_session_id=body.conv_session_id,
        cert_path=cert_path,
        key_path=key_path,
        turn_idempotency_key=turn_idempotency_key,
    )

    pause = executor.pop_conversation_pause()
    if pause is not None:
        logger.info(
            "Conversation turn paused in Agent Runtime: session=%s resume=%s",
            body.conv_session_id,
            pause.resume_id,
        )
        return ConversationTurnResponse(
            response="",
            guardrail_usage=guardrail_usage,
            status_events=status_events,
            paused=True,
            pause=pause.as_dict(),
        )

    logger.info(
        "Conversation turn executed in Agent Runtime: session=%s agent_type=%s",
        body.conv_session_id,
        body.agent_type_id,
    )
    return ConversationTurnResponse(
        response=response_text,
        guardrail_usage=guardrail_usage,
        status_events=status_events,
    )


@conversation_router.post(
    "/resume",
    response_model=ConversationResumeResponse,
    responses={409: {"description": "Another instance is resuming this turn"}},
)
async def resume_conversation_turn(
    body: ConversationResumeRequest,
    request: Request,
) -> ConversationResumeResponse | StreamingResponse:
    """Resume a paused conversational turn from its durable checkpoint.

    Claim arbitration happens BEFORE any stream is opened: contention is a
    distinct HTTP 409 (never a half-open stream), and a terminal record is
    reported declaratively (``already_resolved`` / ``unresumable`` /
    ``not_awaiting``) so the resume router can deliver the right outcome
    without re-running anything.
    """
    data_client = getattr(request.app.state, "data_client", None)
    if data_client is None:
        raise HTTPException(
            status_code=503,
            detail="Agent Runtime not ready; startup may be incomplete",
        )

    service = build_resume_service(request.app.state, data_client)
    conv_session_id = body.conv_session_id

    try:
        claim = await service.claim(conv_session_id)
    except ResumeClaimContentionError as exc:
        logger.info(
            "Conversation resume contention for session %s (holder=%s, expires=%s)",
            conv_session_id,
            exc.holder_instance_id,
            exc.claim_expires_at,
        )
        raise HTTPException(
            status_code=409,
            detail={
                "status": "claim_held",
                "reason": "already_being_resumed",
                "holder_instance_id": exc.holder_instance_id,
                "claim_expires_at": (
                    exc.claim_expires_at.isoformat()
                    if exc.claim_expires_at is not None
                    else None
                ),
            },
        ) from exc
    except CheckpointTransportError as exc:
        logger.error(
            "Conversation resume failed to claim session %s: %s", conv_session_id, exc
        )
        raise HTTPException(status_code=502, detail="Checkpoint relay unavailable") from exc

    terminal = service.outcome_for_claim(claim)
    if terminal is not None:
        return _outcome_response(terminal)

    if body.stream_status_events:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def on_status_event(event: dict[str, str]) -> None:
            await queue.put({"type": "status_event", "event": event})

        async def run_resume() -> None:
            try:
                outcome = await service.resume_claimed(
                    conv_session_id,
                    claim,
                    body.response_value,
                    status_event_callback=on_status_event,
                )
                await queue.put(_outcome_chunk(outcome))
            except CheckpointTransportError as exc:
                logger.error(
                    "Conversation resume transport failure for session %s: %s",
                    conv_session_id,
                    exc,
                )
                await queue.put(
                    {
                        "type": "error",
                        "error_type": "resume_failed",
                        "reason": "checkpoint_relay_unavailable",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Conversation resume failed for session %s: %s",
                    conv_session_id,
                    exc,
                )
                await queue.put(
                    {"type": "error", "error_type": "resume_failed"}
                )

        task = asyncio.create_task(run_resume())
        return StreamingResponse(
            _stream_queue(request, conv_session_id, queue, task),
            media_type="application/x-ndjson",
        )

    try:
        outcome = await service.resume_claimed(
            conv_session_id,
            claim,
            body.response_value,
        )
    except CheckpointTransportError as exc:
        logger.error(
            "Conversation resume transport failure for session %s: %s",
            conv_session_id,
            exc,
        )
        raise HTTPException(status_code=502, detail="Checkpoint relay unavailable") from exc

    return _outcome_response(outcome)


def _outcome_response(outcome: ConversationResumeOutcome) -> ConversationResumeResponse:
    return ConversationResumeResponse(
        status=outcome.status,
        reason=outcome.reason,
        response=outcome.response,
        guardrail_usage=outcome.guardrail_usage,
        status_events=outcome.status_events,
        pause=outcome.pause.as_dict() if outcome.pause is not None else None,
        resume_id=outcome.resume_id,
        write_applied=outcome.write_applied,
    )


def _outcome_chunk(outcome: ConversationResumeOutcome) -> dict[str, Any]:
    """Translate a resume outcome into the terminal NDJSON chunk."""
    if outcome.pause is not None:
        return {"type": "paused", "pause": outcome.pause.as_dict()}
    if outcome.status != "resumed":
        return {
            "type": "resume_status",
            "status": outcome.status,
            "reason": outcome.reason,
            "resume_id": outcome.resume_id,
            "write_applied": outcome.write_applied,
        }
    return {
        "type": "final",
        "response": outcome.response,
        "guardrail_usage": outcome.guardrail_usage,
        "status_events": outcome.status_events,
    }
