"""Decision tool service — CRUD and validation for DecisionTool +
ordered DecisionToolQuestion children.

Tenant containment: every lookup and mutation filters by the caller's
tenant, and names are unique WITHIN a tenant (tenant A and tenant B can
each define ``tool_a``); duplicates within one tenant are rejected with a
clear conflict error.

The tool description is auto-generated from the definition (purpose,
typed questions, referenced input/output data types) and stored on the
entity — this generated description is what skills, agents, and MCP
clients see.

Input/output contracts are AgentDataType references: nullable, resolved
strictly within the caller's tenant (the NULL shared slot is retired).

Questions are validated against per-type rules:
- Choice: non-empty criteria_options dict (option key → description).
- Score: non-empty ordered criteria_options list (rubric legend).
- Noul: no criteria allowed (rejected if present).
- At least one question required (schema-enforced).
- State preset mappings must reference known state sources (``input`` or
  ``agent_data`` keys); ``input``-sourced mapping keys must be fields of
  the chosen input data type (when one is referenced).
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.agent_data_type import AgentDataType
from app.db.models.decision_tools import (
    DecisionQuestionType,
    DecisionTool,
    DecisionToolQuestion,
)
from app.schemas.decision_tools import (
    DecisionToolCreate,
    DecisionToolUpdate,
    StatePresetMapping,
)

logger = logging.getLogger(__name__)


class DecisionToolValidationError(Exception):
    """Raised when a decision tool payload fails validation.

    Carries a list of human-readable field-level error strings.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class DecisionToolNameConflictError(DecisionToolValidationError):
    """Raised when a tool name already exists within the same tenant."""

    def __init__(self, name: str) -> None:
        super().__init__(
            [f"A decision tool named '{name}' already exists in this tenant"]
        )
        self.name = name


def _field_names(data_type: AgentDataType | None) -> list[str]:
    """Extract the field names of an AgentDataType (tolerates odd shapes)."""
    if not data_type or not isinstance(data_type.fields, list):
        return []
    names = []
    for field in data_type.fields:
        if isinstance(field, dict) and field.get("name"):
            names.append(str(field["name"]))
        elif isinstance(field, str):
            names.append(field)
    return names


def describe_data_type(data_type: AgentDataType | None, role: str) -> str | None:
    """One-line description of a referenced data type for the tool description."""
    if not data_type:
        return None
    names = _field_names(data_type)
    fields = f" Fields: {', '.join(names)}." if names else ""
    return f"{role.capitalize()} data type: {data_type.name} ({data_type.slug}).{fields}"


def decision_tool_virtual_tool_id(tool_id: uuid.UUID) -> uuid.UUID:
    """Compute the virtual MCP-hub tool id for a decision tool.

    Mirrors ``mcp_hub._decision_tool_reads`` — decision tools have no
    ``mcp_tools`` row, so skill bindings store this deterministic uuid5 id.
    """
    return uuid.uuid5(uuid.NAMESPACE_URL, f"decision-tool:{tool_id}")


async def resolve_virtual_tool_id(
    db: AsyncSession,
    tool_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
) -> DecisionTool | None:
    """Resolve a virtual decision tool id to the tool, tenant-contained.

    Returns the enabled DecisionTool whose virtual id equals ``tool_id``
    within ``tenant_id`` — or None when the id does not refer to a decision
    tool visible to the caller (used by skill binding validation and the
    skill executor).
    """
    result = await db.execute(
        select(DecisionTool)
        .where(
            DecisionTool.tenant_id == tenant_id,
            DecisionTool.enabled.is_(True),
        )
        .options(selectinload(DecisionTool.questions))
    )
    for tool in result.scalars().all():
        if decision_tool_virtual_tool_id(tool.id) == tool_id:
            return tool
    return None


def build_input_schema(tool: DecisionTool) -> dict[str, Any] | None:
    """Build the JSON-schema input contract from the referenced input data type.

    Used at the MCP surface (bridge catalog / internal list route) — the
    schema is derived, never stored.
    """
    fields = _field_names(tool.input_data_type)
    if not fields:
        return None
    return {
        "type": "object",
        "properties": {name: {"type": "string"} for name in fields},
        "required": fields,
    }


def generate_tool_description(tool: DecisionTool) -> str:
    """Auto-generate the tool description from the definition.

    Derived from the tool's purpose, name/tenant context, typed questions,
    and the referenced input/output data types. Stored on the entity and
    exposed to skills, agents, and MCP clients.
    """
    lines: list[str] = []
    title = f"Decision tool '{tool.name}'"
    if tool.purpose:
        lines.append(f"{title}: {tool.purpose.strip()}")
    else:
        lines.append(
            f"{title}: evaluates predefined System One questions against a "
            "constructed state and returns structured typed answers with "
            "confidence."
        )

    input_line = describe_data_type(tool.input_data_type, "input")
    output_line = describe_data_type(tool.output_data_type, "output")
    if input_line or output_line:
        lines.append("")
        if input_line:
            lines.append(input_line)
        if output_line:
            lines.append(output_line)

    questions = sorted(tool.questions, key=lambda q: q.ordering)
    if questions:
        lines.append("")
        lines.append("Questions:")
        for q in questions:
            desc = f"- `{q.question_key}` ({q.question_type.value})"
            if q.instructions:
                desc += f": {q.instructions.strip()}"
            options = q.criteria_options
            if isinstance(options, dict) and options:
                desc += f" Options: {', '.join(options.keys())}."
            elif isinstance(options, list) and options:
                desc += f" Rubric: {json.dumps(options)}."
            if not q.is_required:
                desc += " (optional)"
            lines.append(desc)

    if tool.state_preset:
        state_keys = ", ".join(tool.state_preset.keys())
        lines.append("")
        lines.append(f"State fields sent to the model: {state_keys}.")

    lines.append("")
    lines.append(
        "Returns per-question typed answers with probabilities and an "
        f"overall gate outcome (act >= {tool.act_threshold}, "
        f"confirm >= {tool.confirm_threshold}, else escalate)."
    )
    return "\n".join(lines)


class DecisionToolService:
    """CRUD for decision tools and their ordered questions (tenant-contained)."""

    async def get(
        self, db: AsyncSession, tool_id: uuid.UUID, tenant_id: uuid.UUID | None
    ) -> DecisionTool | None:
        """Fetch one tool by id, strictly within the caller's tenant."""
        result = await db.execute(
            select(DecisionTool)
            .where(DecisionTool.id == tool_id, DecisionTool.tenant_id == tenant_id)
            .options(selectinload(DecisionTool.questions))
        )
        return result.scalar_one_or_none()

    async def get_by_name(
        self, db: AsyncSession, name: str, tenant_id: uuid.UUID | None
    ) -> DecisionTool | None:
        """Resolve a tool by name within the caller's tenant (tenant-contained)."""
        result = await db.execute(
            select(DecisionTool)
            .where(DecisionTool.name == name, DecisionTool.tenant_id == tenant_id)
            .options(selectinload(DecisionTool.questions))
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID | None,
        status: str | None = None,
    ) -> list[DecisionTool]:
        """List decision tools within the caller's tenant, filterable by status."""
        query = (
            select(DecisionTool)
            .where(DecisionTool.tenant_id == tenant_id)
            .options(selectinload(DecisionTool.questions))
            .order_by(DecisionTool.name)
        )
        if status:
            query = query.where(DecisionTool.status == status)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        payload: DecisionToolCreate,
        tenant_id: uuid.UUID | None,
    ) -> DecisionTool:
        """Create a tool (plus questions) within the tenant.

        Rejects duplicate names within the tenant; the same name in a
        different tenant succeeds (tenant containment).
        """
        await self._ensure_name_available(db, payload.name, tenant_id)
        input_type, output_type = await self._resolve_data_types(
            db, payload.input_data_type_id, payload.output_data_type_id, tenant_id
        )
        self._validate_state_preset(payload.state_preset, input_type)
        tool = DecisionTool(
            tenant_id=tenant_id,
            name=payload.name,
            purpose=payload.purpose,
            input_data_type_id=payload.input_data_type_id,
            output_data_type_id=payload.output_data_type_id,
            input_data_type=input_type,
            output_data_type=output_type,
            state_preset=(
                {k: v.model_dump() for k, v in payload.state_preset.items()}
                if payload.state_preset
                else None
            ),
            act_threshold=payload.act_threshold,
            confirm_threshold=payload.confirm_threshold,
            provider_model=payload.provider_model,
            status=payload.status,
            enabled=payload.enabled,
        )
        # Assign the question list directly — avoids a lazy-load of the
        # (empty) relationship in a sync context after flush.
        tool.questions = self._build_questions(payload.questions)
        tool.description = generate_tool_description(tool)
        db.add(tool)
        await db.flush()
        await db.refresh(tool, ["questions"])
        logger.info(
            "Created decision tool '%s' (tenant=%s, id=%s)",
            tool.name,
            tenant_id,
            tool.id,
        )
        return tool

    async def update(
        self,
        db: AsyncSession,
        tool_id: uuid.UUID,
        payload: DecisionToolUpdate,
        tenant_id: uuid.UUID | None,
    ) -> DecisionTool:
        """Update definition fields; re-validates and regenerates the
        stored description. Question set (when provided) is replaced
        atomically."""
        tool = await self.get(db, tool_id, tenant_id)
        if not tool:
            raise DecisionToolValidationError(
                [f"Decision tool {tool_id} not found"]
            )

        data = payload.model_dump(exclude_unset=True)
        questions_payload = data.pop("questions", None)

        if "name" in data and data["name"] != tool.name:
            raise DecisionToolValidationError(
                ["Decision tool name is immutable; create a new tool instead"]
            )

        input_id = data.get("input_data_type_id", tool.input_data_type_id)
        output_id = data.get("output_data_type_id", tool.output_data_type_id)
        input_type, output_type = await self._resolve_data_types(
            db, input_id, output_id, tenant_id
        )
        if "input_data_type_id" in data or "output_data_type_id" in data:
            # Keep the relationship objects in sync so the regenerated
            # description reflects the new references.
            tool.input_data_type = input_type
            tool.output_data_type = output_type

        state_preset = data.get("state_preset")
        if state_preset is not None or "input_data_type_id" in data:
            preset = state_preset if state_preset is not None else tool.state_preset
            self._validate_state_preset(preset, input_type)

        for field, value in data.items():
            # state_preset arrives as plain dicts here
            setattr(tool, field, value)

        if questions_payload is not None:
            await db.execute(
                delete(DecisionToolQuestion).where(
                    DecisionToolQuestion.decision_tool_id == tool.id
                )
            )
            tool.questions = self._build_questions(questions_payload)

        tool.description = generate_tool_description(tool)
        await db.flush()
        # Refresh scalar columns (updated_at has an onupdate server default)
        # AND the questions relationship — both before serialization, since
        # expired-attribute access would otherwise require sync IO.
        await db.refresh(tool)
        await db.refresh(tool, ["questions"])
        return tool

    async def delete(
        self, db: AsyncSession, tool_id: uuid.UUID, tenant_id: uuid.UUID | None
    ) -> None:
        tool = await self.get(db, tool_id, tenant_id)
        if not tool:
            raise DecisionToolValidationError(
                [f"Decision tool {tool_id} not found"]
            )
        await db.delete(tool)

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _resolve_data_types(
        self,
        db: AsyncSession,
        input_data_type_id: uuid.UUID | None,
        output_data_type_id: uuid.UUID | None,
        tenant_id: uuid.UUID | None,
    ) -> tuple[AgentDataType | None, AgentDataType | None]:
        """Validate + resolve the referenced data types.

        A reference must resolve to an existing AgentDataType owned by the
        caller's tenant — strict tenant matching (the NULL shared slot is
        retired; adoption migrated legacy rows into the root tenant).
        """
        resolved: list[AgentDataType | None] = []
        errors: list[str] = []
        for label, ref_id in (
            ("input_data_type_id", input_data_type_id),
            ("output_data_type_id", output_data_type_id),
        ):
            if ref_id is None:
                resolved.append(None)
                continue
            result = await db.execute(
                select(AgentDataType).where(
                    AgentDataType.id == ref_id,
                    AgentDataType.tenant_id == tenant_id,
                )
            )
            data_type = result.scalar_one_or_none()
            if data_type is None:
                errors.append(
                    f"{label}: data type {ref_id} not found or not visible "
                    "to this tenant"
                )
            resolved.append(data_type)
        if errors:
            raise DecisionToolValidationError(errors)
        return resolved[0], resolved[1]

    @staticmethod
    def _validate_state_preset(
        state_preset: dict[str, Any] | None,
        input_type: AgentDataType | None,
    ) -> None:
        """Validate state mappings against the chosen input data type.

        ``input``-sourced mapping keys must be fields of the referenced
        input data type (when one is chosen); ``agent_data`` keys are free-form.
        """
        if not state_preset:
            return
        errors: list[str] = []
        field_names = set(_field_names(input_type))
        for state_key, raw in state_preset.items():
            mapping = (
                raw
                if isinstance(raw, StatePresetMapping)
                else StatePresetMapping.model_validate(raw)
            )
            if not state_key:
                errors.append("state_preset keys must be non-empty")
            if not str(mapping.key).strip():
                errors.append(
                    f"state_preset mapping for '{state_key}' has an empty data key"
                )
                continue
            if (
                mapping.source == "input"
                and input_type is not None
                and field_names
                and mapping.key not in field_names
            ):
                errors.append(
                    f"state_preset mapping for '{state_key}': key "
                    f"'{mapping.key}' is not a field of the input data type "
                    f"'{input_type.name}'"
                )
        if errors:
            raise DecisionToolValidationError(errors)

    async def _ensure_name_available(
        self,
        db: AsyncSession,
        name: str,
        tenant_id: uuid.UUID | None,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        """Reject duplicate names within one tenant; other tenants unaffected."""
        query = select(DecisionTool.id).where(
            DecisionTool.name == name, DecisionTool.tenant_id == tenant_id
        )
        if exclude_id is not None:
            query = query.where(DecisionTool.id != exclude_id)
        result = await db.execute(query)
        if result.scalar_one_or_none() is not None:
            raise DecisionToolNameConflictError(name)

    @staticmethod
    def _build_questions(questions: list) -> list[DecisionToolQuestion]:
        """Build ordered DecisionToolQuestion ORM instances (validates keys)."""
        built: list[DecisionToolQuestion] = []
        seen_keys: set[str] = set()
        for order, q in enumerate(questions):
            if q.question_key in seen_keys:
                raise DecisionToolValidationError(
                    [f"Duplicate question_key '{q.question_key}'"]
                )
            seen_keys.add(q.question_key)
            built.append(
                DecisionToolQuestion(
                    ordering=q.ordering if q.ordering else order,
                    question_key=q.question_key,
                    question_type=q.question_type,
                    instructions=q.instructions,
                    criteria_options=q.criteria_options,
                    is_required=q.is_required,
                )
            )
        return built


__all__ = [
    "DecisionToolNameConflictError",
    "DecisionToolService",
    "DecisionToolValidationError",
    "DecisionQuestionType",
    "build_input_schema",
    "decision_tool_virtual_tool_id",
    "generate_tool_description",
    "resolve_virtual_tool_id",
]
