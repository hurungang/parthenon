"""Pydantic v2 schemas for Agent Data read-only public API."""
import uuid
from datetime import datetime

from pydantic import BaseModel


class AgentDataResponse(BaseModel):
    """Response body for a single AgentData record with resolved names."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    agent_type_id: uuid.UUID | None
    session_id: uuid.UUID | None
    data_name: str
    data_value: object
    data_type: str
    is_active: bool
    created_at: datetime

    # Resolved names (populated at query time)
    agent_type_name: str | None = None


class AgentDataListResponse(BaseModel):
    """Paginated list response for agent data records."""

    items: list[AgentDataResponse]
    total: int
    page: int
    page_size: int
