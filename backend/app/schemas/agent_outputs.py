"""Pydantic v2 schemas for Agent Output CRUD and validation."""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class FieldError(BaseModel):
    """A validation error for a specific field."""

    field: str
    message: str


class ValidationResult(BaseModel):
    """Result of validating a payload against a data type schema."""

    valid: bool
    errors: list[FieldError] = Field(default_factory=list)


class AgentOutputCreate(BaseModel):
    """Request body for creating a typed agent output (internal)."""

    data_type_id: uuid.UUID
    agent_type_id: uuid.UUID
    execution_session_id: uuid.UUID
    field_values: dict | None = None
    validation_status: str = "valid"  # valid | validation_error
    raw_output: str | None = None


class AgentOutputResponse(BaseModel):
    """Response body for a single agent output with resolved names."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    data_type_id: uuid.UUID
    agent_type_id: uuid.UUID
    execution_session_id: uuid.UUID
    field_values: dict | None
    validation_status: str
    raw_output: str | None
    created_at: datetime

    # Resolved names (populated at query time)
    data_type_name: str | None = None
    agent_type_name: str | None = None


class AgentOutputQueryParams(BaseModel):
    """Filter and pagination parameters for querying agent outputs."""

    data_type_id: uuid.UUID | None = Field(None, description="Filter by data type")
    agent_type_id: uuid.UUID | None = Field(None, description="Filter by agent type")
    date_from: datetime | None = Field(None, description="Filter outputs created on or after this date")
    date_to: datetime | None = Field(None, description="Filter outputs created on or before this date")
    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")


class AgentOutputListResponse(BaseModel):
    """Paginated list response for agent outputs."""

    items: list[AgentOutputResponse]
    total: int
    page: int
    page_size: int


class AutoOutputItem(BaseModel):
    """A single auto-type agent output (stored in AgentJob.output_data)."""

    session_id: uuid.UUID
    agent_type_id: uuid.UUID
    agent_type_name: str | None
    output_preview: str | None  # First 200 chars of output_data['result']
    created_at: datetime


class AutoOutputListResponse(BaseModel):
    """Paginated list response for auto-type agent outputs."""

    items: list[AutoOutputItem]
    total: int
    page: int
    page_size: int


class ValidateOutputRequest(BaseModel):
    """Request body for the internal validation endpoint."""

    data_type_id: uuid.UUID
    payload: dict
