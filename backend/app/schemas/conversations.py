"""Pydantic v2 schemas for Conversations."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.db.models.conversations import ConversationStatus, TurnRole


class ToolCallRecordRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    turn_id: uuid.UUID
    tool_name: str
    tool_input: dict[str, Any] | None
    tool_output: dict[str, Any] | None
    error: str | None
    duration_ms: int | None
    created_at: datetime


class ConversationTurnRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    session_id: uuid.UUID
    role: TurnRole
    content: str
    token_count: int | None
    created_at: datetime
    tool_calls: list[ToolCallRecordRead] = []


class ConversationSessionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    agent_instance_id: uuid.UUID | None
    agent_type_id: uuid.UUID | None
    initiator_subject: str | None
    channel: str
    status: ConversationStatus
    turn_count: int
    created_at: datetime
    closed_at: datetime | None


class ConversationSessionDetailRead(ConversationSessionRead):
    turns: list[ConversationTurnRead] = []
