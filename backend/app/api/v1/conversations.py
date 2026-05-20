"""Conversations API router — session management and conversation history."""
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_claims, require_permission
from app.core.resource_types import RT_CONVERSATION
from app.db.session import DbSession
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.schemas.conversations import (
    ConversationSessionCreate,
    ConversationSessionDetailRead,
    ConversationSessionRead,
)
from app.services.conversations.manager import ConversationSessionManager
from app.services.conversations.store import ConversationStore

logger = logging.getLogger(__name__)

ConversationRouter = APIRouter(prefix="/conversations", tags=["Conversations"])

_store = ConversationStore()
_manager = ConversationSessionManager()


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
    _: dict = Depends(require_permission(RT_CONVERSATION, "read")),
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
    _: dict = Depends(require_permission(RT_CONVERSATION, "read")),
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
    _: dict = Depends(require_permission(RT_CONVERSATION, "read")),
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
    _: dict = Depends(require_permission(RT_CONVERSATION, "read")),
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
    _: dict = Depends(require_permission(RT_CONVERSATION, "read")),
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


@ConversationRouter.get("/{session_id}", response_model=ConversationSessionDetailRead)
async def get_conversation(
    session_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_CONVERSATION, "read")),
) -> ConversationSession:
    session = await _store.get_session_with_turns(session_id, db)
    if not session:
        raise HTTPException(status_code=404, detail="Conversation session not found")
    return session
