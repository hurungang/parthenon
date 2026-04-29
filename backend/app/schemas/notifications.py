"""Pydantic v2 schemas for Results and Notifications."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, StringConstraints
from typing import Annotated

from app.db.models.notifications import ChannelType, DeliveryStatus


class ResultRecordRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    agent_type_id: uuid.UUID | None
    agent_instance_id: uuid.UUID | None
    conversation_session_id: uuid.UUID | None
    title: str | None
    content_type: str
    payload: dict[str, Any]
    tags: list[str] | None
    created_at: datetime


class SaveResultRequest(BaseModel):
    """Request payload for the save_result MCP tool."""
    title: str | None = None
    payload: dict[str, Any]
    tags: list[str] | None = None
    agent_type_id: uuid.UUID | None = None
    agent_instance_id: uuid.UUID | None = None
    conversation_session_id: uuid.UUID | None = None


class NotificationChannelCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    channel_type: ChannelType
    description: str | None = None
    config: dict[str, Any] | None = None  # Plaintext — encrypted before storage


class NotificationChannelUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    config: dict[str, Any] | None = None
    is_active: bool | None = None


class NotificationChannelRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    channel_type: ChannelType
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class NotificationEventRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    channel_id: uuid.UUID
    subject: str | None
    body: str
    recipient: str | None
    status: DeliveryStatus
    error: str | None
    created_at: datetime
    delivered_at: datetime | None


class TestNotificationRequest(BaseModel):
    recipient: str | None = None
    subject: str = "Test notification from Parthenon"
    body: str = "This is a test notification."
