"""AI-assisted decision tool authoring.

Reuses ``workflow_authoring_service.generate_workflow_text`` (the mechanism
behind the skill editor's ``POST /skills/workflow/generate``) with a
decision-tool-specific prompt, then validates/normalizes the model's JSON
answer through the existing decision-tool question schemas.

The draft carries typed questions (choice / score / noul with criteria),
a suggested state preset, and the backtick-quoted state paths detected in
the drafted instructions (suggested mappings for the authoring form).
"""
from __future__ import annotations

import json
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_data_type import AgentDataType
from app.schemas.decision_tools import (
    DecisionToolGenerateResponse,
    DecisionToolQuestionCreate,
    StatePresetMapping,
)
from app.services.agents.workflow_authoring_service import (
    WorkflowAuthoringError,
    generate_workflow_text,
)

logger = logging.getLogger(__name__)

#: Backtick-quoted state paths, e.g. ```input.tier` ``.
_STATE_PATH_RE = re.compile(r"`([^`]+)`")

_SYSTEM_PROMPT = (
    "You draft System One decision tool definitions for an enterprise agent "
    "platform. A decision tool asks a fixed set of atomic typed questions "
    "(choice, score, noul) against a constructed state. Respond with JSON "
    "only — no markdown fences — in this exact shape:\n"
    "{\n"
    '  "questions": [\n'
    '    {"question_key": "kebab_or_snake_key", "question_type": '
    '"choice"|"score"|"noul", "instructions": "... may reference state paths '
    'in backticks like `input.tier`", "criteria_options": {...for choice...} '
    "| [...ordered rubric for score...] | null, \"is_required\": true}\n"
    "  ],\n"
    '  "state_preset": {"state_key": {"source": "input", '
    '"key": "input_field_name"}}\n'
    "}\n"
    "Rules: choice questions require a non-empty criteria_options object "
    "(option key → description); score questions require a non-empty ordered "
    "rubric list; noul questions must have criteria_options null. Every "
    "value the questions need from the execution input must be mapped in "
    "state_preset with source 'input' and a key that is a field of the "
    "input data type (source 'agent_data' is retired — never emit it); "
    "reference those state keys in backticks inside instructions."
)


def extract_state_placeholders(text: str) -> list[str]:
    """Extract backtick-quoted state paths from question instruction text.

    Backend mirror of the frontend ``detectStatePlaceholders`` util (regex
    ```([^`]+)` ``), exposed via the generate endpoint response.
    """
    seen: list[str] = []
    for match in _STATE_PATH_RE.findall(text or ""):
        path = match.strip()
        if path and path not in seen:
            seen.append(path)
    return seen


def _describe_type(data_type: AgentDataType | None, role: str) -> str:
    if not data_type:
        return f"- {role} data type: none (state-only)."
    fields = data_type.fields if isinstance(data_type.fields, list) else []
    lines = [f"- {role} data type '{data_type.name}' (slug: {data_type.slug}):"]
    for field in fields:
        if isinstance(field, dict):
            lines.append(
                f"    - {field.get('name')} ({field.get('type', 'string')}): "
                f"{field.get('description', '')}".rstrip(": ")
            )
        elif isinstance(field, str):
            lines.append(f"    - {field} (string)")
    return "\n".join(lines)


def _parse_draft(
    raw_text: str,
    input_type: AgentDataType | None,
) -> tuple[list[DecisionToolQuestionCreate], dict[str, StatePresetMapping]]:
    """Parse + validate the model's JSON draft through the question schemas."""
    text = raw_text.strip()
    if text.startswith("```"):
        # Strip a markdown fence if the model added one despite instructions.
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise WorkflowAuthoringError(
            f"Model returned invalid JSON draft: {exc}"
        ) from exc

    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        raise WorkflowAuthoringError("Model draft is missing a questions list")

    try:
        questions = [DecisionToolQuestionCreate.model_validate(q) for q in data["questions"]]
    except Exception as exc:  # noqa: BLE001 — surface pydantic errors as authoring errors
        raise WorkflowAuthoringError(f"Model draft failed validation: {exc}") from exc

    state_preset: dict[str, StatePresetMapping] = {}
    raw_preset = data.get("state_preset")
    if isinstance(raw_preset, dict):
        input_fields = (
            input_type.fields
            if input_type is not None
            and isinstance(input_type.fields, list)
            else []
        )
        field_names = {
            f.get("name")
            for f in input_fields
            if isinstance(f, dict)
        }
        for state_key, mapping in raw_preset.items():
            try:
                parsed = StatePresetMapping.model_validate(mapping)
            except Exception:
                continue
            if parsed.source == "input" and field_names and parsed.key not in field_names:
                continue  # drop mappings that don't resolve against the input type
            state_preset[str(state_key)] = parsed

    if not questions:
        raise WorkflowAuthoringError("Model draft contained no questions")
    return questions, state_preset


async def generate_decision_draft(
    db: AsyncSession,
    *,
    description: str,
    model_id: str,
    input_data_type: AgentDataType | None = None,
    output_data_type: AgentDataType | None = None,
    existing_questions: list[DecisionToolQuestionCreate] | None = None,
) -> DecisionToolGenerateResponse:
    """Draft questions + state mapping via the workflow authoring LLM path."""
    input_fields = ", ".join(
        f.get("name", "")
        for f in (input_data_type.fields if input_data_type and isinstance(input_data_type.fields, list) else [])
        if isinstance(f, dict)
    )
    existing_block = ""
    if existing_questions:
        existing_block = (
            "\nExisting draft questions (refine rather than replace unless "
            "the description demands it):\n"
            + json.dumps(
                [q.model_dump(mode="json") for q in existing_questions], indent=2
            )
        )
    user_prompt = (
        "Decision tool purpose/description:\n"
        f"{description.strip()}\n\n"
        f"{_describe_type(input_data_type, 'input')}\n"
        f"{_describe_type(output_data_type, 'output')}\n"
        f"Input data type field names: {input_fields or '(none)'}\n"
        f"{existing_block}\n\n"
        "Draft the typed questions and the state preset mapping."
    )

    raw = await generate_workflow_text(
        model_id=model_id,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        db=db,
    )
    questions, state_preset = _parse_draft(raw, input_data_type)

    detected = sorted(
        {
            path
            for q in questions
            for path in extract_state_placeholders(q.instructions or "")
        }
    )
    return DecisionToolGenerateResponse(
        questions=questions,
        state_preset=state_preset or None,
        detected_state_paths=detected,
        model_id=model_id,
    )


__all__ = [
    "extract_state_placeholders",
    "generate_decision_draft",
]
