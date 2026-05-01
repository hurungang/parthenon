"""Conversations API router — query endpoints for conversation history."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_permission
from app.core.resource_types import RT_CONVERSATION
from app.db.models.conversations import ConversationSession
from app.db.session import DbSession
from app.schemas.conversations import ConversationSessionDetailRead, ConversationSessionRead
from app.services.conversations.store import ConversationStore

logger = logging.getLogger(__name__)

ConversationRouter = APIRouter(prefix="/conversations", tags=["Conversations"])

_store = ConversationStore()


@ConversationRouter.get("", response_model=list[ConversationSessionRead])
async def list_conversations(
    db: DbSession,
    _: dict = Depends(require_permission(RT_CONVERSATION, "read")),
    agent_type_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ConversationSession]:
    return await _store.list_sessions(
        db=db,
        agent_type_id=agent_type_id,
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
