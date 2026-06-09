"""Pydantic v2 schemas for agent-initiated human intervene requests and responses."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.db.models.intervene import InterveneRequestStatus, InterventionType


class InterveneRequestCreate(BaseModel):
    """Payload to create a new intervene request from an agent session."""

    agent_session_id: uuid.UUID
    intervention_type: InterventionType
    reason: str
    choices: list[str] | None = None


class InterveneRequestRead(BaseModel):
    """Read schema for an intervene request, including optional response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_session_id: uuid.UUID
    agent_type_id: uuid.UUID
    intervention_type: InterventionType
    reason: str
    choices: list[str] | None
    status: InterveneRequestStatus
    created_at: datetime
    responded_at: datetime | None
    expires_at: datetime | None
    response: "InterveneResponseRead | None" = None
    agent_name: str | None = None
    triggered_by_user_name: str | None = None


class InterveneResponseSubmit(BaseModel):
    """Operator response to an intervene request.

    Exactly one of approval_value, selected_choice, or text_value must be
    provided, matching the intervention type of the request.
    """

    request_id: uuid.UUID
    approval_value: bool | None = None
    selected_choice: str | None = None
    text_value: str | None = None

    @model_validator(mode="after")
    def _validate_mutually_exclusive(self) -> "InterveneResponseSubmit":
        provided = [
            self.approval_value is not None,
            self.selected_choice is not None,
            self.text_value is not None,
        ]
        if sum(provided) != 1:
            raise ValueError(
                "Exactly one of approval_value, selected_choice, or text_value must be provided"
            )
        return self


class InterveneResponseRead(BaseModel):
    """Read schema for an intervene response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    request_id: uuid.UUID
    operator_user_id: uuid.UUID
    approval_value: bool | None
    selected_choice: str | None
    text_value: str | None
    responded_at: datetime
    operator_user_name: str | None = None


class InterveneMetrics(BaseModel):
    """Aggregate metrics for the intervene system."""

    pending_count: int
    avg_response_time_seconds: float
    resolution_rate: float
