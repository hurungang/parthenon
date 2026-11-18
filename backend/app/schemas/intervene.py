"""Pydantic v2 schemas for agent-initiated human intervene requests and responses."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.db.models.intervene import InterveneRequestStatus, InterventionType


class LiveTestOperationSummary(BaseModel):
    """One entry of the tool-call PREVIEW (never secrets).

    Derived server-side from the approved script's own ``tools.call(...)``
    lines: it describes what the script will call. It is **not** the unit of
    approval — the whole script is.
    """

    tool_name: str
    arguments: dict = {}
    purpose: str | None = None


class LiveTestApprovalSummary(BaseModel):
    """The live-test approval attached to an intervention read.

    Present only when the intervention is the decision point of an
    ``OptimizationLiveTestRequest``; a plain ask/decide request stays
    unchanged. Lets the chat re-surface the approved script, its tool-call
    preview (and the expiry) after a reconnect and tells the client the
    approval is single-use: one end-to-end run of the script.
    """

    live_test_request_id: uuid.UUID
    status: str
    expires_at: datetime | None = None
    script_version_id: uuid.UUID | None = None
    script_name: str | None = None
    script_version_label: str | None = None
    operations: list[LiveTestOperationSummary] = []
    executed_operations: list[dict] | None = None
    target_agent_type_id: uuid.UUID | None = None


class InterveneRequestCreate(BaseModel):
    """Payload to create a new intervene request from an agent session."""

    agent_session_id: uuid.UUID
    intervention_type: InterventionType
    reason: str
    choices: list[str] | None = None
    conversation_session_id: uuid.UUID | None = None
    delegation_depth: int = 0


class InterveneRequestRead(BaseModel):
    """Read schema for an intervene request, including optional response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_session_id: uuid.UUID | None = None
    agent_type_id: uuid.UUID
    conversation_session_id: uuid.UUID | None = None
    intervention_type: InterventionType
    reason: str
    choices: list[str] | None
    status: InterveneRequestStatus
    delegation_depth: int
    created_at: datetime
    responded_at: datetime | None
    expires_at: datetime | None
    response: "InterveneResponseRead | None" = None
    agent_name: str | None = None
    triggered_by_user_name: str | None = None
    #: Present only for a live-test approval (see ``LiveTestApprovalSummary``).
    #: A plain question / choice / approval intervention leaves it null.
    live_test: LiveTestApprovalSummary | None = None


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
