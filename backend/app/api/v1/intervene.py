"""Intervene API router — endpoints for agent-initiated human intervene requests."""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import require_permission
from app.core.resource_types import RT_AGENT_HUMAN_INTERVENTION
from app.db.models.identity import Identity
from app.db.models.intervene import (
    InterveneRequest,
    InterveneRequestStatus,
    InterventionType,
)
from app.db.session import DbSession
from app.schemas.intervene import (
    InterveneMetrics,
    InterveneRequestRead,
    InterveneResponseRead,
    InterveneResponseSubmit,
)
from app.services.agents.intervene_service import InterveneRequestStore

logger = logging.getLogger(__name__)

InterveneRouter = APIRouter(prefix="/intervene", tags=["Intervene"])

_store = InterveneRequestStore()


# ── Helper: resume agent execution via Agent Runtime ──────────────────────


async def _resume_agent_session(session_id: uuid.UUID, response_value: dict) -> None:
    """Notify Agent Runtime that this session can resume after intervention.

    Failures are logged but do NOT propagate — the response has already been
    committed and the operator sees success regardless of the resume call.
    """
    try:
        from app.services.control_center.agent_runtime_client import (
            AgentRuntimeClient,
        )
        client = AgentRuntimeClient()
        await client.resume_session(session_id, response_value)
        logger.info(
            "Session %s resumed on Agent Runtime after human intervention",
            session_id,
        )
    except Exception as exc:
        logger.warning(
            "Agent Runtime resume call failed for session %s: %s "
            "(operator response already committed — execution may not resume)",
            session_id,
            exc,
        )


@InterveneRouter.get("/requests", response_model=list[InterveneRequestRead])
async def list_intervene_requests(
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_HUMAN_INTERVENTION, "view")),
    status: InterveneRequestStatus | None = None,
    intervention_type: InterventionType | None = None,
    agent_session_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list:
    return await _store.list_requests(
        db=db,
        status=status,
        intervention_type=intervention_type,
        agent_session_id=agent_session_id,
        limit=limit,
        offset=offset,
    )


@InterveneRouter.get("/requests/{request_id}", response_model=InterveneRequestRead)
async def get_intervene_request(
    request_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_HUMAN_INTERVENTION, "view")),
):
    request = await _store.get_request(db=db, request_id=request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Intervene request not found")
    return request


@InterveneRouter.post("/requests/{request_id}/respond", response_model=InterveneResponseRead)
async def respond_to_intervene_request(
    request_id: uuid.UUID,
    body: InterveneResponseSubmit,
    db: DbSession,
    claims: dict = Depends(require_permission(RT_AGENT_HUMAN_INTERVENTION, "respond")),
):
    # Validate request_id in path matches body
    if body.request_id != request_id:
        raise HTTPException(
            status_code=422,
            detail="Path request_id does not match body request_id",
        )
    # Resolve operator user from the authenticated caller's identity
    sub = claims.get("sub")
    result = await db.execute(select(Identity).where(Identity.subject == sub))
    identity = result.scalar_one_or_none()
    if identity is None:
        raise HTTPException(status_code=403, detail="User identity not found")
    try:
        orm_response = await _store.submit_response(
            db=db,
            request_id=request_id,
            operator_user_id=identity.id,
            approval_value=body.approval_value,
            selected_choice=body.selected_choice,
            text_value=body.text_value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Capture the session ID and response_value BEFORE commit so the ORM
    # objects are still attached to the session.  We query the request
    # directly (identity-map hit, no extra DB round-trip) instead of
    # accessing orm_response.request (a lazy relationship that would
    # trigger greenlet_spawn in an async context).
    req = await db.get(InterveneRequest, request_id)
    agent_session_id = req.agent_session_id if req else None
    response_value: dict = {}
    if body.approval_value is not None:
        response_value["approval_value"] = body.approval_value
    if body.selected_choice is not None:
        response_value["selected_choice"] = body.selected_choice
    if body.text_value is not None:
        response_value["text_value"] = body.text_value

    # Convert to Pydantic model before commit to avoid serializing an
    # expired ORM object after commit() expires all tracked instances.
    response_data = InterveneResponseRead.model_validate(orm_response)
    await db.commit()

    # Resume the agent session so execution continues.
    if agent_session_id is not None:
        await _resume_agent_session(agent_session_id, response_value)
    else:
        logger.warning(
            "Could not determine agent_session_id for request %s — "
            "agent execution will not resume",
            request_id,
        )

    return response_data


@InterveneRouter.post("/requests/{request_id}/cancel", response_model=InterveneRequestRead)
async def cancel_intervene_request(
    request_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_HUMAN_INTERVENTION, "respond")),
):
    try:
        request = await _store.cancel_request(db=db, request_id=request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    # Refresh with eager-loaded response to avoid MissingGreenlet during serialization
    await db.refresh(request, attribute_names=["response"])
    return request


@InterveneRouter.get("/metrics", response_model=InterveneMetrics)
async def get_intervene_metrics(
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_HUMAN_INTERVENTION, "view")),
):
    metrics = await _store.get_metrics(db=db)
    return InterveneMetrics(**metrics)
