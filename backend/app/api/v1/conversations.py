"""Conversations API router — session management and conversation history."""
import uuid
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from app.api.deps import get_current_claims, require_permission
from app.core.resource_types import RT_AGENT, RT_AGENT_TRAILS
from app.db.models.agents import AgentInputType, AgentType
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.db.models.identity import Identity
from app.db.session import DbSession
from app.schemas.conversations import (
    ConversationSessionCreate,
    ConversationSessionDetailRead,
    ConversationSessionPageRead,
    ConversationSessionRead,
)
from app.schemas.intervene import (
    InterveneRequestRead,
    InterveneResponseRead,
    InterveneResponseSubmit,
)
from app.schemas.optimizer import (
    LiveTestDecisionRead,
    LiveTestOperationRead,
    LiveTestRequestRead,
    OptimizationAuditRead,
    OptimizationAvailabilityRead,
    OptimizationConversationCreate,
    OptimizationConversationDetailRead,
    OptimizationConversationRead,
    OptimizationSubjectRead,
    OptimizerModelStateRead,
)
from app.services.agents.intervene_service import InterveneRequestStore
from app.services.conversations.manager import ConversationSessionManager
from app.services.conversations.store import ConversationStore

logger = logging.getLogger(__name__)

ConversationRouter = APIRouter(prefix="/conversations", tags=["Conversations"])

_store = ConversationStore()
_manager = ConversationSessionManager()
_intervene_store = InterveneRequestStore()


def _get_requesting_user_id(request: Request) -> uuid.UUID | None:
    """Extract the requesting user's canonical Identity id.

    The auth middleware resolves the authenticated human to their Identity row
    (``request.state.identity_id``) — JWTs carry no platform user id, so the
    old claims lookup always yielded None and conversations were never
    attributed to a user.
    """
    identity_id = getattr(request.state, "identity_id", None)
    if identity_id is not None:
        return identity_id
    claims = get_current_claims(request)
    user_id_str: str | None = claims.get("platform_user_id")
    return uuid.UUID(user_id_str) if user_id_str else None


# ── Optimization conversation helpers ─────────────────────────────────────────


def _optimization_subject_read(agent_type: AgentType) -> OptimizationSubjectRead:
    """The conversation's subject (the agent type being optimized)."""
    return OptimizationSubjectRead(
        agent_type_id=agent_type.id,
        name=agent_type.name,
        input_type=(
            agent_type.input_type.value
            if hasattr(agent_type.input_type, "value")
            else str(agent_type.input_type)
        ),
        is_conversational=agent_type.input_type == AgentInputType.conversation,
    )


def _availability_read(
    availability: Any,
) -> OptimizationAvailabilityRead:
    """Map the computed availability onto its API projection."""
    model = availability.optimizer_model
    return OptimizationAvailabilityRead(
        available=availability.available,
        reason_code=availability.reason_code,
        reason=availability.reason,
        can_start_work=availability.can_start_work,
        plan_present=availability.plan_present,
        optimized_plan_status=availability.optimized_plan_status,
        successful_executions=availability.successful_executions,
        optimizer_model=OptimizerModelStateRead(
            model_id=model.model_id,
            effective_model_id=model.effective_model_id,
            source=model.source,
            configured=model.configured,
            enabled=model.enabled,
            reason_code=model.reason_code,
        ),
    )


async def _operator_can_execute(db: Any, request: Request) -> bool:
    """Whether the caller holds ``agent::execute`` (the Optimize grant).

    This is availability INFORMATION (``can_start_work``), never the gate: a
    missing grant is reported on the conversation surface instead of hiding it.
    """
    from fastapi import HTTPException

    from app.api.deps import authorize_identity
    from app.core.tenant_context import optional_tenant_context

    tenant_context = optional_tenant_context(request)
    try:
        await authorize_identity(
            db,
            get_current_claims(request),
            RT_AGENT,
            "execute",
            tenant_id=tenant_context.tenant_id if tenant_context else None,
        )
        return True
    except HTTPException:
        return False
    except Exception:  # noqa: BLE001 - availability must never fail the request
        logger.warning("Optimization availability permission check failed", exc_info=True)
        return False


async def _computed_availability(
    db: Any, request: Request, agent_type: AgentType
) -> OptimizationAvailabilityRead:
    from app.services.agents.optimization_mode import (
        get_optimization_conversation_availability,
    )

    availability = await get_optimization_conversation_availability(
        db,
        agent_type,
        can_start_work=await _operator_can_execute(db, request),
    )
    return _availability_read(availability)


async def _session_audit(db: Any, session_id: uuid.UUID) -> OptimizationAuditRead:
    """Replay-vs-live projection from the raw runtime tool log.

    Delegates to the ledger service (single source of truth): replay evidence is
    an ``execute_script`` call; a live operation is a call carrying the ledger
    pointer (set only by an approved, single-use live test).
    """
    from app.services.agents.optimization_live_test_service import (
        get_live_test_service,
    )

    audit = await get_live_test_service().session_audit(db, session_id)
    return OptimizationAuditRead(
        replay_verifications=int(audit["replay_verifications"]),
        live_operations=int(audit["live_operations"]),
        last_live_at=audit["last_live_at"],
        replay_only=bool(audit["replay_only"]),
    )


async def _load_optimization_session(
    db: Any, session_id: uuid.UUID, request: Request
) -> tuple[ConversationSession, AgentType]:
    """Load the conversation for an optimization read, enforcing the guards.

    404 unknown session, 403 not the owner, 422 not an optimization
    conversation (a business/assistant conversation can never become one).
    """
    from app.services.agents.optimization_mode import OPTIMIZATION_CHANNEL

    conv_session = await db.get(ConversationSession, session_id)
    if conv_session is None:
        raise HTTPException(status_code=404, detail="Conversation session not found")

    user_id = _get_requesting_user_id(request)
    if (
        user_id
        and conv_session.triggered_by_user_id
        and user_id != conv_session.triggered_by_user_id
    ):
        raise HTTPException(
            status_code=403,
            detail="Not authorized to view this conversation",
        )

    if (conv_session.channel or "") != OPTIMIZATION_CHANNEL:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "not_optimization_conversation",
                "reason": (
                    "This conversation is not an optimization conversation; "
                    "optimization mode only applies to sessions created with "
                    "channel='optimization'."
                ),
            },
        )

    if conv_session.agent_type_id is None:
        raise HTTPException(status_code=404, detail="Agent type not found")
    agent_type = await db.get(AgentType, conv_session.agent_type_id)
    if agent_type is None:
        raise HTTPException(status_code=404, detail="Agent type not found")
    return conv_session, agent_type


@ConversationRouter.post(
    "/optimization",
    response_model=OptimizationConversationRead,
    status_code=201,
)
async def create_optimization_conversation(
    body: OptimizationConversationCreate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> OptimizationConversationRead:
    """Open an optimization conversation on the subject agent type.

    The body carries ONLY the subject (no scope / optimizer / second agent
    type). Typed and conversational agent types are both accepted: the channel
    — not ``input_type`` — decides that these turns run the conversational
    loop.

    Creation writes exactly one ``ConversationSession`` (subject, channel,
    operator, status). No optimization work starts; availability is computed
    and returned, never stored, and a missing precondition does NOT fail the
    open — the conversation is where the operator learns what is missing.
    """
    agent_type = await db.get(AgentType, body.agent_type_id)
    if agent_type is None:
        raise HTTPException(status_code=404, detail="Agent type not found")

    user_id = _get_requesting_user_id(request)
    try:
        conv_session = await _manager.create_optimization(
            agent_type_id=agent_type.id,
            triggered_by_user_id=user_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "optimization_unavailable", "reason": str(exc)},
        ) from exc

    availability = await _computed_availability(db, request, agent_type)
    return OptimizationConversationRead(
        conversation=ConversationSessionRead.model_validate(conv_session),
        subject=_optimization_subject_read(agent_type),
        availability=availability,
    )


@ConversationRouter.get(
    "/{session_id}/optimization",
    response_model=OptimizationConversationDetailRead,
)
async def get_optimization_conversation(
    session_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> OptimizationConversationDetailRead:
    """Subject + availability + replay-vs-live audit for an optimization session.

    Used on open, resume and reconnect. The subject is always the session's own
    ``agent_type_id`` — no other agent type can be named here.
    """
    conv_session, agent_type = await _load_optimization_session(
        db, session_id, request
    )
    availability = await _computed_availability(db, request, agent_type)
    audit = await _session_audit(db, session_id)
    return OptimizationConversationDetailRead(
        conversation=ConversationSessionRead.model_validate(conv_session),
        subject=_optimization_subject_read(agent_type),
        availability=availability,
        audit=audit,
    )


@ConversationRouter.get(
    "/{session_id}/live-test-requests",
    response_model=list[LiveTestRequestRead],
)
async def list_live_test_requests(
    session_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[LiveTestRequestRead]:
    """Return the session's live-test ledger, newest first.

    Read-only projection: the request list, its domain status, the execution
    evidence and the decision attribution (read from the linked
    ``InterveneResponse`` — never duplicated on the ledger row).
    """
    await _load_optimization_session(db, session_id, request)

    from app.db.models.intervene import InterveneResponse
    from app.db.models.optimization_live_test import OptimizationLiveTestRequest
    from app.services.agents.optimization_live_test_service import (
        get_live_test_service,
    )

    rows = (
        await db.execute(
            select(OptimizationLiveTestRequest)
            .where(
                OptimizationLiveTestRequest.conversation_session_id == session_id
            )
            .order_by(OptimizationLiveTestRequest.created_at.desc())
        )
    ).scalars().all()
    if not rows:
        return []

    script_labels = await get_live_test_service().script_labels(
        db, [row.script_version_id for row in rows if row.script_version_id]
    )

    intervene_ids = [row.intervene_request_id for row in rows if row.intervene_request_id]
    responses: dict[uuid.UUID, Any] = {}
    if intervene_ids:
        response_rows = (
            await db.execute(
                select(InterveneResponse).where(
                    InterveneResponse.request_id.in_(intervene_ids)
                )
            )
        ).scalars().all()
        for response in response_rows:
            responses[response.request_id] = response

    result: list[LiveTestRequestRead] = []
    for row in rows:
        response = responses.get(row.intervene_request_id) if row.intervene_request_id else None
        operations = [
            LiveTestOperationRead(
                tool_name=str(operation.get("tool_name") or ""),
                arguments=operation.get("arguments")
                if isinstance(operation.get("arguments"), dict)
                else {},
                purpose=operation.get("purpose"),
            )
            for operation in (row.requested_operations or [])
            if isinstance(operation, dict)
        ]
        result.append(
            LiveTestRequestRead(
                id=row.id,
                status=(
                    row.status.value
                    if hasattr(row.status, "value")
                    else str(row.status)
                ),
                target_agent_type_id=row.target_agent_type_id,
                script_version_id=row.script_version_id,
                script_name=script_labels.get(row.script_version_id, (None, None))[0],
                script_version_label=script_labels.get(row.script_version_id, (None, None))[1],
                requested_operations=operations,
                executed_operations=row.executed_operations,
                expires_at=row.expires_at,
                execution_started_at=row.execution_started_at,
                execution_finished_at=row.execution_finished_at,
                decision=(
                    LiveTestDecisionRead(
                        approval_value=response.approval_value,
                        operator_user_id=response.operator_user_id,
                        responded_at=response.responded_at,
                    )
                    if response is not None
                    else None
                ),
                created_at=row.created_at,
            )
        )
    return result


@ConversationRouter.post("", response_model=ConversationSessionRead, status_code=201)
async def create_conversation_session(
    body: ConversationSessionCreate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_TRAILS, "read")),
) -> ConversationSession:
    """Create a new conversation session for the given agent type."""
    user_id = _get_requesting_user_id(request)
    try:
        session = await _manager.create(
            agent_type_id=body.agent_type_id,
            triggered_by_user_id=user_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return session


@ConversationRouter.post("/{session_id}/resume", response_model=ConversationSessionDetailRead)
async def resume_conversation_session(
    session_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_TRAILS, "read")),
) -> ConversationSession:
    """Return full session context (metadata + all turns) for resuming a conversation."""
    user_id = _get_requesting_user_id(request)
    try:
        session = await _manager.resume(
            session_id=session_id,
            requesting_user_id=user_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return session


@ConversationRouter.post("/{session_id}/end", response_model=ConversationSessionRead)
async def end_conversation_session(
    session_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_TRAILS, "read")),
) -> ConversationSession:
    """Transition a conversation session to closed status.

    FIX-20261031-091657 (Defect B): also best-effort terminates any in-flight
    agent execution bound to this session (hung/slow turn) via the existing
    CC → CH → AR termination machinery; never fails the end call.
    """
    user_id = _get_requesting_user_id(request)
    try:
        session = await _manager.end(
            session_id=session_id,
            requesting_user_id=user_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    from app.services.conversations.termination import (
        terminate_in_flight_conversation_execution,
    )

    await terminate_in_flight_conversation_execution(session_id)

    # Ending the conversation closes any pending live-test approval: nothing
    # runs, and the session never re-surfaces a dead decision.
    try:
        from app.services.agents.optimization_live_test_service import (
            get_live_test_service,
        )

        if await get_live_test_service().cancel_for_session(db, session_id):
            await db.commit()
    except Exception:  # noqa: BLE001 — end must still succeed
        logger.warning(
            "Failed to cancel pending live-test requests for conversation %s",
            session_id,
            exc_info=True,
        )
    return session


@ConversationRouter.post("/{session_id}/archive", response_model=ConversationSessionRead)
async def archive_conversation_session(
    session_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_TRAILS, "read")),
) -> ConversationSession:
    """Transition a conversation session to archived status."""
    user_id = _get_requesting_user_id(request)
    try:
        session = await _manager.archive(
            session_id=session_id,
            requesting_user_id=user_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return session


@ConversationRouter.get("", response_model=list[ConversationSessionRead])
async def list_conversations(
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_TRAILS, "read")),
    agent_type_id: uuid.UUID | None = None,
    triggered_by_user_id: uuid.UUID | None = None,
    status: ConversationStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ConversationSession]:
    return await _store.list_sessions(
        db=db,
        agent_type_id=agent_type_id,
        triggered_by_user_id=triggered_by_user_id,
        status=status,
        limit=limit,
        offset=offset,
    )


@ConversationRouter.get("/{session_id}/interventions/pending", response_model=list[InterveneRequestRead])
async def list_pending_interventions_for_conversation(
    session_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_TRAILS, "read")),
):
    """Return currently pending intervention requests for a conversation session.

    Used by the frontend on reconnect to re-surface outstanding interventions.
    Returns an empty list (not error) when no pending requests exist.
    """
    # Verify session exists
    conv_session = await db.get(ConversationSession, session_id)
    if not conv_session:
        raise HTTPException(status_code=404, detail="Conversation session not found")
    # Verify ownership
    user_id = _get_requesting_user_id(request)
    if user_id and conv_session.triggered_by_user_id and user_id != conv_session.triggered_by_user_id:
        raise HTTPException(status_code=403, detail="Not authorized to view interventions for this session")

    return await _intervene_store.list_pending_for_conversation(
        db=db, conversation_session_id=session_id
    )


@ConversationRouter.post("/{session_id}/interventions/{request_id}/respond", response_model=InterveneResponseRead)
async def respond_to_conversation_intervention(
    session_id: uuid.UUID,
    request_id: uuid.UUID,
    body: InterveneResponseSubmit,
    request: Request,
    db: DbSession,
    claims: dict = Depends(require_permission(RT_AGENT_TRAILS, "read")),
):
    """Submit a response to an intervention request within a conversation session.

    REST fallback when the WebSocket respond path is unavailable. Validates
    session existence, ownership, and that the intervention request belongs to
    this conversation session and is still pending.
    """
    # Validate path request_id matches body
    if body.request_id != request_id:
        raise HTTPException(status_code=422, detail="Path request_id does not match body request_id")

    # Verify session exists
    conv_session = await db.get(ConversationSession, session_id)
    if not conv_session:
        raise HTTPException(status_code=404, detail="Conversation session not found")

    # Verify ownership
    user_id = _get_requesting_user_id(request)
    if user_id and conv_session.triggered_by_user_id and user_id != conv_session.triggered_by_user_id:
        raise HTTPException(status_code=403, detail="Not authorized to respond to interventions for this session")

    # Resolve operator identity from the authenticated caller
    # (identity plane — tenant-scope-exempt, FIX-20260929-221449: the
    # operator's Identity row may live in another tenant than the
    # resolved workspace).
    sub = claims.get("sub")
    from app.db.tenant_scoping import execute_unscoped

    identity_result = await execute_unscoped(
        db, select(Identity).where(Identity.subject == sub)
    )
    identity = identity_result.scalar_one_or_none()
    if identity is None:
        raise HTTPException(status_code=403, detail="User identity not found")

    # Verify the intervention request belongs to this conversation session
    from app.db.models.intervene import InterveneRequest, InterveneRequestStatus
    intervene_req = await db.get(InterveneRequest, request_id)
    if not intervene_req:
        raise HTTPException(status_code=404, detail="Intervene request not found")
    if intervene_req.conversation_session_id != session_id:
        raise HTTPException(
            status_code=400,
            detail="This intervention request does not belong to the specified conversation session",
        )
    if intervene_req.status != InterveneRequestStatus.pending:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot respond: request status is {intervene_req.status.value}",
        )

    # Same transaction as the stored answer: advance the durable resume record
    # (answering user, `resuming`, attempt).  A terminal record returns its
    # stored outcome and an elapsed window closes as `unresumable/expired` —
    # neither may start a resume.
    from app.services.conversations.turn_resolution import (
        REASON_EXPIRED,
        advance_answered_intervention,
        dispatch_answered_conversation_turn,
        execute_approved_live_test,
        prepare_live_test_decision,
        push_outcome_message,
    )

    # Live-test approval: apply the decision to the ledger FIRST (single
    # mechanism, two payload shapes). No linked ledger row → handled=False and
    # the ordinary ask/decide path below runs untouched.
    live_decision = await prepare_live_test_decision(
        db, intervene_req, approved=body.approval_value
    )
    if live_decision.expired:
        # The answer arrived after the approval window closed: the ledger and
        # the paused turn are already settled as expired, so nothing is run and
        # no resume is dispatched.
        await db.commit()
        await push_outcome_message(session_id, REASON_EXPIRED)
        raise HTTPException(
            status_code=409,
            detail={
                "error": "live_test_expired",
                "reason": (
                    "This live-test approval expired before it was answered. "
                    "Nothing ran — verification stays replay-only."
                ),
            },
        )

    try:
        orm_response = await _intervene_store.submit_response(
            db=db,
            request_id=request_id,
            operator_user_id=identity.id,
            approval_value=body.approval_value,
            selected_choice=body.selected_choice,
            text_value=body.text_value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    advance = await advance_answered_intervention(
        db, intervene_req, operator_user_id=identity.id
    )

    # Build response value for the durable resume dispatch.
    response_value: dict = {}
    if body.approval_value is not None:
        response_value["approval_value"] = body.approval_value
    if body.selected_choice is not None:
        response_value["selected_choice"] = body.selected_choice
    if body.text_value is not None:
        response_value["text_value"] = body.text_value
    # The paused live-test tool returns the stored/consumed outcome.
    if live_decision.handled:
        response_value.update(live_decision.resume_payload)

    # Convert to Pydantic model before commit
    response_data = InterveneResponseRead.model_validate(orm_response)
    await db.commit()

    if live_decision.should_execute and live_decision.request_id is not None and advance.dispatch:
        # Exactly the approved operations, once each, BEFORE the resume — so the
        # paused tool returns what actually ran. A duplicate answer never gets
        # here (the resume record is already terminal), and the ledger's
        # single-shot transition makes a second execution impossible.
        from app.core.tenant_context import optional_tenant_context

        payload = await execute_approved_live_test(
            db,
            live_decision.request_id,
            tenant_context=optional_tenant_context(request),
        )
        response_value.update(payload)

    if advance.dispatch or advance.expired:
        # Multi-tenancy: thread the REQUEST-resolved tenant into the resume
        # dispatch (never the module contextvar — internal answer paths do not
        # bind it). Without it the CH→CC claim/checkpoint relay is headerless
        # and fails closed 401, killing a still-valid pause.
        from app.core.tenant_context import optional_tenant_context

        # Dispatches the one resume, or delivers the already-persisted
        # `unresumable/expired` outcome (never both).
        await dispatch_answered_conversation_turn(
            db,
            intervene_req,
            advance,
            response_value,
            tenant_context=optional_tenant_context(request),
        )
    else:
        logger.info(
            "Answered intervention %s is already terminal (%s) — returning the "
            "stored outcome without re-dispatching",
            request_id,
            advance.reason_code,
        )

    return response_data


@ConversationRouter.get(
    "/sessions", response_model=ConversationSessionPageRead
)
async def list_conversation_sessions_paged(
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_TRAILS, "read")),
    agent_type_id: uuid.UUID | None = None,
    triggered_by_user_id: uuid.UUID | None = None,
    status: str = "all",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    all_time: bool = False,
    page: int = 1,
    page_size: int = 10,
) -> ConversationSessionPageRead:
    """FIX-20261101-120618 Work Item 1: paginated, filterable sessions listing.

    Ordered by updated_at DESC. When no explicit date range is given, a
    default lower bound of ``now − conversation_sessions_default_window_days``
    applies; ``all_time=true`` disables the window. ``status`` semantics:
    ``active`` → only active; ``ended`` → closed/archived/error; ``all`` →
    everything. Tenant-scoped via the request's tenant context.
    """
    from app.core.config import get_settings

    if status not in ("active", "ended", "all"):
        raise HTTPException(status_code=422, detail="status must be one of: active, ended, all")
    if page < 1 or page_size < 1:
        raise HTTPException(status_code=422, detail="page and page_size must be >= 1")

    items, total = await _store.list_sessions_page(
        db=db,
        agent_type_id=agent_type_id,
        triggered_by_user_id=triggered_by_user_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        all_time=all_time,
        page=page,
        page_size=page_size,
    )
    return ConversationSessionPageRead(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        default_window_days=get_settings().conversation_sessions_default_window_days,
    )


@ConversationRouter.get("/{session_id}", response_model=ConversationSessionDetailRead)
async def get_conversation(
    session_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_TRAILS, "read")),
) -> ConversationSession:
    session = await _store.get_session_with_turns(session_id, db)
    if not session:
        raise HTTPException(status_code=404, detail="Conversation session not found")
    return session
