"""Pydantic v2 schemas for Results and Notifications."""
import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.db.models.notifications import ChannelType, DeliveryStatus, SourceType


# ── Result schemas (unchanged) ─────────────────────────────────────────────────

class ResultRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


# ── Channel property schemas ───────────────────────────────────────────────────

class ChannelPropertyRead(BaseModel):
    """Property metadata returned in API responses.
    
    - encrypted_value is never exposed
    - value is only populated for non-secret properties (for editing convenience)
    - secret properties (is_secret=True) have value=None for security
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    is_secret: bool
    value: str | None = None  # Only populated for non-secret properties


class ChannelPropertyWrite(BaseModel):
    """Property key-value pair submitted by the client (plaintext — service encrypts)."""
    key: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    value: str
    is_secret: bool = False


# ── Notification channel schemas ───────────────────────────────────────────────

class NotificationChannelCreate(BaseModel):
    name: Annotated[
        str,
        StringConstraints(min_length=1, max_length=200, pattern=r"^[a-z0-9\-]+$"),
    ]
    channel_type: ChannelType
    description: str | None = None
    properties: list[ChannelPropertyWrite] = []


class NotificationChannelUpdate(BaseModel):
    name: Annotated[
        str,
        StringConstraints(min_length=1, max_length=200, pattern=r"^[a-z0-9\-]+$"),
    ] | None = None
    description: str | None = None
    is_active: bool | None = None
    properties: list[ChannelPropertyWrite] | None = None


class NotificationChannelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    channel_type: ChannelType
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    properties: list[ChannelPropertyRead] = []


# ── Recipient group schemas ────────────────────────────────────────────────────

class GroupChannelMappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel_id: uuid.UUID
    recipient_properties: dict | None = None


class RecipientGroupCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    slug: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = None
    description: str | None = None
    is_active: bool = True


class RecipientGroupUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    description: str | None = None
    is_active: bool | None = None


class RecipientGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    channel_mappings: list[GroupChannelMappingRead] = []


class AssignChannelRequest(BaseModel):
    channel_id: uuid.UUID
    recipient_properties: dict | None = None


# ── Notification log schemas ───────────────────────────────────────────────────

class NotificationLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    group_id: uuid.UUID | None
    channel_id: uuid.UUID
    source_type: SourceType
    source_id: uuid.UUID | None
    subject: str | None
    body: str
    recipient: str | None
    status: DeliveryStatus
    error: str | None
    metadata_: dict | None = None
    created_at: datetime
    delivered_at: datetime | None


# ── Send / test schemas ────────────────────────────────────────────────────────

class SendNotificationRequest(BaseModel):
    group_slug: str
    subject: str | None = None
    body: str
    source_type: SourceType = SourceType.MANUAL
    source_id: uuid.UUID | None = None


class TestChannelRequest(BaseModel):
    test_recipient: str


class TestChannelResponse(BaseModel):
    success: bool
    error: str | None = None


# ── Legacy schemas (kept for backward compatibility) ──────────────────────────

class NotificationEventRead(BaseModel):
    """Retained for backward compatibility — maps to NotificationEvent."""
    model_config = ConfigDict(from_attributes=True)

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
    """Legacy test request schema."""
    recipient: str | None = None
    subject: str = "Test notification from Parthenon"
    body: str = "This is a test notification."
