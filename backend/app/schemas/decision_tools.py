"""Pydantic v2 schemas for decision tools, questions, and execution results.

Decision tools are user-definable tools behaving like system tools: a name
(unique per tenant), a purpose, input/output contracts as AgentDataType
references (``input_data_type_id`` / ``output_data_type_id`` — no inline
schema storage), a state preset, act/confirm thresholds, and an
auto-generated description derived from the definition. The
``decision____`` prefix is applied only at the MCP/tool surface; names are
stored plain.
"""
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.db.models.decision_tools import DecisionQuestionType, DecisionToolStatus
from app.db.models.results import DecisionExecutionStatus, DecisionOutcome

# Sources allowed in a state-preset mapping. Each mapping pulls a value from
# the execution input (``input``) or from agent data saved in the session
# (``agent_data``) into the state sent to the System One model.
StatePresetSource = Literal["input", "agent_data"]


class AgentDataTypeSummary(BaseModel):
    """Read-only summary of a referenced AgentDataType (id/name/slug/fields)."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    slug: str
    fields: list[Any] = []


class StatePresetMapping(BaseModel):
    """A single state field mapping: state key → data source + key."""

    source: StatePresetSource
    key: Annotated[str, StringConstraints(min_length=1)]


class DecisionToolQuestionBase(BaseModel):
    """Typed question payload with per-type criteria validation.

    - ``choice``: ``criteria_options`` must be a non-empty dict (option key → description).
    - ``score``: ``criteria_options`` must be a non-empty ordered list (rubric legend).
    - ``noul``: binary numeric judgment — ``criteria_options`` must be omitted/None.
    """

    question_key: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    question_type: DecisionQuestionType = DecisionQuestionType.choice
    instructions: str | None = None
    criteria_options: dict[str, str] | list[Any] | None = None
    is_required: bool = True
    ordering: int = 0

    @model_validator(mode="after")
    def validate_criteria_by_type(self) -> "DecisionToolQuestionBase":
        qtype = self.question_type
        if qtype == DecisionQuestionType.choice:
            if not isinstance(self.criteria_options, dict) or not self.criteria_options:
                raise ValueError(
                    "choice questions require a non-empty criteria_options dict "
                    "mapping option key to description"
                )
        elif qtype == DecisionQuestionType.score:
            if not isinstance(self.criteria_options, list) or not self.criteria_options:
                raise ValueError(
                    "score questions require a non-empty ordered criteria_options "
                    "list (rubric legend)"
                )
        else:  # noul
            if self.criteria_options is not None:
                raise ValueError(
                    "noul questions must not define criteria_options"
                )
        return self


class DecisionToolQuestionCreate(DecisionToolQuestionBase):
    """Create/update payload for a decision tool question."""


class DecisionToolQuestionRead(BaseModel):
    """Question as returned in tool detail reads."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    ordering: int
    question_key: str
    question_type: DecisionQuestionType
    instructions: str | None
    criteria_options: dict[str, Any] | list[Any] | None
    is_required: bool


class DecisionToolCreate(BaseModel):
    """Create/update payload for a decision tool.

    ``name`` is unique within the calling tenant; the auto-generated
    description is derived server-side from the definition (never accepted
    from the client).
    """

    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    purpose: str | None = None
    input_data_type_id: uuid.UUID | None = None
    output_data_type_id: uuid.UUID | None = None
    state_preset: dict[str, StatePresetMapping] | None = None
    act_threshold: float = Field(default=0.9, ge=0.0, le=1.0)
    confirm_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    provider_model: str = "jev-latest"
    status: DecisionToolStatus = DecisionToolStatus.active
    enabled: bool = True
    questions: list[DecisionToolQuestionCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_thresholds_and_preset(self) -> "DecisionToolCreate":
        if self.act_threshold < self.confirm_threshold:
            raise ValueError(
                "act_threshold must be greater than or equal to confirm_threshold"
            )
        if self.state_preset:
            for state_key, mapping in self.state_preset.items():
                if not state_key:
                    raise ValueError("state_preset keys must be non-empty")
                if not mapping.key.strip():
                    raise ValueError(
                        f"state_preset mapping for '{state_key}' has an empty data key"
                    )
        return self


class DecisionToolUpdate(BaseModel):
    """Partial update payload; re-validates and regenerates the description."""

    purpose: str | None = None
    input_data_type_id: uuid.UUID | None = None
    output_data_type_id: uuid.UUID | None = None
    state_preset: dict[str, StatePresetMapping] | None = None
    act_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    confirm_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    provider_model: str | None = None
    status: DecisionToolStatus | None = None
    enabled: bool | None = None
    questions: list[DecisionToolQuestionCreate] | None = None


class DecisionToolRead(BaseModel):
    """Decision tool as returned by the REST API (includes the generated
    description and question children)."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    tenant_id: uuid.UUID | None
    name: str
    purpose: str | None
    description: str | None
    input_data_type_id: uuid.UUID | None
    output_data_type_id: uuid.UUID | None
    input_data_type: AgentDataTypeSummary | None = None
    output_data_type: AgentDataTypeSummary | None = None
    state_preset: dict[str, Any] | None
    act_threshold: float
    confirm_threshold: float
    provider_model: str
    status: DecisionToolStatus
    enabled: bool
    is_system: bool = False
    created_at: datetime
    updated_at: datetime
    questions: list[DecisionToolQuestionRead] = []


class DecisionToolDescriptionRead(BaseModel):
    """The auto-generated tool description."""

    tool_id: uuid.UUID
    name: str
    description: str


class DecisionExecutionResultRead(BaseModel):
    """Persisted decision execution result (auditable, no credentials)."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    tenant_id: uuid.UUID | None
    decision_tool_id: uuid.UUID
    conversation_session_id: uuid.UUID | None
    input_state_snapshot: dict[str, Any] | None
    answers: dict[str, Any] | None
    outcome: DecisionOutcome
    status: DecisionExecutionStatus
    provider_model: str | None
    error_message: str | None
    created_at: datetime


class DecisionToolGenerateRequest(BaseModel):
    """AI-assisted authoring request: description + chosen data types.

    ``existing_questions`` (optional draft) is provided when regenerating
    against an existing definition so the model can refine it.
    """

    description: Annotated[str, StringConstraints(min_length=1)]
    input_data_type_id: uuid.UUID | None = None
    output_data_type_id: uuid.UUID | None = None
    existing_questions: list[DecisionToolQuestionCreate] | None = None


class DecisionToolGenerateResponse(BaseModel):
    """Reviewable draft: typed questions + suggested state mapping.

    ``detected_state_paths`` are backtick-quoted state paths found in the
    drafted question instructions (suggested mappings for the form).
    """

    questions: list[DecisionToolQuestionCreate]
    state_preset: dict[str, StatePresetMapping] | None = None
    detected_state_paths: list[str] = []
    model_id: str
