"""Declarative step-graph schema for compiled bridge scripts (Agent Runtime).

Pydantic v2 models describing a deterministic bridge script: typed step
nodes (tool call, transform, semantic-bridge, decision, output), typed
inputs/outputs, comparison tolerance, and model-backed step markers (S3).

Security invariants (SEC3):
- Tool-call steps reference tools by NAME only — permission resolution and
  per-call token injection stay delegated to Control Center / Communication
  Hub. No credentials, tokens, or secret-bearing URLs may appear anywhere.
"""
from __future__ import annotations

import enum
from typing import Any, Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StepKind(str, enum.Enum):
    tool_call = "tool_call"
    transform = "transform"
    semantic_bridge = "semantic_bridge"
    decision = "decision"
    output = "output"
    # Model-authored sandboxed Python segment (N3): executed in the
    # RestrictedPython sandbox with the injected MCP-only client.
    script_segment = "script_segment"


class TransformOp(str, enum.Enum):
    """Supported declarative data transformations between steps.

    Structural ops reshape step outputs; computed-data ops derive
    deterministic values (counts, columns, aggregates, elements) from prior
    step outputs so subsequent steps can consume them without a model.
    """

    passthrough = "passthrough"
    select_keys = "select_keys"
    json_path_get = "json_path_get"
    template = "template"
    constant = "constant"
    # Computed-data ops:
    count = "count"      # length of an array / number of keys of an object
    pluck = "pluck"      # extract a column (``field``) from an array of objects → array
    merge = "merge"      # merge two context keys' objects (key-wise) or arrays (concat)
    sum = "sum"          # numeric sum of ``field`` over an array of objects
    first = "first"      # first element of an array
    last = "last"        # last element of an array


class ComparisonTolerance(BaseModel):
    """Deterministic comparison tolerance used by the Verification Engine (V1)."""

    ignore_keys: list[str] = Field(default_factory=list)
    numeric_abs_tolerance: float = 0.0
    numeric_rel_tolerance: float = 0.0
    string_case_insensitive: bool = False
    ignore_order_in_lists: bool = False


class BaseStep(BaseModel):
    """Common step node fields."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    model_backed: bool = False
    # Output key under which this step's result is stored for downstream steps.
    output_key: str | None = None


class ToolCallStep(BaseStep):
    """Invoke an MCP/system tool through Communication Hub by name only."""

    kind: Literal[StepKind.tool_call] = StepKind.tool_call
    tool_name: str = Field(min_length=1, description="Canonical tool name (server____tool)")
    arguments: dict[str, Any] = Field(default_factory=dict)
    # ``{{step_name.field}}`` references resolved from prior step outputs.
    argument_templates: dict[str, str] = Field(default_factory=dict)
    # Optional JSON-schema-ish validation applied to the tool result.
    expected_output_keys: list[str] = Field(default_factory=list)


class TransformStep(BaseStep):
    """Pure data transformation between steps (no model, no tool)."""

    kind: Literal[StepKind.transform] = StepKind.transform
    op: TransformOp = TransformOp.passthrough
    input_key: str | None = None
    # Second source key for ``merge`` (merged with ``input_key``).
    input_key_b: str | None = None
    keys: list[str] = Field(default_factory=list)
    # Column name for ``pluck`` / ``sum`` over arrays of objects.
    field: str | None = None
    path: str | None = None
    template: str | None = None
    value: Any = None


class SemanticBridgeStep(BaseStep):
    """Model-backed semantic-bridge sub-agent step (S1, S2) — model_backed=True."""

    kind: Literal[StepKind.semantic_bridge] = StepKind.semantic_bridge
    model_backed: bool = True
    tool_name: str = Field(min_length=1, description="Bridge tool routed via Communication Hub")
    prompt_template: str | None = None
    input_key: str | None = None


class DecisionStep(BaseStep):
    """System One decision step (S1) — model_backed=True, carries confidence."""

    kind: Literal[StepKind.decision] = StepKind.decision
    model_backed: bool = True
    tool_name: str = Field(min_length=1, description="decision____<name> tool")
    arguments: dict[str, Any] = Field(default_factory=dict)
    argument_templates: dict[str, str] = Field(default_factory=dict)


class ScriptSegmentStep(BaseStep):
    """Model-authored sandboxed Python segment (N3).

    The ``python_source`` must define ``run(context, tools)``; it executes in
    the RestrictedPython sandbox with the session's MCP-only client injected
    as ``tools`` — the segment's only external binding (E8).
    """

    kind: Literal[StepKind.script_segment] = StepKind.script_segment
    python_source: str = Field(min_length=1)
    # Optional sandbox caps overriding the version defaults for this segment.
    cpu_limit_seconds: int | None = None
    memory_limit_mb: int | None = None
    wall_time_limit_seconds: int | None = None


class OutputStep(BaseStep):
    """Final output declaration: projects stored step outputs to the result."""

    kind: Literal[StepKind.output] = StepKind.output
    output_key: str = "result"
    select_keys: list[str] = Field(default_factory=list)


Step = Annotated[
    Union[
        ToolCallStep,
        TransformStep,
        SemanticBridgeStep,
        DecisionStep,
        ScriptSegmentStep,
        OutputStep,
    ],
    Field(discriminator="kind"),
]


class StepGraph(BaseModel):
    """A compiled bridge script: an ordered, typed step graph.

    Round-trips to JSON; ``model_validate_json`` / ``model_dump_json`` are the
    canonical serialization. Unknown step ``kind`` values are rejected by the
    discriminated union.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    version: str = "1"
    steps: list[Step] = Field(min_length=1)
    comparison_tolerance: ComparisonTolerance = Field(default_factory=ComparisonTolerance)

    @field_validator("steps")
    @classmethod
    def _validate_step_names_unique(cls, steps: list[BaseStep]) -> list[BaseStep]:
        names = [s.name for s in steps]
        if len(names) != len(set(names)):
            raise ValueError("Step names must be unique within a step graph")
        return steps

    def model_backed_steps(self) -> list[BaseStep]:
        """Steps that consume model capacity (S3 telemetry marker)."""
        return [s for s in self.steps if s.model_backed]

    def tool_names(self) -> list[str]:
        """All tool names referenced by this graph (for audit/permission preview)."""
        return [
            s.tool_name
            for s in self.steps
            if isinstance(s, (ToolCallStep, SemanticBridgeStep, DecisionStep))
        ]


# ── Model-authored workflow composition (Phase 2 emission schema) ────────────


class CompositionSegment(BaseModel):
    """One model-authored composition segment.

    Either a sandboxed Python script segment (``python_source`` set,
    ``scriptable=True``) or a model-backed step design (LLM bridge /
    decision) — strongly typed (Pydantic v2).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    order: int = Field(ge=1)
    scriptable: bool = True
    # Sandboxable Python for scriptable segments (run(context, tools)).
    python_source: str | None = None
    # Tool-call step design (deterministic MCP tool invocation).
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Model-backed step design.
    step_type: Literal[
        "tool_invocation",
        "skill_invocation",
        "script_segment",
        "semantic_bridge",
        "decision",
        "interactive_input",
        "agent_delegation",
        "sop_invocation",
    ] = "tool_invocation"
    prompt_template: str | None = None
    output_key: str | None = None
    output_mode: Literal["deterministic", "llm_render"] | None = None
    output_template: str | None = None


class WorkflowComposition(BaseModel):
    """Full model-authored composition emitted by plan generation.

    The plan LLM authors the workflow: sandboxed Python script segments,
    LLM bridge steps, and decision steps — the compiler only validates and
    normalizes (no hardcoded steps are ever appended).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    segments: list[CompositionSegment] = Field(min_length=1)
    comparison_tolerance: ComparisonTolerance = Field(
        default_factory=ComparisonTolerance
    )
