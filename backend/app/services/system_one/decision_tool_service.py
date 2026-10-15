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
- Questions are OPTIONAL: a tool with no manual questions derives them
  1:1 from its output data type at execution time (see
  ``derive_questions_from_output_type``); manual questions win as override.
- State preset maps FROM THE INPUT ONLY: each mapping is
  ``state_key → input property``. The legacy ``agent_data`` source is
  retired — payloads carrying it are rejected by the schema with a clear
  error; rows persisted before the retirement are skipped with a warning
  (at validation and at execution) and dropped on the next save.
- ``resolve_state_mapping`` implements the auto-match contract shared with
  the authoring form: every state key/placeholder equal to an input data
  type field name resolves 1:1 automatically (asks the user NOTHING);
  keys with no same-named input property are reported as ``unmatched`` so
  the UI can ask the user to map them explicitly.
- A tool is READY only when both its input and output data types are set;
  enabling a non-ready tool is rejected with an actionable error
  (``_validate_readiness``) — disabled drafts may keep missing types.
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
from app.db.models.decision_model_availability import DecisionModelAvailability
from app.db.models.decision_tools import (
    DecisionQuestionType,
    DecisionTool,
    DecisionToolQuestion,
)
from app.schemas.decision_tools import (
    DecisionToolCreate,
    DecisionToolQuestionCreate,
    DecisionToolUpdate,
    StatePresetMapping,
)
from app.services.system_one.decision_model_availability_service import (
    DecisionModelCatalogueError,
    DecisionModelCatalogueService,
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


#: Appended to an enabled-but-unready tool's LLM-facing description so the
#: model knows the tool exists but is NOT callable — it should REPORT the
#: unavailability to the user instead of emitting raw tool-call syntax.
UNAVAILABLE_TOOL_NOTE = (
    "NOTE: This tool is currently unavailable — missing input/output "
    "data type configuration."
)


def unavailable_tool_message(tool_name: str) -> str:
    """In-band execution error for an enabled-but-unready decision tool."""
    return (
        f"Tool '{tool_name}' is not ready: input/output data types are not "
        "configured. Ask your workspace administrator to configure them "
        "in Decision Tools."
    )


def is_decision_tool_ready(tool: DecisionTool) -> bool:
    """A tool is READY when both its input and output data types are set.

    Product-owner rule: a decision tool must be READY before it can be
    enabled/used — otherwise its LLM function schema is empty (input) and
    its results are untyped (output).
    """
    return (
        tool.input_data_type_id is not None
        and tool.output_data_type_id is not None
    )


def _validate_readiness(
    name: str,
    enabled: bool,
    input_data_type_id: uuid.UUID | None,
    output_data_type_id: uuid.UUID | None,
) -> None:
    """Reject enabling a tool whose input/output contracts are incomplete.

    Disabled tools may keep missing types (drafts), but ``enabled=True``
    with a NULL ``input_data_type_id`` and/or ``output_data_type_id`` is
    rejected with an actionable message naming the missing piece(s).
    """
    if not enabled:
        return
    missing: list[str] = []
    if input_data_type_id is None:
        missing.append("input data type")
    if output_data_type_id is None:
        missing.append("output data type")
    if missing:
        raise DecisionToolValidationError(
            [
                f"Decision tool '{name}' cannot be enabled: "
                f"{' and '.join(missing)} "
                f"{'are' if len(missing) > 1 else 'is'} required "
                "(set them in the decision tool definition, or disable "
                "the tool first)"
            ]
        )


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


def _parse_state_mapping(raw: Any) -> StatePresetMapping | None:
    """Parse a persisted state-preset row, tolerating legacy shapes.

    Rows persisted before the ``agent_data`` retirement (or otherwise
    invalid) return None — callers skip them with a warning instead of
    failing validation/execution.
    """
    try:
        mapping = (
            raw
            if isinstance(raw, StatePresetMapping)
            else StatePresetMapping.model_validate(raw)
        )
    except Exception:
        return None
    if mapping.source != "input":
        return None
    return mapping


def resolve_state_mapping(
    state_preset: dict[str, Any] | None,
    placeholders: list[str],
    input_fields: list[str],
) -> dict[str, Any]:
    """Auto-match contract shared with the authoring form.

    The state keys are the placeholders a tool's prompt/questions use
    (backtick-quoted paths detected in question instructions) plus the
    explicit preset keys. Resolution per key:

    - An explicit ``state_key → input property`` mapping wins (rename).
    - Otherwise the key resolves 1:1 (``key → key``) — the default, and
      exactly what an empty preset does in ``build_state``.

    A key is ``matched`` when its resolved input property is a field of
    the input data type — the user is asked NOTHING. Keys that cannot be
    resolved to a known input property are ``unmatched`` — the UI asks
    the user to map them.

    Returns ``{"matched": {state_key: input_property}, "unmatched": [keys]}``
    (both in first-seen order).
    """
    keys: list[str] = []
    for state_key in (state_preset or {}):
        k = str(state_key).strip()
        if k and k not in keys:
            keys.append(k)
    for placeholder in placeholders:
        k = (placeholder or "").strip()
        if k and k not in keys:
            keys.append(k)

    fields = {f for f in input_fields if f}
    matched: dict[str, str] = {}
    unmatched: list[str] = []
    for key in keys:
        raw = (state_preset or {}).get(key)
        mapping = _parse_state_mapping(raw) if raw is not None else None
        resolved = mapping.key.strip() if mapping else key
        if resolved in fields:
            matched[key] = resolved
        else:
            unmatched.append(key)
    return {"matched": matched, "unmatched": unmatched}


def describe_data_type(data_type: AgentDataType | None, role: str) -> str | None:
    """One-line description of a referenced data type for the tool description."""
    if not data_type:
        return None
    names = _field_names(data_type)
    fields = f" Fields: {', '.join(names)}." if names else ""
    return f"{role.capitalize()} data type: {data_type.name} ({data_type.slug}).{fields}"


# Default rubric legend for score questions derived from number fields.
DEFAULT_SCORE_RUBRIC = [
    "1 - very poor",
    "2 - poor",
    "3 - adequate",
    "4 - good",
    "5 - excellent",
]

# Manual questions take precedence; derivation only fills the gap.


def _derive_question_specs(fields: Any) -> list[dict[str, Any]]:
    """Derive question payload specs from an AgentDataType field list.

    Rules (product-owner approved):
    - enum field    → ``choice``; ``criteria_options`` maps allowed value →
      description VERBATIM from the enum (missing description → the value
      itself as description).
    - number field  → ``score``; default 1–5 rubric legend.
    - string field  → ``choice`` used as the free-form text question type
      (open answer; empty criteria dict = unrestricted).
    - boolean field → ``noul`` (binary judgment).

    ``question_key`` is the field name; ``is_required`` mirrors the field's
    required flag; ``ordering`` follows field order.
    """
    specs: list[dict[str, Any]] = []
    if not isinstance(fields, list):
        return specs
    for order, field in enumerate(fields):
        if not isinstance(field, dict) or not field.get("name"):
            continue
        name = str(field["name"])
        ftype = str(field.get("type", "string")).lower()
        description = (field.get("description") or "").strip() or None
        required = bool(field.get("required", True))
        spec: dict[str, Any] = {
            "ordering": order,
            "question_key": name,
            "instructions": description or f"Answer for output field '{name}'.",
            "is_required": required,
        }
        if ftype == "enum":
            raw_values = field.get("enum_values") or []
            criteria: dict[str, str] = {}
            for entry in raw_values:
                if isinstance(entry, str):
                    criteria[entry] = entry
                elif isinstance(entry, dict) and entry.get("value") is not None:
                    value = str(entry["value"])
                    criteria[value] = str(
                        entry.get("description") or value
                    )
            spec["question_type"] = DecisionQuestionType.choice
            spec["criteria_options"] = criteria or None
        elif ftype == "number":
            spec["question_type"] = DecisionQuestionType.score
            spec["criteria_options"] = list(DEFAULT_SCORE_RUBRIC)
        elif ftype == "boolean":
            spec["question_type"] = DecisionQuestionType.noul
            spec["criteria_options"] = None
        else:  # string (and unknown types) → free-form text answer
            spec["question_type"] = DecisionQuestionType.choice
            spec["criteria_options"] = {}
            spec["instructions"] = (
                description or f"Free-form answer for output field '{name}'."
            )
        specs.append(spec)
    return specs


def derive_questions_from_output_type(
    db: AsyncSession | None,
    tool: DecisionTool,
) -> list[DecisionToolQuestion]:
    """Derive transient DecisionToolQuestion instances from the tool's
    OUTPUT data type (1:1 from its typed fields).

    The questions are NOT persisted — they are built at execution /
    description time whenever the tool has no manually-authored questions
    (manual questions win as the override). ``db`` is accepted for
    signature compatibility with execution-time callers; the output data
    type is already eager-loaded on the tool.
    """
    specs = _derive_question_specs(
        tool.output_data_type.fields if tool.output_data_type else None
    )
    return [
        DecisionToolQuestion(
            ordering=spec["ordering"],
            question_key=spec["question_key"],
            question_type=spec["question_type"],
            instructions=spec["instructions"],
            criteria_options=spec["criteria_options"],
            is_required=spec["is_required"],
        )
        for spec in specs
    ]


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
    derived = False
    if not questions and tool.output_data_type is not None:
        # No manual questions: the effective question set is derived from
        # the output data type — surface it in the description too.
        questions = derive_questions_from_output_type(None, tool)
        derived = True
    if questions:
        lines.append("")
        lines.append(
            "Questions (auto-derived from the output data type):"
            if derived
            else "Questions:"
        )
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


def _coerce_question_payloads(
    questions: list[Any],
) -> list[DecisionToolQuestionCreate]:
    """Coerce question payloads through the pydantic schema.

    Accepts both raw dicts (e.g. payloads re-serialized via
    ``model_dump`` or read back from storage) and existing
    ``DecisionToolQuestionCreate`` instances, so downstream code can rely
    on attribute access (``q.question_key`` etc.).
    """
    return [
        q if isinstance(q, DecisionToolQuestionCreate)
        else DecisionToolQuestionCreate.model_validate(q)
        for q in questions
    ]


class DecisionToolService:
    """CRUD for decision tools and their ordered questions (tenant-contained)."""

    def __init__(
        self,
        catalogue_service: DecisionModelCatalogueService | None = None,
    ) -> None:
        self._catalogue = catalogue_service or DecisionModelCatalogueService()

    async def _validate_model_selection(
        self,
        db: AsyncSession,
        availability_id: uuid.UUID | None,
        tenant_id: uuid.UUID | None,
    ) -> None:
        """Validate the selected decision model exists AND is enabled
        (provider enabled + model enabled) within the caller's tenant."""
        if availability_id is None:
            return
        try:
            await self._catalogue.resolve_selection(
                db, availability_id, tenant_id
            )
        except DecisionModelCatalogueError as exc:
            raise DecisionToolValidationError([f"decision model: {exc}"]) from exc

    async def get(
        self, db: AsyncSession, tool_id: uuid.UUID, tenant_id: uuid.UUID | None
    ) -> DecisionTool | None:
        """Fetch one tool by id, strictly within the caller's tenant."""
        result = await db.execute(
            select(DecisionTool)
            .where(DecisionTool.id == tool_id, DecisionTool.tenant_id == tenant_id)
            .options(
                selectinload(DecisionTool.questions),
                selectinload(DecisionTool.decision_model_availability),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_name(
        self, db: AsyncSession, name: str, tenant_id: uuid.UUID | None
    ) -> DecisionTool | None:
        """Resolve a tool by name within the caller's tenant (tenant-contained)."""
        result = await db.execute(
            select(DecisionTool)
            .where(DecisionTool.name == name, DecisionTool.tenant_id == tenant_id)
            .options(
                selectinload(DecisionTool.questions),
                selectinload(DecisionTool.decision_model_availability),
            )
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
            .options(
                selectinload(DecisionTool.questions),
                selectinload(DecisionTool.decision_model_availability),
            )
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
        await self._validate_model_selection(
            db, payload.decision_model_availability_id, tenant_id
        )
        _validate_readiness(
            payload.name,
            payload.enabled,
            payload.input_data_type_id,
            payload.output_data_type_id,
        )
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
            decision_model_availability_id=payload.decision_model_availability_id,
            status=payload.status,
            enabled=payload.enabled,
        )
        # Assign the question list directly — avoids a lazy-load of the
        # (empty) relationship in a sync context after flush. Coerce in
        # case callers pass raw dicts.
        tool.questions = self._build_questions(
            _coerce_question_payloads(payload.questions)
        )
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
        if questions_payload is not None:
            # model_dump() serializes the nested pydantic question models
            # into plain dicts — coerce back through the schema so both
            # dicts and model instances work downstream.
            questions_payload = _coerce_question_payloads(
                payload.questions or []
            )

        if "name" in data and data["name"] != tool.name:
            raise DecisionToolValidationError(
                ["Decision tool name is immutable; create a new tool instead"]
            )

        input_id = data.get("input_data_type_id", tool.input_data_type_id)
        output_id = data.get("output_data_type_id", tool.output_data_type_id)
        effective_enabled = data.get("enabled", tool.enabled)
        # Readiness gate: enabling (or staying enabled) without both data
        # types is rejected; clearing types while enabled hits the same
        # check (disable first). Disabling-first-then-clear passes.
        _validate_readiness(tool.name, effective_enabled, input_id, output_id)
        await self._validate_model_selection(
            db,
            data.get(
                "decision_model_availability_id",
                tool.decision_model_availability_id,
            ),
            tenant_id,
        )
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

        Mappings are ``state_key → input property`` (source is always
        ``input`` — the schema rejects anything else with a clear error).
        Legacy ``agent_data`` rows persisted before the retirement are
        SKIPPED with a warning (they are dropped when the client next
        saves the preset). ``input``-sourced mapping keys must be fields
        of the referenced input data type (when one is chosen).
        """
        if not state_preset:
            return
        errors: list[str] = []
        field_names = set(_field_names(input_type))
        for state_key, raw in state_preset.items():
            mapping = _parse_state_mapping(raw)
            if mapping is None:
                logger.warning(
                    "state_preset row for '%s' ignored: legacy non-input "
                    "source or invalid mapping (state maps from the input "
                    "only); it will be dropped on the next save",
                    state_key,
                )
                continue
            if not state_key:
                errors.append("state_preset keys must be non-empty")
                continue
            if not str(mapping.key).strip():
                errors.append(
                    f"state_preset mapping for '{state_key}' has an empty data key"
                )
                continue
            if (
                input_type is not None
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
    "is_decision_tool_ready",
    "UNAVAILABLE_TOOL_NOTE",
    "unavailable_tool_message",
    "resolve_state_mapping",
    "decision_tool_virtual_tool_id",
    "generate_tool_description",
    "derive_questions_from_output_type",
    "resolve_virtual_tool_id",
]
