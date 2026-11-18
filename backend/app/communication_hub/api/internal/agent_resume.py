"""Communication Hub — instance-independent, de-duplicated resume dispatch.

Route: ``POST /internal/agent/resume/{session_id}``

Control Center records the operator's answer and dispatches **one** resume
through this route.  Two very different paths live behind it:

* **Agent-job sessions** (non-conversational) keep the legacy behaviour: the
  resume is forwarded to Agent Runtime's ``POST /internal/resume`` and the AR
  status is returned.  Room for retry is preserved.
* **Conversation sessions** are routed to Agent Runtime's durable
  ``POST /internal/conversation/resume`` in *streaming* mode.  The paused turn
  can be continued by **any** Agent Runtime instance (it reloads the state from
  Control Center), so the resume is never pinned to the instance that paused
  it.  The dispatch runs in a supervised background task:

  - the request returns promptly with a status instead of holding the HTTP
    connection open for the whole turn;
  - streamed status events are forwarded to the live WebSocket and persisted
    through Control Center (so the activity survives reconnects);
  - a ``final`` chunk delivers the reply **once** and closes the turn through
    Control Center's single-transaction ``complete`` endpoint;
  - a ``paused`` chunk records the new pause and delivers no reply;
  - a repeated operator response for the same answered intervention is
    de-duplicated (one in-flight dispatch per conversation, then the stored
    outcome), and Agent Runtime's turn claim arbitrates across instances.

Terminal semantics: Communication Hub emits a terminal ``chat_status`` **only**
when Control Center reports that the turn can no longer be resumed, carrying
Control Center's reason code and an actionable message.  A service restart on
its own never produces a terminal message — a paused turn is durably
resumable, and a genuinely unresumable one is resolved by Control Center.

Communication Hub is transport only here: it forwards the verified signed
tenant header set (never minting one), never reads the database, and never
inspects the checkpoint payload.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.communication_hub.data_client import (
    ControlCenterDataClient,
    ControlCenterDataError,
    ConversationResumeLookup,
)
from app.core.config import get_settings
from app.core.internal_http import internal_httpx_client
from app.core.ssl_context import get_ssl_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/agent", tags=["Internal - Agent Control"])

#: Agent Runtime route for a durable, streamed conversational resume.
AR_CONVERSATION_RESUME_PATH = "/internal/conversation/resume"
#: Agent Runtime route for the legacy (job-session / degraded) resume.
AR_LEGACY_RESUME_PATH = "/internal/resume"

# ── Resume status vocabulary (returned to Control Center) ────────────────────
#: The resume was accepted and is running out of band.
RESUME_STATUS_RESUMED = "resumed"
#: The answer was already applied (or is being applied) — nothing re-dispatched.
RESUME_STATUS_ALREADY_RESOLVED = "already_resolved"
#: The turn exists but can never continue (Control Center reports why).
RESUME_STATUS_UNRESUMABLE = "unresumable"
#: Nothing is paused for this session (no live resume record).
RESUME_STATUS_NOT_AWAITING = "not_awaiting"
#: A repeat arrived while the first dispatch was still in flight.
RESUME_STATUS_IN_FLIGHT = "in_flight"
#: The dispatch could not reach Agent Runtime; the pause is still answerable.
RESUME_STATUS_DISPATCH_FAILED = "dispatch_failed"

#: Dispatch guard states.
_DISPATCH_IN_FLIGHT = "in_flight"
_DISPATCH_COMPLETED = "completed"

#: How many completed dispatches we keep for stored-outcome short-circuiting.
_MAX_TRACKED_DISPATCHES = 256

#: Terminal, reason-specific text for a durably unresumable turn. Keyed by
#: Control Center's ``terminal_reason_code`` (never a hardcoded restart string).
_TERMINAL_REASON_MESSAGES: dict[str, str] = {
    "expired": (
        "This confirmation was not answered within its validity window and has "
        "now expired. Nothing was applied — ask again to generate a fresh "
        "preview."
    ),
    "superseded": (
        "A newer confirmation replaced this one, so it can no longer be "
        "answered. Nothing was applied — ask again if you still need it."
    ),
    "cancelled": (
        "This confirmation was cancelled, so the paused turn cannot continue. "
        "Nothing was applied."
    ),
    "checkpoint_unavailable": (
        "The paused turn can no longer be restored because its saved state is "
        "unavailable. Nothing was applied — ask again to repeat the request."
    ),
    "checkpoint_consumed": (
        "The paused turn's saved state was already used, so it cannot be "
        "restored again. Nothing was applied — ask again to repeat the request."
    ),
    "resume_failed": (
        "The paused turn could not be resumed. Nothing was applied — ask again "
        "to repeat the request."
    ),
    "unexpectedly_terminated": (
        "The assistant stopped unexpectedly (e.g. a server restart) before "
        "finishing. Nothing was applied. Please resend your request or ask "
        "again."
    ),
}

_TERMINAL_REASON_DEFAULT_MESSAGE = (
    "This confirmation can no longer be resumed. Nothing was applied — ask "
    "again to repeat the request."
)

#: Reason codes that mean "the answer window closed" (a timed-out turn).
_EXPIRY_REASON_CODES = frozenset({"expired"})

#: One terminal notification per (conversation, reason) within this window.
_TERMINAL_NOTIFICATION_TTL_SECONDS = 300.0
_TERMINAL_NOTIFIED: dict[str, float] = {}


def terminal_message_for_reason(
    reason_code: str | None,
    *,
    write_applied: bool = False,
) -> str:
    """Render the actionable message for a durably unresumable turn."""
    key = (reason_code or "").strip()
    message = _TERMINAL_REASON_MESSAGES.get(key, _TERMINAL_REASON_DEFAULT_MESSAGE)
    if write_applied:
        # Never claim "nothing was applied" when the applied marker is set.
        return message.replace(
            "Nothing was applied — ", ""
        ).replace(" Nothing was applied.", "")
    return message


def terminal_status_for_reason(reason_code: str | None) -> str:
    """Map a terminal reason code onto the terminal ``chat_status`` value."""
    return "timed_out" if (reason_code or "") in _EXPIRY_REASON_CODES else "failed"


# ── Models ───────────────────────────────────────────────────────────────────


class AgentResumeRequest(BaseModel):
    """Request to resume an agent session after human intervention."""

    response_value: dict | None = None
    #: Optional identity of the answered intervention / resume record.  Control
    #: Center may send them; when absent the live resume record supplies them.
    request_id: uuid.UUID | None = None
    resume_id: uuid.UUID | None = None


class AgentResumeResponse(BaseModel):
    """Resume dispatch result (never blocks on the resumed turn)."""

    session_id: uuid.UUID
    status: str
    reason: str | None = None
    resume_id: str | None = None
    write_applied: bool = False
    deduplicated: bool = False


# ── Dispatch guard (de-duplicate repeated operator responses) ────────────────


@dataclass
class ResumeDispatch:
    """One in-flight or recently completed resume dispatch for a conversation.

    Keyed by conversation session id: the resume index guarantees at most one
    *live* record per session, so a repeat of the same answered intervention
    always lands on the same guard entry while it is in flight or right after
    it resolved.
    """

    conversation_session_id: uuid.UUID
    resume_id: str | None
    intervention_id: str | None
    started_at: float
    state: str = _DISPATCH_IN_FLIGHT
    status: str = RESUME_STATUS_RESUMED
    reason: str | None = None
    write_applied: bool = False
    task: "asyncio.Task[None] | None" = None


_RESUME_DISPATCHES: dict[str, ResumeDispatch] = {}


def _get_dispatch(conversation_session_id: uuid.UUID | str) -> ResumeDispatch | None:
    return _RESUME_DISPATCHES.get(str(conversation_session_id))


def _register_dispatch(dispatch: ResumeDispatch) -> None:
    _RESUME_DISPATCHES[str(dispatch.conversation_session_id)] = dispatch
    _prune_dispatches()


def _prune_dispatches() -> None:
    """Bound the completed-dispatch memory (oldest completed entries first)."""
    if len(_RESUME_DISPATCHES) <= _MAX_TRACKED_DISPATCHES:
        return
    completed = sorted(
        (d for d in _RESUME_DISPATCHES.values() if d.state == _DISPATCH_COMPLETED),
        key=lambda d: d.started_at,
    )
    for dispatch in completed[: len(_RESUME_DISPATCHES) - _MAX_TRACKED_DISPATCHES]:
        _RESUME_DISPATCHES.pop(str(dispatch.conversation_session_id), None)


def reset_resume_dispatch_state() -> None:
    """Clear the dispatch guard (test isolation / service restart)."""
    for dispatch in list(_RESUME_DISPATCHES.values()):
        task = dispatch.task
        if task is not None and not task.done():
            task.cancel()
    _RESUME_DISPATCHES.clear()
    _TERMINAL_NOTIFIED.clear()


@dataclass
class ConversationResumeOutcome:
    """Normalized outcome of one streamed Agent Runtime resume."""

    status: str
    reason: str | None = None
    response: str = ""
    guardrail_usage: dict[str, Any] | None = None
    status_events: list[dict[str, Any]] = field(default_factory=list)
    pause: dict[str, Any] | None = None
    write_applied: bool = False


# ── Route ────────────────────────────────────────────────────────────────────


@router.post("/resume/{session_id}", response_model=AgentResumeResponse)
async def forward_resume_session(
    session_id: uuid.UUID,
    body: AgentResumeRequest,
    request: Request,
) -> AgentResumeResponse:
    """Forward a resume request from Control Center.

    Conversation-scoped ids are dispatched out of band through the durable
    resume route; agent-job ids keep the legacy forwarding path.  A repeated
    answer for the same intervened turn is answered with the in-flight/stored
    outcome instead of starting a second resume.
    """
    app = request.app
    lookup = await _lookup_resume(app, session_id)

    if lookup is None or not lookup.is_conversation_session:
        # Agent-job session (or Control Center unreachable — Agent Runtime
        # decides which path applies).  Legacy behaviour, retries included.
        return await _forward_legacy_resume(session_id, body, request)

    live = lookup.live_record
    guard = _get_dispatch(session_id)
    live_resume_id = _record_resume_id(live)

    if guard is not None and _is_same_answered_turn(guard, live_resume_id):
        if _is_retryable_dispatch(guard):
            # A previous dispatch never reached Agent Runtime: the pause is
            # still answerable, so this response retries instead of absorbing.
            logger.info(
                "Resume dispatch retrying for conversation %s after a failed "
                "previous dispatch (%s)",
                session_id,
                guard.reason,
            )
            _RESUME_DISPATCHES.pop(str(session_id), None)
        else:
            return _deduplicated_response(session_id, guard)

    if live is None:
        # No live resume record: either nothing is paused (a restart alone must
        # not produce a terminal message) or Control Center already resolved
        # the turn terminally.
        terminal = await _read_terminal_state(app, session_id)
        if terminal is not None:
            reason_code, message_key = terminal
            await _notify_unresumable_turn(
                app,
                session_id,
                reason_code=reason_code,
                message_key=message_key,
            )
            return AgentResumeResponse(
                session_id=session_id,
                status=RESUME_STATUS_UNRESUMABLE,
                reason=reason_code,
            )
        logger.info(
            "Resume for conversation %s: no live resume record — nothing to "
            "dispatch (restart-only or already resolved)",
            session_id,
        )
        return AgentResumeResponse(
            session_id=session_id,
            status=RESUME_STATUS_NOT_AWAITING,
            reason="no_live_resume",
        )

    if _record_expired(live):
        # Control Center's validity window closed: the turn is unresumable.
        reason_code = "expired"
        await _notify_unresumable_turn(app, session_id, reason_code=reason_code)
        return AgentResumeResponse(
            session_id=session_id,
            status=RESUME_STATUS_UNRESUMABLE,
            reason=reason_code,
            resume_id=live_resume_id,
        )

    dispatch = ResumeDispatch(
        conversation_session_id=session_id,
        resume_id=live_resume_id,
        intervention_id=str(body.request_id) if body.request_id else None,
        started_at=time.monotonic(),
    )
    _register_dispatch(dispatch)
    dispatch.task = asyncio.create_task(
        _dispatch_conversation_resume(
            app=app,
            conversation_session_id=session_id,
            response_value=body.response_value or {},
            record=live,
            dispatch=dispatch,
        ),
        name=f"resume-dispatch-{session_id}",
    )
    logger.info(
        "Resume dispatch started for conversation %s (resume_id=%s) → %s",
        session_id,
        live_resume_id,
        AR_CONVERSATION_RESUME_PATH,
    )
    return AgentResumeResponse(
        session_id=session_id,
        status=RESUME_STATUS_RESUMED,
        reason="dispatch_started",
        resume_id=live_resume_id,
    )


# ── Control Center reads (forward-only) ──────────────────────────────────────


async def _lookup_resume(
    app: Any, conversation_session_id: uuid.UUID
) -> ConversationResumeLookup | None:
    """Read the session's live resume record from Control Center (best effort)."""
    data_client: ControlCenterDataClient | None = getattr(app.state, "data_client", None)
    if data_client is None:
        return None
    try:
        return await data_client.get_conversation_turn_resume(conversation_session_id)
    except ControlCenterDataError as exc:
        logger.warning(
            "Resume lookup failed for session %s — falling back to the Agent "
            "Runtime resume route: %s",
            conversation_session_id,
            exc,
        )
        return ConversationResumeLookup(is_conversation_session=False)


async def _read_terminal_state(
    app: Any, conversation_session_id: uuid.UUID
) -> tuple[str, str | None] | None:
    """Return Control Center's terminal reason for the session, if any.

    The persisted activity is the authoritative, reconnect-safe projection: it
    only carries a terminal reason once Control Center has durably resolved the
    turn.  Absent terminal state → the resume must not surface a terminal
    message (a restart alone is not a terminal outcome).
    """
    data_client = getattr(app.state, "data_client", None)
    if data_client is None:
        return None
    try:
        activity = await data_client.get_conversation_activity(conversation_session_id)
    except Exception as exc:  # noqa: BLE001 - best effort
        logger.warning(
            "Terminal-state lookup failed for conversation %s: %s",
            conversation_session_id,
            exc,
        )
        return None
    if not isinstance(activity, dict) or not activity.get("is_terminal"):
        return None
    # A ``finished`` activity means the turn ended normally — never a terminal
    # "can no longer be resumed" notice.
    state = activity.get("state")
    if state not in {"failed", "timed_out"}:
        return None
    reason_code = activity.get("terminal_reason_code")
    if not isinstance(reason_code, str) or not reason_code.strip():
        detail = activity.get("detail")
        if isinstance(detail, dict):
            detail_reason = detail.get("terminal_reason_code")
            if isinstance(detail_reason, str) and detail_reason.strip():
                reason_code = detail_reason
    if not isinstance(reason_code, str) or not reason_code.strip():
        return None
    message_key = activity.get("terminal_message_key")
    if not isinstance(message_key, str) or not message_key:
        detail = activity.get("detail")
        if isinstance(detail, dict):
            detail_key = detail.get("terminal_message_key")
            if isinstance(detail_key, str) and detail_key:
                message_key = detail_key
    return (
        reason_code.strip(),
        message_key if isinstance(message_key, str) and message_key else None,
    )


# ── Dispatch guard helpers ───────────────────────────────────────────────────


def _record_resume_id(record: dict[str, Any] | None) -> str | None:
    if not isinstance(record, dict):
        return None
    value = record.get("resume_id")
    return str(value) if value else None


def _record_expired(record: dict[str, Any]) -> bool:
    raw = record.get("expires_at")
    if not isinstance(raw, str) or not raw:
        return False
    try:
        expires_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)


def _is_same_answered_turn(guard: ResumeDispatch, live_resume_id: str | None) -> bool:
    """True when a repeat response targets the intervention already dispatched.

    A live record that differs from the guard's resume id means a *new* pause
    happened in between, so the answer must be dispatched rather than absorbed.
    """
    if live_resume_id is not None and guard.resume_id is not None:
        return live_resume_id == guard.resume_id
    # The intervened turn already closed (no live record): the guard holds its
    # stored outcome.
    return True


def _is_retryable_dispatch(guard: ResumeDispatch) -> bool:
    """True when the guard records a dispatch that never reached the turn.

    A dispatch failure (Agent Runtime unreachable / rejected before the claim)
    leaves the pause answerable, so a repeat must be allowed to retry rather
    than being absorbed as an already-resolved outcome.  A task that died
    without settling is treated the same way.
    """
    if guard.state == _DISPATCH_COMPLETED:
        return guard.status == RESUME_STATUS_DISPATCH_FAILED
    if guard.task is not None and guard.task.done():
        return True
    return False



def _deduplicated_response(
    conversation_session_id: uuid.UUID, guard: ResumeDispatch
) -> AgentResumeResponse:
    if guard.state == _DISPATCH_IN_FLIGHT:
        logger.info(
            "Resume dispatch de-duplicated for conversation %s (in flight, "
            "resume_id=%s)",
            conversation_session_id,
            guard.resume_id,
        )
        return AgentResumeResponse(
            session_id=conversation_session_id,
            status=RESUME_STATUS_ALREADY_RESOLVED,
            reason="in_flight",
            resume_id=guard.resume_id,
            deduplicated=True,
        )
    logger.info(
        "Resume outcome short-circuited for conversation %s (stored status=%s "
        "reason=%s)",
        conversation_session_id,
        guard.status,
        guard.reason,
    )
    return AgentResumeResponse(
        session_id=conversation_session_id,
        status=guard.status,
        reason=guard.reason,
        resume_id=guard.resume_id,
        write_applied=guard.write_applied,
        deduplicated=True,
    )


# ── Conversation-scoped background dispatch ──────────────────────────────────


async def _activity_heartbeat_loop(
    app: Any,
    conversation_session_id: uuid.UUID,
    stop: asyncio.Event,
) -> None:
    """Keep the resumed turn's persisted activity fresh while it streams.

    A resumed turn can be silent for a long time (one slow tool call, a long
    model completion) without emitting a status event. Control Center's
    staleness bound is short by design (a dead turn must resolve quickly), so a
    live resumed turn has to keep beating exactly like a first turn does through
    the WebSocket heartbeat. Reuses the single touch helper in ``app.api.ws.chat``
    (signed tenant forwarding + the standard internal egress).
    """
    from app.api.ws.chat import (
        CONVERSATION_HEARTBEAT_INTERVAL_SECONDS,
        _touch_activity_heartbeat,
    )

    while not stop.is_set():
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=CONVERSATION_HEARTBEAT_INTERVAL_SECONDS
            )
        except asyncio.TimeoutError:
            pass
        if stop.is_set():
            return
        await _touch_activity_heartbeat(app, conversation_session_id)


async def _dispatch_conversation_resume(
    *,
    app: Any,
    conversation_session_id: uuid.UUID,
    response_value: dict[str, Any],
    record: dict[str, Any],
    dispatch: ResumeDispatch,
) -> None:
    """Supervise one streamed AR resume, then record its stored outcome."""
    # FIX-20261113: beat the persisted activity while the resumed turn streams,
    # so a quiet-but-live resumed turn is never resolved by the activity reaper.
    stop_heartbeat = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _activity_heartbeat_loop(app, conversation_session_id, stop_heartbeat)
    )
    try:
        outcome = await _stream_conversation_resume(
            app=app,
            conversation_session_id=conversation_session_id,
            response_value=response_value,
            record=record,
        )
    except asyncio.CancelledError:
        dispatch.state = _DISPATCH_COMPLETED
        dispatch.status = RESUME_STATUS_DISPATCH_FAILED
        dispatch.reason = "cancelled"
        raise
    except Exception:  # noqa: BLE001 - the guard must always settle
        logger.exception(
            "Resume dispatch failed for conversation %s", conversation_session_id
        )
        dispatch.state = _DISPATCH_COMPLETED
        dispatch.status = RESUME_STATUS_DISPATCH_FAILED
        dispatch.reason = "dispatch_failed"
        return
    finally:
        stop_heartbeat.set()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            # The dispatch itself was cancelled: never leave the beat running.
            heartbeat_task.cancel()
            raise
        except Exception:  # noqa: BLE001 - a heartbeat failure is never fatal
            logger.debug(
                "Resume activity heartbeat stopped with an error for "
                "conversation %s",
                conversation_session_id,
                exc_info=True,
            )
    dispatch.state = _DISPATCH_COMPLETED
    dispatch.status = outcome.status
    dispatch.reason = outcome.reason
    dispatch.write_applied = outcome.write_applied
    logger.info(
        "Resume dispatch finished for conversation %s: status=%s reason=%s",
        conversation_session_id,
        outcome.status,
        outcome.reason,
    )


def _ar_client_configuration(app: Any, ar_base: str) -> tuple[dict[str, Any], dict[str, str]]:
    """Build the AR egress kwargs/headers (CH service cert, forwarded tenant set).

    Tenant headers are attached by ``internal_httpx_client`` (the verified
    CC-signed set is forwarded verbatim — Communication Hub never signs).
    """
    client_kwargs: dict[str, Any] = {
        # The resumed turn streams status events; never time out the read side.
        "timeout": httpx.Timeout(connect=15.0, read=None, write=30.0, pool=30.0),
        "verify": get_ssl_context(),
    }
    headers: dict[str, str] = {}
    cert_manager = getattr(app.state, "certificate_manager", None)
    if cert_manager and cert_manager.cert_path and cert_manager.key_path:
        if ar_base.startswith("https://"):
            client_kwargs["cert"] = (
                str(cert_manager.cert_path),
                str(cert_manager.key_path),
            )
        else:
            cert_content = Path(cert_manager.cert_path).read_text()
            headers["X-Client-Certificate"] = cert_content.replace("\n", "\\n")
    else:
        logger.warning(
            "No certificate manager available — Agent Runtime resume may fail "
            "authentication"
        )
    return client_kwargs, headers


async def _stream_conversation_resume(
    *,
    app: Any,
    conversation_session_id: uuid.UUID,
    response_value: dict[str, Any],
    record: dict[str, Any],
) -> ConversationResumeOutcome:
    """Call AR's durable resume route in streaming mode and act on the stream."""
    settings = get_settings()
    ar_base = (settings.agent_runtime_url or "http://localhost:8001").rstrip("/")
    endpoint = f"{ar_base}{AR_CONVERSATION_RESUME_PATH}"
    client_kwargs, headers = _ar_client_configuration(app, ar_base)
    payload = {
        "conv_session_id": str(conversation_session_id),
        "response_value": response_value or {},
        "stream_status_events": True,
    }

    status_events: list[dict[str, Any]] = []
    final_response: str | None = None
    guardrail_usage: dict[str, Any] | None = None
    try:
        async with internal_httpx_client(**client_kwargs) as client:
            async with client.stream("POST", endpoint, json=payload, headers=headers) as response:
                if response.status_code == 409:
                    # Another instance holds the turn claim: serialised, not an
                    # error and never a terminal outcome.
                    logger.info(
                        "Resume already in flight elsewhere for conversation %s "
                        "(AR claim contention)",
                        conversation_session_id,
                    )
                    return ConversationResumeOutcome(
                        status=RESUME_STATUS_RESUMED, reason="claim_held_elsewhere"
                    )
                if response.status_code >= 400:
                    body_text = (await response.aread()).decode("utf-8", "replace")[:300]
                    logger.error(
                        "Agent Runtime rejected resume for conversation %s: HTTP %s — %s",
                        conversation_session_id,
                        response.status_code,
                        body_text,
                    )
                    return ConversationResumeOutcome(
                        status=RESUME_STATUS_DISPATCH_FAILED,
                        reason=f"http_{response.status_code}",
                    )
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Unparseable resume chunk for conversation %s",
                            conversation_session_id,
                        )
                        continue
                    chunk_type = chunk.get("type")
                    if chunk_type == "status_event":
                        normalized = await _forward_resume_status_event(
                            app, conversation_session_id, chunk.get("event")
                        )
                        if normalized is not None:
                            status_events.append(normalized)
                        continue
                    if chunk_type == "final":
                        final_response = str(chunk.get("response") or "")
                        guardrail_raw = chunk.get("guardrail_usage")
                        guardrail_usage = (
                            guardrail_raw if isinstance(guardrail_raw, dict) else None
                        )
                        break
                    if chunk_type == "paused":
                        pause = chunk.get("pause") if isinstance(chunk.get("pause"), dict) else None
                        logger.info(
                            "Resumed turn paused again for conversation %s "
                            "(resume_id=%s)",
                            conversation_session_id,
                            (pause or {}).get("resume_id"),
                        )
                        # The reply is *not* delivered: the turn waits for the
                        # operator again.  The new pause is already persisted by
                        # Agent Runtime (checkpoint + resume index).
                        await _persist_waiting_activity(app, conversation_session_id)
                        return ConversationResumeOutcome(
                            status=RESUME_STATUS_RESUMED,
                            reason="paused_again",
                            status_events=status_events,
                            pause=pause,
                        )
                    if chunk_type == "resume_status":
                        outcome = _outcome_from_status_chunk(
                            chunk, status_events=status_events
                        )
                        if outcome.status == RESUME_STATUS_UNRESUMABLE:
                            # Control Center reports the turn durably
                            # unresumable (claim saw a terminal record): one
                            # reason-carrying terminal message.
                            await _notify_unresumable_turn(
                                app,
                                conversation_session_id,
                                reason_code=outcome.reason or "resume_failed",
                            )
                        return outcome
                    if chunk_type == "error":
                        error_type = chunk.get("error_type") or "resume_failed"
                        logger.error(
                            "Agent Runtime resume error for conversation %s: %s",
                            conversation_session_id,
                            error_type,
                        )
                        await _notify_unresumable_turn(
                            app,
                            conversation_session_id,
                            reason_code=str(error_type),
                        )
                        return ConversationResumeOutcome(
                            status=RESUME_STATUS_UNRESUMABLE,
                            reason=str(error_type),
                            status_events=status_events,
                        )
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.error(
            "Agent Runtime unreachable for resume of conversation %s: %s",
            conversation_session_id,
            exc,
        )
        # The pause is still answerable — a dispatch failure is NOT a durable
        # terminal outcome, so no terminal message is emitted.
        return ConversationResumeOutcome(
            status=RESUME_STATUS_DISPATCH_FAILED, reason="instance_unreachable"
        )
    except httpx.HTTPError as exc:
        logger.error(
            "Agent Runtime resume transport failed for conversation %s: %s",
            conversation_session_id,
            exc,
        )
        return ConversationResumeOutcome(
            status=RESUME_STATUS_DISPATCH_FAILED, reason="dispatch_failed"
        )

    if final_response is None:
        logger.warning(
            "Resume stream for conversation %s ended without a terminal chunk",
            conversation_session_id,
        )
        return ConversationResumeOutcome(
            status=RESUME_STATUS_DISPATCH_FAILED,
            reason="empty_resume_stream",
            status_events=status_events,
        )

    return await _complete_resumed_turn(
        app=app,
        conversation_session_id=conversation_session_id,
        record=record,
        response_value=response_value,
        reply=final_response,
        guardrail_usage=guardrail_usage,
        status_events=status_events,
    )


async def _forward_resume_status_event(
    app: Any, conversation_session_id: uuid.UUID, event: Any
) -> dict[str, Any] | None:
    """Forward one AR status event to the socket and persist it via CC."""
    if not isinstance(event, dict):
        return None
    status_value = event.get("status")
    if not isinstance(status_value, str) or not status_value:
        return None
    agent_type = event.get("agent_type") if isinstance(event.get("agent_type"), str) else None
    tool_name = event.get("tool_name") if isinstance(event.get("tool_name"), str) else None
    receiver = (
        event.get("receiver_session_id")
        if isinstance(event.get("receiver_session_id"), str)
        else None
    )
    timestamp = event.get("timestamp") if isinstance(event.get("timestamp"), str) else None
    message = event.get("message") if isinstance(event.get("message"), str) else None

    from app.api.ws.chat import (
        _build_chat_status_event,
        _persist_activity_transition,
        _send_to_live_socket,
    )

    normalized = _build_chat_status_event(
        status_value, agent_type, tool_name, receiver, timestamp, message
    )
    await _persist_activity_transition(
        app,
        conversation_session_id,
        status_value,
        normalized.get("agent_type"),
        normalized.get("tool_name"),
    )
    await _send_to_live_socket(
        str(conversation_session_id),
        None,
        {"type": "chat_status", **normalized},
    )
    return normalized


def _outcome_from_status_chunk(
    chunk: dict[str, Any], *, status_events: list[dict[str, Any]]
) -> ConversationResumeOutcome:
    """Map AR's non-streamed ``resume_status`` chunk onto a dispatch outcome."""
    status_value = str(chunk.get("status") or RESUME_STATUS_DISPATCH_FAILED)
    reason = chunk.get("reason")
    return ConversationResumeOutcome(
        status=status_value,
        reason=str(reason) if reason else None,
        status_events=status_events,
        write_applied=bool(chunk.get("write_applied", False)),
    )


async def _complete_resumed_turn(
    *,
    app: Any,
    conversation_session_id: uuid.UUID,
    record: dict[str, Any],
    response_value: dict[str, Any],
    reply: str,
    guardrail_usage: dict[str, Any] | None,
    status_events: list[dict[str, Any]],
) -> ConversationResumeOutcome:
    """Deliver the reply once and close the paused turn through Control Center."""
    from app.api.ws.chat import (
        _build_chat_status_event,
        _persist_terminal_activity,
        _send_to_live_socket,
    )

    # One delivery: the live socket (or the reconnected socket resolved at send
    # time).  Persistence is handled by the Control Center closer below.
    await _send_to_live_socket(
        str(conversation_session_id),
        None,
        {
            "sender_role": "agent",
            "content": reply,
            "final": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

    data_client: ControlCenterDataClient | None = getattr(app.state, "data_client", None)
    if data_client is None:
        return ConversationResumeOutcome(
            status=RESUME_STATUS_RESUMED,
            response=reply,
            guardrail_usage=guardrail_usage,
            status_events=status_events,
        )

    # Control Center owns the applied marker (the confirmed-write chokepoint
    # stamps it during the turn), so re-read it before closing the record.
    live = await _lookup_resume(app, conversation_session_id)
    live_record = live.live_record if live is not None else None
    effective_record = live_record if isinstance(live_record, dict) else record
    outcome, write_applied = _completion_outcome(response_value, effective_record)

    if live_record is None:
        # The record is already closed: nothing to close again, but the reply
        # must still land in the transcript exactly once.
        await _persist_reply_fallback(app, conversation_session_id, reply)
        return ConversationResumeOutcome(
            status=RESUME_STATUS_ALREADY_RESOLVED,
            reason="already_resolved",
            response=reply,
            status_events=status_events,
        )

    try:
        await data_client.complete_conversation_turn_resume(
            conversation_session_id,
            {
                "resume_id": effective_record.get("resume_id"),
                "outcome": outcome,
                "write_applied": write_applied,
                "outcome_turn_content": reply,
                "consume_checkpoint": True,
            },
        )
    except ControlCenterDataError as exc:
        # The lifecycle closer refused (e.g. an approval without the applied
        # marker — the exactly-once contract forbids a fabricated one).  The
        # reply is delivered; it must not be lost from the transcript, and no
        # second outcome turn may be created.
        logger.warning(
            "Resume closer deferred for conversation %s (outcome=%s): %s",
            conversation_session_id,
            outcome,
            exc,
        )
        await _persist_reply_fallback(app, conversation_session_id, reply)
        await _persist_terminal_activity(app, conversation_session_id, "finished")
        return ConversationResumeOutcome(
            status=RESUME_STATUS_RESUMED,
            reason="completion_deferred",
            response=reply,
            status_events=status_events,
        )

    await _send_to_live_socket(
        str(conversation_session_id),
        None,
        {"type": "chat_status", **_build_chat_status_event("finished")},
    )
    logger.info(
        "Resumed turn closed for conversation %s (outcome=%s write_applied=%s)",
        conversation_session_id,
        outcome,
        write_applied,
    )
    return ConversationResumeOutcome(
        status=RESUME_STATUS_RESUMED,
        reason=outcome,
        response=reply,
        guardrail_usage=guardrail_usage,
        status_events=status_events,
        write_applied=write_applied,
    )


def _completion_outcome(
    response_value: dict[str, Any], record: dict[str, Any] | None
) -> tuple[str, bool]:
    """Map the operator's answer + Control Center's applied marker to an outcome."""
    if response_value.get("approval_value") is False:
        return "denied", False
    write_applied = bool((record or {}).get("write_applied", False))
    return "approved_applied", write_applied


async def _persist_reply_fallback(
    app: Any, conversation_session_id: uuid.UUID, reply: str
) -> None:
    """Persist the reply as an agent turn when the closer could not (best effort)."""
    data_client = getattr(app.state, "data_client", None)
    if data_client is None:
        return
    try:
        await data_client.append_conversation_turn(
            conv_session_id=conversation_session_id,
            agent_reply=reply,
        )
    except Exception as exc:  # noqa: BLE001 - never fail the dispatch on persistence
        logger.warning(
            "Failed to persist resumed reply for conversation %s: %s",
            conversation_session_id,
            exc,
        )


async def _persist_waiting_activity(app: Any, conversation_session_id: uuid.UUID) -> None:
    """Ensure a re-paused turn is shown as waiting (the durable record backs it)."""
    from app.api.ws.chat import _persist_activity_transition

    await _persist_activity_transition(
        app, conversation_session_id, "waiting_for_human", None, None
    )


# ── Terminal notification (durable state only) ───────────────────────────────


async def _notify_unresumable_turn(
    app: Any,
    conversation_session_id: uuid.UUID,
    *,
    reason_code: str,
    message_key: str | None = None,
    write_applied: bool = False,
) -> None:
    """Emit exactly one terminal status for a *durably* unresumable turn.

    The payload carries Control Center's reason code and a reason-specific,
    actionable message — never a hardcoded "a service restart happened" string.
    Delivery is best effort: with no live socket the persisted terminal
    activity carries the same state forward to the next hydration.
    """
    from app.api.ws.chat import (
        ActiveSessionTracker,
        _build_chat_status_event,
        _persist_terminal_activity,
        _send_to_live_socket,
    )

    status_value = terminal_status_for_reason(reason_code)
    message = terminal_message_for_reason(reason_code, write_applied=write_applied)
    payload: dict[str, Any] = {
        "type": "chat_status",
        **_build_chat_status_event(status_value, message=message),
        "reason": reason_code,
        "terminal_reason_code": reason_code,
        "resume_state": "unresumable",
    }
    if message_key:
        payload["terminal_message_key"] = message_key

    notification_key = f"{conversation_session_id}:{reason_code}"
    now = time.monotonic()
    last_sent = _TERMINAL_NOTIFIED.get(notification_key)
    if last_sent is not None and (now - last_sent) < _TERMINAL_NOTIFICATION_TTL_SECONDS:
        logger.debug(
            "Terminal notification already delivered for conversation %s "
            "(reason=%s) — not repeating",
            conversation_session_id,
            reason_code,
        )
        return

    # Persist first: the hydrated activity then carries the same terminal state
    # even when no socket is connected (offline client sees it on reconnect).
    await _persist_terminal_activity(
        app,
        conversation_session_id,
        status_value,
        detail={
            "resume_state": "unresumable",
            "terminal_reason_code": reason_code,
            **({"terminal_message_key": message_key} if message_key else {}),
        },
    )
    _TERMINAL_NOTIFIED[notification_key] = now


    if not ActiveSessionTracker.is_connected(str(conversation_session_id)):
        logger.info(
            "Unresumable turn for conversation %s (reason=%s): no live WebSocket "
            "client — terminal state persisted for the next hydration",
            conversation_session_id,
            reason_code,
        )
        return
    await _send_to_live_socket(
        str(conversation_session_id),
        None,
        payload,
    )
    logger.warning(
        "Terminal notification emitted for durably unresumable turn "
        "conversation=%s reason_code=%s terminal_message_key=%s",
        conversation_session_id,
        reason_code,
        message_key,
    )


# ── Legacy (agent-job) forwarding path ───────────────────────────────────────


async def _forward_legacy_resume(
    session_id: uuid.UUID,
    body: AgentResumeRequest,
    request: Request,
) -> AgentResumeResponse:
    """Forward a resume to Agent Runtime's legacy route (job sessions).

    Retry behaviour is unchanged from the pre-durable implementation: transient
    Agent Runtime failures are retried, a 4xx rejection is surfaced as 502.
    """
    settings = get_settings()
    ar_base = settings.agent_runtime_url or "http://localhost:8001"
    ar_endpoint = f"{ar_base}{AR_LEGACY_RESUME_PATH}"
    client_kwargs, headers = _legacy_client_configuration(request.app, ar_base)

    payload: dict[str, Any] = {"session_id": str(session_id)}
    if body.response_value:
        payload["response_value"] = body.response_value

    max_retries = 3
    retry_delays = [0, 2, 4]
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                delay = retry_delays[attempt]
                logger.info(
                    "Retrying Agent Runtime resume (attempt %d/%d) after %ds "
                    "delay: session=%s",
                    attempt + 1,
                    max_retries,
                    delay,
                    session_id,
                )
                await asyncio.sleep(delay)

            async with internal_httpx_client(**client_kwargs) as client:
                response = await client.post(
                    ar_endpoint,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                result = response.json()

                logger.info(
                    "Agent resume forwarded successfully: session=%s status=%s "
                    "(attempt %d/%d)",
                    session_id,
                    result.get("status"),
                    attempt + 1,
                    max_retries,
                )
                resumed_status = str(result.get("status", RESUME_STATUS_RESUMED))
                reason = result.get("reason")
                return AgentResumeResponse(
                    session_id=uuid.UUID(str(result.get("session_id") or session_id)),
                    status=resumed_status,
                    reason=str(reason) if reason else None,
                )

        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response.status_code < 500:
                error_msg = (
                    f"Agent Runtime rejected resume: HTTP {exc.response.status_code}"
                )
                logger.error("%s — %s", error_msg, exc.response.text[:200])
                raise HTTPException(status_code=502, detail=error_msg) from exc
            logger.warning(
                "Agent Runtime returned HTTP %d (attempt %d/%d): %s",
                exc.response.status_code,
                attempt + 1,
                max_retries,
                exc.response.text[:200],
            )

        except httpx.TimeoutException as exc:
            last_error = exc
            logger.warning(
                "Agent Runtime resume timeout (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                exc,
            )

        except httpx.ConnectError as exc:
            last_error = exc
            logger.warning(
                "Agent Runtime resume connection failed (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                exc,
            )

        except Exception as exc:  # noqa: BLE001 - retried below
            last_error = exc
            logger.exception(
                "Agent resume forward failed unexpectedly (attempt %d/%d)",
                attempt + 1,
                max_retries,
            )

    if isinstance(last_error, (httpx.ConnectError, httpx.TimeoutException)):
        error_msg = (
            "Agent Runtime unavailable after retries — request timed out or "
            "connection failed"
        )
        logger.error("%s: session=%s", error_msg, session_id)
        raise HTTPException(status_code=503, detail=error_msg)
    error_msg = (
        f"Failed to forward agent resume after {max_retries} retries: {last_error}"
    )
    logger.error("%s: session=%s", error_msg, session_id)
    raise HTTPException(status_code=502, detail=error_msg)


def _legacy_client_configuration(app: Any, ar_base: str) -> tuple[dict[str, Any], dict[str, str]]:
    """Bounded-timeout AR egress configuration for the legacy resume route."""
    client_kwargs: dict[str, Any] = {"timeout": 30.0, "verify": get_ssl_context()}
    headers: dict[str, str] = {}
    cert_manager = getattr(app.state, "certificate_manager", None)
    if cert_manager and cert_manager.cert_path and cert_manager.key_path:
        if ar_base.startswith("https://"):
            client_kwargs["cert"] = (
                str(cert_manager.cert_path),
                str(cert_manager.key_path),
            )
            logger.debug("Using mTLS certificate for Agent Runtime resume")
        else:
            cert_content = Path(cert_manager.cert_path).read_text()
            headers["X-Client-Certificate"] = cert_content.replace("\n", "\\n")
            logger.debug("Using X-Client-Certificate header for Agent Runtime resume")
    else:
        logger.warning(
            "No certificate manager available — Agent Runtime call may fail "
            "authentication"
        )
    return client_kwargs, headers


__all__ = [
    "AR_CONVERSATION_RESUME_PATH",
    "AR_LEGACY_RESUME_PATH",
    "AgentResumeRequest",
    "AgentResumeResponse",
    "RESUME_STATUS_ALREADY_RESOLVED",
    "RESUME_STATUS_DISPATCH_FAILED",
    "RESUME_STATUS_IN_FLIGHT",
    "RESUME_STATUS_NOT_AWAITING",
    "RESUME_STATUS_RESUMED",
    "RESUME_STATUS_UNRESUMABLE",
    "forward_resume_session",
    "reset_resume_dispatch_state",
    "router",
    "terminal_message_for_reason",
    "terminal_status_for_reason",
]
