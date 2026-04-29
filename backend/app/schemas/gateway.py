"""Pydantic v2 schemas for Agent Gateway."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class GatewayInitRequest(BaseModel):
    agent_type_id: uuid.UUID
    initiator_subject: str | None = None


class GatewayInitResponse(BaseModel):
    session_handle: str
    instance_id: uuid.UUID
    agent_type_id: uuid.UUID


class GatewayRequestPayload(BaseModel):
    prompt: str
    context: dict[str, Any] | None = None


class GatewayRequestResponse(BaseModel):
    response: str
    instance_id: uuid.UUID
    session_handle: str
    has_question: bool = False


class GatewayQuestionResponse(BaseModel):
    question: str | None = None
    instance_id: uuid.UUID
    pending: bool = True


class GatewayAnswerPayload(BaseModel):
    answer: str


class GatewayAnswerResponse(BaseModel):
    acknowledged: bool
    instance_id: uuid.UUID


class GatewayCloseResponse(BaseModel):
    closed: bool
    instance_id: uuid.UUID


class GatewayRouteRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    agent_type_id: uuid.UUID
    http_base_path: str
    created_at: datetime
