"""Terminal resolution for paused conversational turns (Control Center).

One paused turn has three possible endings and Control Center owns all three:

* **resumed** — Agent Runtime continued the turn and Communication Hub closed
  it through the single-transaction ``complete`` endpoint;
* **already terminal** — the resume record was closed before (a duplicate
  operator answer returns the stored outcome instead of re-dispatching);
* **unresumable** — the turn can never continue (window expired, saved state
  gone, answer abandoned).  The record is closed with a *reason code* and
  exactly one reason-keyed outcome turn is appended, guarded by
  ``outcome_turn_id`` so repeated responses can never produce a second turn.

This module is also the answer-path advance: the operator's answer and the
resume record transition (``waiting_for_human`` → ``resuming``, answering user,
attempt) commit in the **same transaction** as the stored response, so a
committed answer always has a dispatched turn behind it and a rolled-back
answer never leaves a half-advanced record.

Every unresumable path leaves ``write_applied`` false — a denial, an expiry, or
a lost pause point must never claim the confirmed action was applied.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation_activity import ActivityState
from app.db.models.conversation_turn_resume import ConversationTurnResume
from app.db.models.conversations import TurnRole, TurnType
from app.db.models.intervene import InterveneRequest, InterveneRequestStatus
from app.services.conversations.activity_store import ConversationActivityStore
from app.services.conversations.store import ConversationStore
from app.services.conversations.turn_checkpoint_store import (
    ConversationTurnCheckpointStore,
)
from app.services.conversations.turn_resume_store import (
    ConversationTurnResumeStore,
    TurnResumeTransitionError,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.core.tenant_context import TenantContext

logger = logging.getLogger(__name__)

# ── Terminal reason vocabulary ───────────────────────────────────────────────
#: Why a paused turn can never continue.  The same vocabulary is rendered by
#: Communication Hub for live `chat_status` messages and hydrated by the UI.
REASON_EXPIRED = "expired"
REASON_SUPERSEDED = "superseded"
REASON_CANCELLED = "cancelled"
REASON_CHECKPOINT_UNAVAILABLE = "checkpoint_unavailable"
REASON_CHECKPOINT_CONSUMED = "checkpoint_consumed"
REASON_RESUME_FAILED = "resume_failed"
#: The turn stopped while it was still working (heartbeat stopped → the turn
#: died, e.g. a server restart/crash) before finishing.  Distinct from
#: ``resume_failed`` (a pause that could not be restarted) and ``cancelled``
#: (a deliberate stop): nothing was applied and the request can simply be
#: repeated.
REASON_UNEXPECTEDLY_TERMINATED = "unexpectedly_terminated"

#: User-facing text per reason code.  Each names what happened *and* the next
#: step; none of them claims a confirmed write was applied.
REASON_MESSAGES: dict[str, str] = {
    REASON_EXPIRED: (
        "This confirmation was not answered within its validity window and has "
        "now expired. Nothing was applied — ask again to generate a fresh "
        "preview."
    ),
    REASON_SUPERSEDED: (
        "A newer confirmation replaced this one, so it can no longer be "
        "answered. Nothing was applied — ask again if you still need it."
    ),
    REASON_CANCELLED: (
        "This confirmation was cancelled, so the paused turn cannot continue. "
        "Nothing was applied."
    ),
    REASON_CHECKPOINT_UNAVAILABLE: (
        "The paused turn can no longer be restored because its saved state is "
        "unavailable. Nothing was applied — ask again to repeat the request."
    ),
    REASON_CHECKPOINT_CONSUMED: (
        "The paused turn's saved state was already used, so it cannot be "
        "restored again. Nothing was applied — ask again to repeat the request."
    ),
    REASON_RESUME_FAILED: (
        "The paused turn could not be resumed. Nothing was applied — ask again "
        "to repeat the request."
    ),
    REASON_UNEXPECTEDLY_TERMINATED: (
        "The assistant stopped unexpectedly (e.g. a server restart) before "
        "finishing. Nothing was applied. Please resend your request or ask "
        "again."
    ),
}

DEFAULT_REASON_MESSAGE = (
    "This confirmation can no longer be resumed. Nothing was applied — ask "
    "again to repeat the request."
)

#: i18n keys mirrored onto the record (the UI's authoritative message key).
REASON_MESSAGE_KEYS: dict[str, str] = {
    REASON_EXPIRED: "chat.resume.expired",
    REASON_SUPERSEDED: "chat.resume.superseded",
    REASON_CANCELLED: "chat.resume.cancelled",
    REASON_CHECKPOINT_UNAVAILABLE: "chat.resume.checkpointUnavailable",
    REASON_CHECKPOINT_CONSUMED: "chat.resume.checkpointConsumed",
    REASON_RESUME_FAILED: "chat.resume.failed",
    REASON_UNEXPECTEDLY_TERMINATED: "chat.resume.unexpectedlyTerminated",
}

#: Reasons that mean "the answer window closed" — surfaced as a timeout.
EXPIRY_REASON_CODES = frozenset({REASON_EXPIRED})


def outcome_message_for_reason(reason_code: str | None) -> str:
    """Render the actionable outcome text for a terminal reason code."""
    key = (reason_code or "").strip()
    return REASON_MESSAGES.get(key, DEFAULT_REASON_MESSAGE)


def message_key_for_reason(reason_code: str | None) -> str | None:
    """Return the i18n key mirrored onto the resume record (or ``None``)."""
    return REASON_MESSAGE_KEYS.get((reason_code or "").strip())


def terminal_activity_state_for_reason(reason_code: str | None) -> ActivityState:
    """Map a terminal reason onto the persisted activity state.

    An expiry is a timeout; everything else is a failure to resume.
    """
    return (
        ActivityState.timed_out
        if (reason_code or "") in EXPIRY_REASON_CODES
        else ActivityState.failed
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stored_reason(record: ConversationTurnResume) -> str | None:
    """The record's stored terminal reason (code first, then the outcome)."""
    if record.terminal_reason_code:
        return record.terminal_reason_code
    outcome = record.resume_outcome
    if outcome is None:
        return None
    return outcome.value if hasattr(outcome, "value") else str(outcome)


def _ensure_tz(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def window_elapsed(record: ConversationTurnResume, *, now: datetime | None = None) -> bool:
    """True when the record's answerable window has passed."""
    expires_at = _ensure_tz(record.expires_at)
    return expires_at is not None and expires_at <= (now or _utcnow())


# ── Answer path: advance the record in the response transaction ─────────────


@dataclass
class AnsweredTurn:
    """Outcome of advancing the resume record for an answered intervention.

    ``dispatch`` is False for every terminal answer: a duplicate answer returns
    the stored outcome and an expired window closes the record, and neither may
    start a resume.
    """

    resume: ConversationTurnResume | None = None
    #: True when a resume must be dispatched for this answer.
    dispatch: bool = False
    #: True when the record is already terminal (stored outcome returned).
    already_terminal: bool = False
    #: True when the answerable window had elapsed (record closed as expired).
    expired: bool = False
    reason_code: str | None = None
    outcome_turn_id: uuid.UUID | None = None

    @property
    def resume_id(self) -> uuid.UUID | None:
        return self.resume.id if self.resume is not None else None

    @property
    def resume_key(self) -> str | None:
        return self.resume.resume_key if self.resume is not None else None


async def _mark_activity_processing(
    db: AsyncSession,
    conversation_session_id: uuid.UUID | None,
    resume_id: uuid.UUID,
) -> None:
    """Move a just-answered pause's activity out of ``waiting_for_human``.

    Once the operator has answered, the persisted activity must stop reading as
    a *pending* pause immediately. Otherwise a reconnect hydration or a
    watchdog ``status_pong`` re-surfaces "waiting for your input" for a turn
    that is already processing again. Only a still-waiting row is touched — a
    live runtime transition always wins.
    """
    if conversation_session_id is None:
        return
    store = ConversationActivityStore()
    activity = await store.get(conversation_session_id, db)
    if activity is None or activity.state is not ActivityState.waiting_for_human:
        return
    await store.upsert(
        conversation_session_id,
        db,
        ActivityState.thinking,
        active_resume_id=resume_id,
    )


async def _answered_record(
    db: AsyncSession,
    intervene_request: InterveneRequest,
) -> ConversationTurnResume | None:
    """Resolve the resume record a just-answered intervention belongs to."""
    store = ConversationTurnResumeStore()
    record = await store.get_for_intervention(intervene_request.id, db)
    if record is not None:
        return record
    if intervene_request.conversation_session_id is not None:
        return await store.get_live_for_session(
            intervene_request.conversation_session_id, db
        )
    return None


async def advance_answered_intervention(
    db: AsyncSession,
    intervene_request: InterveneRequest,
    *,
    operator_user_id: uuid.UUID | None,
    now: datetime | None = None,
) -> AnsweredTurn:
    """Advance the live resume record in the operator-answer transaction.

    Must be called **before** the caller commits the stored response:

    * already terminal → no state change, no dispatch (stored outcome wins);
    * answerable window elapsed → close as ``unresumable/expired`` and append
      the reason-keyed outcome turn, no dispatch;
    * otherwise → stamp the answering user and move to ``resuming``.
    """
    if intervene_request.conversation_session_id is None:
        # Agent-job interventions keep their legacy suspension path (the caller
        # dispatches through the job resume route, never the conversational one).
        return AnsweredTurn()

    record = await _answered_record(db, intervene_request)
    if record is None:
        # No durable record (legacy pause): the caller's dispatch still runs.
        return AnsweredTurn(dispatch=True)

    if record.is_terminal:
        logger.info(
            "Answered intervention %s targets terminal resume %s (%s) — "
            "returning the stored outcome",
            intervene_request.id,
            record.id,
            record.resume_outcome,
        )
        return AnsweredTurn(
            resume=record,
            already_terminal=True,
            reason_code=_stored_reason(record),
            outcome_turn_id=record.outcome_turn_id,
        )

    if window_elapsed(record, now=now):
        logger.info(
            "Answered intervention %s outside its answerable window (resume "
            "%s) — closing as unresumable/expired with no dispatch",
            intervene_request.id,
            record.id,
        )
        resolved = await resolve_unresumable_turn(
            db,
            intervene_request.conversation_session_id,
            reason_code=REASON_EXPIRED,
            resume=record,
            intervene_request_id=intervene_request.id,
        )
        return AnsweredTurn(
            resume=resolved or record,
            expired=True,
            reason_code=REASON_EXPIRED,
            outcome_turn_id=(resolved or record).outcome_turn_id,
        )

    advanced = await ConversationTurnResumeStore().mark_resuming(
        record.id, db, applied_by_user_id=operator_user_id
    )
    # The pause is answered: flip the persisted activity to processing in the
    # same transaction so no hydration/pong can resurrect the pending bar.
    await _mark_activity_processing(
        db, intervene_request.conversation_session_id, advanced.id
    )
    logger.info(
        "Answered intervention %s → resume %s resuming (attempt=%s)",
        intervene_request.id,
        advanced.id,
        advanced.attempt_count,
    )
    return AnsweredTurn(resume=advanced, dispatch=True)


# ── Live-test approval: consume once, then (and only then) run ──────────────


@dataclass
class LiveTestDecision:
    """What the answer path must do about a live-test approval.

    ``handled`` is False for every ordinary ask/decide intervention (the existing
    chain runs untouched). ``expired`` means the answer arrived too late: the
    ledger row and its paused turn are already settled as expired, so the caller
    must not record the answer or dispatch a resume.
    """

    handled: bool = False
    request_id: uuid.UUID | None = None
    status: str | None = None
    expired: bool = False
    #: True when this answer owns the one execution attempt.
    should_execute: bool = False
    #: Values merged into the resume value (the paused tool returns them).
    resume_payload: dict[str, Any] = field(default_factory=dict)


async def prepare_live_test_decision(
    db: AsyncSession,
    intervene_request: InterveneRequest,
    *,
    approved: bool | None,
) -> LiveTestDecision:
    """Apply the operator decision to a linked live-test request (pre-commit).

    Must run in the same transaction as the stored answer, and **before**
    ``advance_answered_intervention``:

    * no linked request → ``handled=False`` (ordinary question/approval);
    * request already terminal → return its stored outcome, never execute;
    * request overdue → close it ``expired`` and settle the pause as
      ``unresumable/expired`` (one bounded-stop turn, no retry);
    * approval → ``approved`` + this answer owns the execution attempt;
    * denial / no approval value → ``denied``; nothing may ever run.
    """
    from app.services.agents.optimization_live_test_service import (
        TERMINAL_STATUSES,
        get_live_test_service,
        outcome_of,
        status_value,
    )

    service = get_live_test_service()
    row = await service.get_for_intervention(db, intervene_request.id)
    if row is None:
        return LiveTestDecision()

    if row.status in TERMINAL_STATUSES:
        logger.info(
            "Live-test request %s is already %s — returning its stored outcome "
            "without executing anything",
            row.id,
            status_value(row.status),
        )
        outcome = outcome_of(row)
        return LiveTestDecision(
            handled=True,
            request_id=row.id,
            status=outcome.status,
            # A request the sweep already closed as expired can no longer be
            # answered: the answer path must refuse it (nothing runs, no
            # resume) instead of recording a decision for a dead request.
            expired=outcome.status == "expired",
            resume_payload=outcome.resume_payload(),
        )

    if service.is_overdue(row):
        logger.info(
            "Live-test request %s expired before the answer — closing the "
            "paused turn as unresumable/expired",
            row.id,
        )
        await service.mark_expired(db, row)
        await expire_and_settle_live_test(db, row)
        outcome = outcome_of(row)
        return LiveTestDecision(
            handled=True,
            request_id=row.id,
            status=outcome.status,
            expired=True,
            resume_payload=outcome.resume_payload(),
        )

    if approved is True:
        await service.mark_approved(db, row)
        return LiveTestDecision(
            handled=True,
            request_id=row.id,
            status="approved",
            should_execute=True,
        )

    await service.mark_denied(db, row)
    outcome = outcome_of(row)
    return LiveTestDecision(
        handled=True,
        request_id=row.id,
        status=outcome.status,
        resume_payload=outcome.resume_payload(),
    )


async def expire_and_settle_live_test(
    db: AsyncSession, row: Any
) -> None:
    """Close an overdue live-test request and its paused turn (idempotent)."""
    from app.services.agents.optimization_live_test_service import (
        get_live_test_service,
    )

    await get_live_test_service().settle_expired_pause(db, row)


async def execute_approved_live_test(
    db: AsyncSession,
    live_test_request_id: uuid.UUID,
    *,
    tenant_context: "TenantContext | None" = None,
) -> dict[str, Any]:
    """Run an approved live test ONCE and persist its evidence.

    A live test runs the approved **script** end to end — never an individual
    MCP tool call; MCP tools are assumed to work.

    Called **after** the answer transaction commits and **before** the resume is
    dispatched, so the paused tool receives what actually ran:

    1. the single-shot transition claims the execution (a second attempt finds
       nothing and returns the stored outcome — it never runs);
    2. the approved version's ``python_source`` (plus the reference execution's
       input, so the script runs the real scenario) is forwarded to
       ``CH → AR``, which executes the script once in the real sandbox under
       the subject agent type's own identity, tenant and existing grants;
    3. the script-run record (result summary, per-call outcomes, telemetry,
       duration) is persisted on the ledger row and returned.

    Transport failures are terminal for the run (``failed``): nothing is retried
    and the session stays replay-only.
    """
    from app.services.agents.optimization_live_test_service import (
        get_live_test_service,
        outcome_of,
    )

    service = get_live_test_service()
    row = await service.get(db, live_test_request_id)
    if row is None:
        logger.warning(
            "Live-test request %s vanished before execution", live_test_request_id
        )
        return {"live_test_status": "failed", "live_test_error": "not_found"}

    if row.status.value in {s.value for s in _terminal_status_values()}:
        return outcome_of(row).resume_payload()

    # Capture everything needed for the run BEFORE the claim commit expires the
    # ORM instance (a post-commit lazy refresh would break in async SQLAlchemy).
    conversation_session_id = row.conversation_session_id
    target_agent_type_id = row.target_agent_type_id
    script_version_id = row.script_version_id

    claimed = await service.begin_execution(db, live_test_request_id)
    # Commit the claim before the network run: the single-use gate must hold
    # even if this process dies mid-run.
    await db.commit()
    if not claimed:
        refreshed = await service.get(db, live_test_request_id)
        if refreshed is None:
            return {"live_test_status": "failed", "live_test_error": "not_found"}
        return outcome_of(refreshed).resume_payload()

    started_at = datetime.now(timezone.utc)
    executed_operations: list[dict[str, Any]] = []
    failed = False
    error_text: str | None = None

    # ── The approved script (the unit of execution) ─────────────────────────
    script_name: str | None = None
    script_version_label: str | None = None
    python_source: str | None = None
    input_context: dict[str, Any] = {}
    try:
        (
            python_source,
            script_name,
            script_version_label,
            input_context,
        ) = await _load_approved_script(
            db,
            tenant_id=row.tenant_id,
            target_agent_type_id=target_agent_type_id,
            script_version_id=script_version_id,
        )
    except Exception as exc:  # noqa: BLE001 — the ledger must always settle
        logger.exception(
            "Live-test request %s: could not load the approved script",
            live_test_request_id,
        )
        error_text = f"The approved script could not be loaded: {exc}"

    if python_source:
        try:
            from app.services.control_center.comm_hub_client import (
                CommunicationHubClient,
                CommunicationHubClientError,
            )

            result = await CommunicationHubClient().forward_live_test(
                live_test_request_id=str(live_test_request_id),
                conversation_session_id=str(conversation_session_id),
                target_agent_type_id=str(target_agent_type_id),
                script_version_id=(
                    str(script_version_id) if script_version_id else None
                ),
                script_name=script_name,
                script_version_label=script_version_label,
                python_source=python_source,
                input_context=input_context,
                tenant_context=tenant_context,
            )
            executed_operations = [
                record
                for record in (result.get("executed_operations") or [])
                if isinstance(record, dict)
            ]
            failed = str(result.get("status") or "") != "executed"
            error_text = result.get("error")
        except CommunicationHubClientError as exc:
            failed = True
            error_text = f"Live test could not run: {exc}"
            logger.warning(
                "Live-test request %s run failed (transport): %s",
                live_test_request_id,
                exc,
            )
        except Exception as exc:  # noqa: BLE001 — the ledger must always settle
            failed = True
            error_text = f"Live test could not run: {exc}"
            logger.exception("Live-test request %s run failed", live_test_request_id)
    else:
        failed = True
        error_text = error_text or (
            "The approved script version has no source to run; nothing was executed"
        )

    finished_at = datetime.now(timezone.utc)
    if not executed_operations and failed:
        # Always leave one script-run record so the audit says what happened.
        executed_operations = [
            service.build_script_run_record(
                script_version_id=script_version_id,
                script_name=script_name,
                script_version_label=script_version_label,
                status="error",
                result_summary=None,
                tool_calls=None,
                telemetry=None,
                duration_ms=int((finished_at - started_at).total_seconds() * 1000),
                error=error_text,
            )
        ]

    await service.complete_execution(
        db,
        live_test_request_id,
        executed_operations=executed_operations,
        failed=failed,
        started_at=started_at,
        finished_at=finished_at,
    )
    await db.commit()

    payload = {
        "live_test_status": "failed" if failed else "executed",
        "live_test_request_id": str(live_test_request_id),
        "script_version_id": str(script_version_id) if script_version_id else None,
        "executed_operations": executed_operations,
    }
    if executed_operations:
        payload["script_run"] = executed_operations[0]
    if error_text:
        payload["live_test_error"] = str(error_text)
    await push_live_test_result(conversation_session_id, payload)
    logger.info(
        "Live-test request %s completed → %s (script %s, %d tool call(s))",
        live_test_request_id,
        payload["live_test_status"],
        script_name or script_version_id or "?",
        len((payload.get("script_run") or {}).get("tool_calls") or []),
    )
    return payload


async def _load_approved_script(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None,
    target_agent_type_id: uuid.UUID,
    script_version_id: uuid.UUID | None,
) -> tuple[str | None, str | None, str | None, dict[str, Any]]:
    """Load the approved version's source (+ the reference input it runs with).

    Returns ``(python_source, script_name, script_version_label, input)``.
    The source must still exist and must still belong to the subject agent type
    — a version that was retired or repointed is never run.
    """
    if script_version_id is None:
        return None, None, None, {}

    from app.services.script_registry import ScriptRegistryService

    service = ScriptRegistryService()
    version = await service.get_version(db, script_version_id, tenant_id)
    if version is None or not (version.python_source or "").strip():
        return None, None, None, {}

    definition = (
        await service.get_definition(db, version.script_definition_id, tenant_id)
        if version.script_definition_id
        else None
    )
    if definition is None or definition.agent_type_id != target_agent_type_id:
        logger.warning(
            "Live-test script version %s no longer belongs to agent type %s — "
            "refusing to run it",
            script_version_id,
            target_agent_type_id,
        )
        return None, None, None, {}

    # The reference execution's input is the script's ``context`` — the same
    # payload replay verification uses, so the live run exercises the real
    # scenario. Server-derived; never supplied by the model.
    input_context: dict[str, Any] = {}
    try:
        from app.api.v1.internal.optimization_tools import (
            _build_reference_transcript,
        )

        transcript = await _build_reference_transcript(
            db,
            target_agent_type_id,
            session_id=None,
            current_session_id=None,
        )
        reference_input = transcript.get("input")
        if isinstance(reference_input, dict):
            input_context = reference_input
    except Exception:  # noqa: BLE001 — the script can still run without it
        logger.info(
            "No reference input available for live-test script %s (running with "
            "an empty context)",
            script_version_id,
            exc_info=True,
        )

    return (
        version.python_source,
        definition.name,
        version.version_label,
        input_context,
    )


def _terminal_status_values() -> Any:
    from app.services.agents.optimization_live_test_service import TERMINAL_STATUSES

    return TERMINAL_STATUSES


async def push_live_test_result(
    conversation_session_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """Best-effort live delivery of the per-operation outcomes.

    The chat replaces the pending approval card with what ran (or what failed)
    before the resumed reply arrives. Persistence already happened, so a missing
    live socket must never fail the answer.
    """
    try:
        from app.services.control_center.comm_hub_client import (
            CommunicationHubClient,
        )

        await CommunicationHubClient().dispatch_message(
            session_id=conversation_session_id,
            message_type="live_test_result",
            content={"type": "live_test_result", **payload},
        )
    except Exception:
        logger.info(
            "No live delivery of the live-test result for conversation %s "
            "(client re-fetches on reconnect)",
            conversation_session_id,
            exc_info=True,
        )


# ── Terminal resolution: one reason-keyed outcome ───────────────────────────

async def expire_linked_intervention(
    db: AsyncSession,
    record: ConversationTurnResume | None,
) -> bool:
    """Expire the still-pending confirmation of a turn that can never answer it.

    A dead pause must never leave an actionable confirmation behind: the REST
    pending-interventions fetch (``InterveneRequestStore.
    list_pending_for_conversation``) returns only ``pending`` requests, so
    expiring the linked request is what stops the UI from offering a
    confirmation whose resume record is already ``expired`` /
    ``resume_failed`` / ``superseded``.

    Only the record's own linked request is touched — an operator answer for a
    *different* request must never be closed by this path. Must be called in the
    same transaction as the resolution itself so the confirmation and the resume
    record can never disagree. Returns True when the request was expired.
    """
    if record is None or record.intervene_request_id is None:
        return False
    request = await db.get(InterveneRequest, record.intervene_request_id)
    if request is None or request.status is not InterveneRequestStatus.pending:
        return False
    request.status = InterveneRequestStatus.expired
    request.responded_at = _utcnow()
    await db.flush()
    logger.info(
        "Expired pending intervention %s — its resume record %s is %s",
        request.id,
        record.id,
        record.terminal_reason_code or "closed",
    )
    return True


async def resolve_unresumable_turn(
    db: AsyncSession,
    conversation_session_id: uuid.UUID | None,
    *,
    reason_code: str | None,
    resume: ConversationTurnResume | None = None,
    intervene_request_id: uuid.UUID | None = None,
    resume_id: uuid.UUID | None = None,
) -> ConversationTurnResume | None:
    """Close a turn as unresumable and append exactly one outcome turn.

    One caller-owned transaction: the record's terminal state, the outcome turn
    (guarded by ``outcome_turn_id``), the consumed checkpoint, and the terminal
    activity row all settle together.  Safe to call repeatedly — the second
    call finds ``outcome_turn_id`` set and appends nothing.
    """
    store = ConversationTurnResumeStore()
    record = resume
    if record is None and resume_id is not None:
        record = await store.get(resume_id, db)
    if record is None and conversation_session_id is not None:
        record = await store.get_live_for_session(conversation_session_id, db)
    if record is None and conversation_session_id is not None:
        record = await store.get_latest_for_session(conversation_session_id, db)

    session_id = (
        conversation_session_id
        or (record.conversation_session_id if record is not None else None)
    )
    code = (reason_code or REASON_RESUME_FAILED).strip()
    message_key = message_key_for_reason(code)

    if record is not None and not record.is_terminal:
        try:
            record = await store.resolve_unresumable(
                record.id,
                db,
                reason_code=code,
                message_key=message_key,
            )
        except TurnResumeTransitionError as exc:  # pragma: no cover - defensive
            logger.warning(
                "Resume %s could not be closed as unresumable (%s); leaving "
                "its stored state untouched",
                record.id,
                exc,
            )

    outcome_turn_id = record.outcome_turn_id if record is not None else None
    if session_id is not None and outcome_turn_id is None:
        existing = await _existing_outcome_turn(
            db, session_id, intervene_request_id=intervene_request_id
        )
        if existing is not None:
            outcome_turn_id = existing
        else:
            turn = await ConversationStore().add_turn(
                session_id=session_id,
                role=TurnRole.agent,
                content=outcome_message_for_reason(code),
                db=db,
                turn_type=TurnType.message,
                intervene_request_id=intervene_request_id,
            )
            outcome_turn_id = turn.id
            logger.info(
                "Persisted terminal outcome turn %s for conversation %s "
                "(reason=%s)",
                outcome_turn_id,
                session_id,
                code,
            )
    if record is not None and outcome_turn_id is not None:
        record.outcome_turn_id = outcome_turn_id

    # Resolution consumes the saved state: it can never be rebuilt again.
    if record is not None:
        await ConversationTurnCheckpointStore().mark_consumed(record.id, db)
        # A confirmation whose turn can never be answered must never stay
        # actionable: expire the pending intervention in this same transaction
        # so the REST pending list stops surfacing it.
        await expire_linked_intervention(db, record)

    if session_id is not None:
        activity_store = ConversationActivityStore()
        terminal_state = terminal_activity_state_for_reason(code)
        resolved_activity = await activity_store.resolve_terminal(
            session_id,
            db,
            state=terminal_state,
        )
        if resolved_activity is None:
            # No activity row was ever persisted for this turn (e.g. the pause
            # never reported a transition): create the terminal projection so a
            # reconnecting client hydrates the same outcome it would have seen.
            await activity_store.upsert(
                session_id,
                db,
                state=terminal_state,
                detail={
                    "terminal_reason_code": code,
                    "terminal_message_key": message_key,
                },
            )

    await db.flush()
    return record


async def _existing_outcome_turn(
    db: AsyncSession,
    conversation_session_id: uuid.UUID,
    *,
    intervene_request_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """Find an already-persisted terminal outcome turn for this pause."""
    from app.db.models.conversations import ConversationTurn

    if intervene_request_id is None:
        return None
    result = await db.execute(
        select(ConversationTurn.id)
        .where(
            ConversationTurn.session_id == conversation_session_id,
            ConversationTurn.role == TurnRole.agent,
            ConversationTurn.intervene_request_id == intervene_request_id,
            ConversationTurn.turn_type == TurnType.message,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def dispatch_answered_conversation_turn(
    db: AsyncSession,
    intervene_request: InterveneRequest,
    advance: "AnsweredTurn",
    response_value: dict,
    *,
    tenant_context: "TenantContext | None" = None,
) -> str | None:
    """Dispatch the one resume for an answered conversational turn.

    Returns the dispatch status (``None`` = transport failure or no dispatch).
    Never starts a resume for a terminal record or an elapsed window; when the
    dispatch proves the turn is durably unresumable, resolves it with a
    reason-keyed outcome (exactly one turn) and pushes it best-effort.

    ``tenant_context`` is the tenant the ANSWER was authenticated for, resolved
    by the caller from the request (or from the internal-auth dependency's
    verified context).  It is threaded explicitly because the module
    contextvar is not bound on bypassed ``/internal/*`` paths — relying on it
    dispatched the resume headerless and made the CH→CC claim relay fail 401,
    marking a still-valid turn ``unresumable``.
    """
    session_id = intervene_request.conversation_session_id
    if session_id is None:
        return None
    if advance.expired:
        # Already settled in the answer transaction — deliver the persisted
        # outcome best-effort, dispatch nothing.
        await push_outcome_message(session_id, advance.reason_code)
        return None
    if not advance.dispatch:
        return None

    from app.api.v1.intervene import _resume_agent_session
    from app.core.tenant_context import get_current_tenant_context

    # Multi-tenancy: attach the resolved tenant context so the CC→CH→AR→CH→CC
    # resume chain carries signed tenant headers. Without this the CH→CC
    # checkpoint/claim relay is headerless and CC rejects it 401, marking a
    # still-valid turn `unresumable`. The caller's explicitly threaded context
    # wins; the contextvar is only a last-resort fallback (it is NOT bound on
    # bypassed /internal/* paths). Single-tenant (both unset) → None → no
    # headers, behaviour unchanged.
    effective_tenant_context = tenant_context or get_current_tenant_context()
    status = await _resume_agent_session(
        session_id,
        response_value,
        tenant_context=effective_tenant_context,
        resume_id=advance.resume_id,
        request_id=intervene_request.id,
    )
    if is_resumable_dispatch_status(status):
        return status

    record = (
        await ConversationTurnResumeStore().get(advance.resume_id, db)
        if advance.resume_id is not None
        else None
    )
    reason = await classify_unresumable_reason(db, resume=record)
    resolved = await resolve_unresumable_turn(
        db,
        session_id,
        reason_code=reason,
        resume=record,
        intervene_request_id=intervene_request.id,
    )
    await db.commit()
    logger.info(
        "Answered turn for conversation %s is durably unresumable (dispatch "
        "status=%s reason=%s outcome_turn=%s)",
        session_id,
        status,
        reason,
        resolved.outcome_turn_id if resolved is not None else None,
    )
    await push_outcome_message(session_id, reason)
    return status


async def push_outcome_message(
    conversation_session_id: uuid.UUID,
    reason_code: str | None,
) -> None:
    """Best-effort live delivery of the reason-keyed outcome message.

    Persistence already happened (the client re-fetches turns on reconnect); a
    missing live socket must never fail the operator's answer.
    """
    message = outcome_message_for_reason(reason_code)
    try:
        from app.services.control_center.comm_hub_client import (
            CommunicationHubClient,
        )

        client = CommunicationHubClient()
        await client.dispatch_message(
            session_id=conversation_session_id,
            message_type="chat_message",
            content={
                "type": "chat_message",
                "sender_role": "agent",
                "content": message,
            },
        )
    except Exception:
        logger.info(
            "No live dispatch of the terminal outcome for conversation %s "
            "(client will re-fetch on reconnect)",
            conversation_session_id,
            exc_info=True,
        )


async def classify_unresumable_reason(
    db: AsyncSession,
    *,
    resume: ConversationTurnResume | None,
    now: datetime | None = None,
) -> str:
    """Derive the terminal reason for a turn that failed to resume.

    Prefers the record's own terminal reason, then a closed answer window, then
    a missing/consumed checkpoint (the lost pause point), and finally a generic
    resume failure.
    """
    if resume is not None:
        if resume.is_terminal and resume.terminal_reason_code:
            return resume.terminal_reason_code
        if window_elapsed(resume, now=now):
            return REASON_EXPIRED
        checkpoint = await ConversationTurnCheckpointStore().get(resume.id, db)
        if checkpoint is None:
            return REASON_CHECKPOINT_UNAVAILABLE
        if checkpoint.is_consumed:
            return REASON_CHECKPOINT_CONSUMED
    return REASON_RESUME_FAILED


def is_resumable_dispatch_status(status: str | None) -> bool:
    """True when a dispatch status means the turn is not durably unresumable.

    ``None`` is a transport failure (Communication Hub unreachable): the pause
    is still answerable, so the Terminal Resolver owns the eventual outcome
    instead of the answer path fabricating one.
    """
    if status is None:
        return True
    return status not in {"unresumable", "not_awaiting"}


__all__ = [
    "AnsweredTurn",
    "LiveTestDecision",
    "advance_answered_intervention",
    "classify_unresumable_reason",
    "dispatch_answered_conversation_turn",
    "execute_approved_live_test",
    "expire_and_settle_live_test",
    "expire_linked_intervention",
    "is_resumable_dispatch_status",
    "message_key_for_reason",
    "outcome_message_for_reason",
    "prepare_live_test_decision",
    "push_live_test_result",
    "push_outcome_message",
    "resolve_unresumable_turn",
    "terminal_activity_state_for_reason",
    "window_elapsed",
    "REASON_CANCELLED",
    "REASON_CHECKPOINT_CONSUMED",
    "REASON_CHECKPOINT_UNAVAILABLE",
    "REASON_EXPIRED",
    "REASON_RESUME_FAILED",
    "REASON_SUPERSEDED",
    "REASON_UNEXPECTEDLY_TERMINATED",
]
