"""Workflow authoring helpers for Skill and SOP generation and preview."""

from __future__ import annotations

import json
from typing import Any

from app.db.models.agents import ModelConfig
from app.services.agents.model_binding import ModelBindingError, ModelBindingLayer


class WorkflowAuthoringError(Exception):
    """Raised when workflow generation cannot be completed."""


async def resolve_model_config_for_generation(model_id: str, db: Any) -> ModelConfig:
    """Resolve the ModelConfig that enables model_id."""
    model_layer = ModelBindingLayer()
    return await model_layer.resolve_model_config(model_id, db)


async def generate_workflow_text(*, model_id: str, system_prompt: str, user_prompt: str, db: Any) -> str:
    """Generate workflow text using the selected model and model config."""
    model_layer = ModelBindingLayer()
    try:
        model_config = await model_layer.resolve_model_config(model_id, db)
        config_dict = {
            "provider_type": model_config.provider_type.value,
            "api_base_url": model_config.api_base_url,
            "api_key": model_layer._resolve_api_key(model_config),
        }
        response = await model_layer.complete_from_context(
            model_id=model_id,
            model_config_dict=config_dict,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1400,
        )
    except ModelBindingError as exc:
        raise WorkflowAuthoringError(str(exc)) from exc
    except Exception as exc:
        raise WorkflowAuthoringError(f"Workflow generation failed: {exc}") from exc

    text = ModelBindingLayer.extract_text(response, model_config.provider_type).strip()
    if not text:
        raise WorkflowAuthoringError("Workflow generation returned an empty response")
    return text


def build_skill_instruction_file(*, workflow: str, tools: list[dict[str, Any]]) -> str:
    """Build the single formatted instruction file for Skill preview."""
    lines: list[str] = ["# Skill Workflow Instruction File", "", "## Workflow", workflow.strip() or "(empty workflow)"]

    lines.append("")
    lines.append("## Tools")
    if not tools:
        lines.append("- No tools selected")
    else:
        for tool in tools:
            lines.append(f"- `{tool.get('name', 'unknown-tool')}`")
            description = (tool.get("description") or "").strip()
            if description:
                lines.append(f"  - Description: {description}")
            input_schema = tool.get("input_schema")
            if isinstance(input_schema, dict):
                lines.append("  - Input Schema:")
                lines.append("```json")
                lines.append(json.dumps(input_schema, indent=2))
                lines.append("```")

    return "\n".join(lines)


def build_sop_instruction_file(*, workflow: str, steps: list[dict[str, Any]]) -> str:
    """Build the single formatted instruction file for SOP preview."""
    lines: list[str] = ["# SOP Workflow Instruction File", "", "## Workflow", workflow.strip() or "(empty workflow)"]

    lines.append("")
    lines.append("## Ordered Steps")
    if not steps:
        lines.append("- No steps defined")
    else:
        for step in sorted(steps, key=lambda s: int(s.get("order", 0))):
            order = int(step.get("order", 0))
            step_type = str(step.get("step_type", "skill_invocation"))
            name = (step.get("name") or "Unnamed step").strip()
            description = (step.get("description") or "").strip()
            target_agent_type_id = step.get("target_agent_type_id")
            skill_id = step.get("skill_id")

            lines.append(f"{order + 1}. {name} ({step_type})")
            if description:
                lines.append(f"   - Description: {description}")
            if skill_id:
                lines.append(f"   - Skill ID: {skill_id}")
            if target_agent_type_id:
                lines.append(f"   - Delegates to Agent Type ID: {target_agent_type_id}")

    return "\n".join(lines)
