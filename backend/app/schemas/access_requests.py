"""Pydantic v2 schemas for Access Requests."""
import uuid
from datetime import datetime
from enum import Enum
from typing import List

from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated


class AccessRequestStatusEnum(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class AccessRequestBatchCreate(BaseModel):
    group_ids: List[uuid.UUID] = Field(default_factory=list)
    justification: Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class AccessRequestRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    batch_id: uuid.UUID
    user_id: uuid.UUID
    group_id: uuid.UUID | None
    status: AccessRequestStatusEnum
    reviewer_id: uuid.UUID | None
    reviewer_reason: str | None
    created_at: datetime
    updated_at: datetime
    # Enriched fields (populated manually in API handlers)
    group_name: str | None = None
    requester_display_name: str | None = None


class AccessRequestBatchRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    justification: str
    submitted_at: datetime
    requests: List[AccessRequestRead] = Field(default_factory=list)


class ApproveRequestBody(BaseModel):
    group_id: uuid.UUID | None = None
    approval_reason: str | None = None


class RejectRequestBody(BaseModel):
    rejection_reason: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
