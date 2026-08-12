"""Conversations API router — session management and conversation history."""
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_claims, require_permission
from app.core.resource_types import RT_AGENT_TRAILS
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.db.models.identity import Identity
from app.db.session import DbSession
from app.schemas.conversations import (
    ConversationSessionCreate,
    ConversationSessionDetailRead,
    ConversationSessionRead,
)
from app.schemas.intervene import (
    InterveneRequestRead,
    InterveneResponseRead,
    InterveneResponseSubmit,
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
    """Extract the platform user ID from JWT claims."""
    claims = get_current_claims(request)
    user_id_str: str | None = claims.get("platform_user_id")
    return uuid.UUID(user_id_str) if user_id_str else None


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
    """Transition a conversation session to closed status."""
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
    sub = claims.get("sub")
    identity_result = await db.execute(select(Identity).where(Identity.subject == sub))
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

    # Build response value for Agent Runtime resume
    agent_session_id = intervene_req.agent_session_id
    response_value: dict = {}
    if body.approval_value is not None:
        response_value["approval_value"] = body.approval_value
    if body.selected_choice is not None:
        response_value["selected_choice"] = body.selected_choice
    if body.text_value is not None:
        response_value["text_value"] = body.text_value

    # Convert to Pydantic model before commit
    response_data = InterveneResponseRead.model_validate(orm_response)
    await db.commit()

    # Resume the agent session
    if agent_session_id is not None:
        try:
            from app.api.v1.intervene import _resume_agent_session
            logger.info(
                "Resuming agent session %s with response_value=%s",
                agent_session_id,
                response_value,
            )
            await _resume_agent_session(agent_session_id, response_value)
        except Exception:
            logger.warning(
                "Failed to resume agent session %s after conversation intervention response",
                agent_session_id,
                exc_info=True,
            )

    return response_data


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
