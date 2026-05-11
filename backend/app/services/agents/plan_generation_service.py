"""PlanGenerationService — LLM-based plan generation on agent type save.

Traverses the role→SOP→Skill→Tool graph, constructs a detailed prompt with
agent context, invokes the configured LLM, parses the response into structured
plan steps, calls TopologyBuilderService for the topology payload, and upserts
the AgentPlan row. Plan generation failure is non-blocking.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.agents import AgentPlan, AgentPlanStatus, AgentType
from app.services.agents.topology_builder_service import TopologyBuilderService

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

_topology_builder = TopologyBuilderService()


class PlanGenerationService:
    """
    Orchestrates LLM-based plan generation when an AgentType is saved.

    Call generate_plan(agent_type, db) after a successful commit of the agent type.
    The method is non-blocking: any exception is caught, a failed AgentPlan record
    is upserted, and the method returns the plan record without re-raising.
    """

    async def generate_plan(
        self, agent_type: AgentType, db: AsyncSession
    ) -> AgentPlan:
        """
        Generate a plan for the given agent type and upsert the AgentPlan row.

        Args:
            agent_type: The saved AgentType ORM instance.
            db: Active async SQLAlchemy session.

        Returns:
            The upserted AgentPlan row (success or failed status).
        """
        with tracer.start_as_current_span(
            "plan_generation.generate_plan",
            attributes={
                "agent_type_id": str(agent_type.id),
                "role_id": str(agent_type.role_id) if agent_type.role_id else "none",
            },
        ) as span:
            config_hash = self._compute_config_hash(agent_type)

            try:
                plan_steps, topology = await self._do_generate(agent_type, db)
                plan = await self._upsert_plan(
                    agent_type_id=agent_type.id,
                    plan_steps=plan_steps,
                    topology=topology,
                    status=AgentPlanStatus.success,
                    error=None,
                    config_hash=config_hash,
                    db=db,
                )
                span.set_attribute("status", "success")
                span.set_attribute("step_count", len(plan_steps))
                logger.info(
                    "Plan generation succeeded for agent_type=%s: %d steps",
                    agent_type.id,
                    len(plan_steps),
                )
                return plan

            except Exception as exc:
                error_msg = str(exc)[:990]
                logger.warning(
                    "Plan generation failed for agent_type=%s (non-blocking): %s",
                    agent_type.id,
                    error_msg,
                )
                span.set_attribute("status", "failed")
                span.set_attribute("error", error_msg)
                plan = await self._upsert_plan(
                    agent_type_id=agent_type.id,
                    plan_steps=None,
                    topology=None,
                    status=AgentPlanStatus.failed,
                    error=error_msg,
                    config_hash=config_hash,
                    db=db,
                )
                return plan

    # ── Internal orchestration ────────────────────────────────────────────────

    async def _do_generate(
        self, agent_type: AgentType, db: AsyncSession
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Core generation logic — raises on failure (caller handles non-blocking)."""
        # Step 1: Resolve the role→SOP→Skill→Tool graph
        graph = await self._resolve_graph(agent_type, db)

        # Step 2: Construct prompt
        prompt = self._build_prompt(agent_type, graph)

        # Step 3: Invoke LLM
        raw_response = await self._invoke_llm(agent_type, db, prompt)

        # Step 4: Parse plan steps
        plan_steps = self._parse_plan_steps(raw_response)

        # Step 5: Build topology
        topology = _topology_builder.build_topology(graph)

        return plan_steps, topology

    async def _resolve_graph(
        self, agent_type: AgentType, db: AsyncSession
    ) -> dict[str, Any]:
        """Traverse role→SOP→Skill→Tool graph and return a structured dict."""
        from app.db.models.agents import AgentIdentity, AgentRole, AgentRoleSOP, AgentRoleSkill
        from app.db.models.skills import Skill, SkillToolBinding, Sop, SopStep, SopStepType
        from app.db.models.mcp_hub import McpTool

        # Build agent data
        agent_data: dict[str, Any] = {
            "id": str(agent_type.id),
            "name": agent_type.name,
            "description": agent_type.description,
        }

        # Load identity if assigned
        identity_data: dict[str, Any] | None = None
        if agent_type.identity_id:
            id_result = await db.execute(
                select(AgentIdentity).where(AgentIdentity.id == agent_type.identity_id)
            )
            identity_obj = id_result.scalar_one_or_none()
            if identity_obj:
                identity_data = {"id": str(identity_obj.id), "name": identity_obj.name}

        if not agent_type.role_id:
            return {"agent": agent_data, "identity": identity_data, "role": None, "sops": [], "skills": [], "tools": []}

        # Load role
        role_result = await db.execute(
            select(AgentRole).where(AgentRole.id == agent_type.role_id)
        )
        role = role_result.scalar_one_or_none()
        if not role:
            return {"agent": agent_data, "identity": identity_data, "role": None, "sops": [], "skills": [], "tools": []}

        role_data: dict[str, Any] = {
            "id": str(role.id),
            "name": role.name,
            "description": role.description,
        }

        # Load SOPs assigned to role
        sop_rows = await db.execute(
            select(AgentRoleSOP.sop_id).where(AgentRoleSOP.role_id == role.id)
        )
        sop_ids = [row[0] for row in sop_rows.fetchall()]

        sop_data_list: list[dict[str, Any]] = []
        sop_skill_ids: dict[str, list[str]] = {}  # sop_id -> [skill_ids from steps]

        if sop_ids:
            sops_result = await db.execute(
                select(Sop)
                .where(Sop.id.in_(sop_ids))
                .options(selectinload(Sop.steps))
            )
            for sop in sops_result.scalars().all():
                sop_data_list.append({
                    "id": str(sop.id),
                    "name": sop.name,
                    "description": sop.description,
                    "instructions": sop.instructions,
                    "steps": [
                        {
                            "order": step.order,
                            "step_type": step.step_type.value if step.step_type else "skill_invocation",
                            "name": step.name,
                            "description": step.description,
                        }
                        for step in sorted(sop.steps, key=lambda s: s.order)
                    ],
                })
                # Collect skill IDs referenced in SOP steps
                for step in sop.steps:
                    if step.step_type == SopStepType.skill_invocation and step.skill_id:
                        sop_skill_ids.setdefault(str(sop.id), []).append(str(step.skill_id))

        # Collect all skill IDs: from SOP steps + directly assigned
        direct_skill_rows = await db.execute(
            select(AgentRoleSkill.skill_id).where(AgentRoleSkill.role_id == role.id)
        )
        direct_skill_ids = {str(row[0]) for row in direct_skill_rows.fetchall()}

        sop_step_skill_ids: set[str] = set()
        for ids in sop_skill_ids.values():
            sop_step_skill_ids.update(ids)

        all_skill_ids_str = direct_skill_ids | sop_step_skill_ids
        all_skill_ids = [uuid.UUID(sid) for sid in all_skill_ids_str]

        skill_data_list: list[dict[str, Any]] = []
        tool_data_list: list[dict[str, Any]] = []

        if all_skill_ids:
            skills_result = await db.execute(
                select(Skill)
                .where(Skill.id.in_(all_skill_ids))
                .options(selectinload(Skill.tool_bindings).selectinload(SkillToolBinding.tool))
            )
            for skill in skills_result.scalars().all():
                # Determine which SOPs reference this skill (for topology edges)
                parent_sop_ids = [
                    sop_id for sop_id, skill_ids in sop_skill_ids.items()
                    if str(skill.id) in skill_ids
                ]
                skill_data_list.append({
                    "id": str(skill.id),
                    "name": skill.name,
                    "description": skill.description,
                    "instructions": skill.instructions,
                    "sop_ids": parent_sop_ids,
                })
                # Collect tools
                for binding in skill.tool_bindings:
                    if binding.tool:
                        tool_data_list.append({
                            "name": binding.tool.name,
                            "description": binding.tool.description,
                            "skill_id": str(skill.id),
                        })

        return {
            "agent": agent_data,
            "identity": identity_data,
            "role": role_data,
            "sops": sop_data_list,
            "skills": skill_data_list,
            "tools": tool_data_list,
        }

    def _build_prompt(
        self, agent_type: AgentType, graph: dict[str, Any]
    ) -> str:
        """Construct the LLM prompt with agent context."""
        lines: list[str] = [
            "You are a technical assistant generating an implementation plan for an AI agent.",
            "",
            "## Agent Configuration",
            f"- **Name**: {agent_type.name}",
        ]
        if agent_type.description:
            lines.append(f"- **Description**: {agent_type.description}")
        if agent_type.system_instruction:
            lines.extend([
                "",
                "### System Instruction",
                agent_type.system_instruction,
            ])

        role = graph.get("role")
        if role:
            lines.extend([
                "",
                "## Assigned Role",
                f"- **Role Name**: {role['name']}",
            ])
            if role.get("description"):
                lines.append(f"- **Role Description**: {role['description']}")

        sops = graph.get("sops", [])
        if sops:
            lines.extend(["", "## Standard Operating Procedures (SOPs)"])
            for sop in sops:
                lines.append(f"\n### SOP: {sop['name']}")
                if sop.get("description"):
                    lines.append(f"- Description: {sop['description']}")
                if sop.get("instructions"):
                    lines.append(f"- Instructions: {sop['instructions']}")
                if sop.get("steps"):
                    lines.append("- Steps:")
                    for step in sop["steps"]:
                        lines.append(
                            f"  {step['order']}. [{step['step_type']}] {step.get('name') or ''} — {step.get('description') or ''}"
                        )

        skills = graph.get("skills", [])
        if skills:
            lines.extend(["", "## Available Skills"])
            for skill in skills:
                lines.append(f"\n### Skill: {skill['name']}")
                if skill.get("description"):
                    lines.append(f"- Description: {skill['description']}")
                if skill.get("instructions"):
                    lines.append(f"- Instructions: {skill['instructions']}")

        tools = graph.get("tools", [])
        if tools:
            lines.extend(["", "## Available MCP Tools"])
            for tool in tools:
                desc = tool.get("description") or ""
                lines.append(f"- `{tool['name']}`: {desc}")

        lines.extend([
            "",
            "## Task",
            "Generate a clear, step-by-step implementation plan for this agent.",
            "Each step should specify:",
            "  1. The action type: `sop_invocation`, `skill_invocation`, or `tool_call`",
            "  2. A concise name for the step",
            "  3. A human-readable description of what the agent does in this step",
            "",
            "Respond ONLY with a valid JSON array. Each element must be an object with these exact keys:",
            '  {"order": <integer>, "type": "<sop_invocation|skill_invocation|tool_call>", "name": "<string>", "description": "<string or null>"}',
            "",
            "Do not include any text before or after the JSON array.",
        ])
        return "\n".join(lines)

    async def _invoke_llm(
        self, agent_type: AgentType, db: AsyncSession, prompt: str
    ) -> str:
        """Invoke the configured LLM with the plan generation prompt."""
        from app.services.agents.model_binding import ModelBindingLayer, ModelBindingError
        from app.db.models.agents import ModelConfig
        import time

        model_layer = ModelBindingLayer()
        model_config: ModelConfig | None = None

        # Try to resolve using the agent type's own model first
        if agent_type.model_id:
            try:
                model_config = await model_layer.resolve_model_config(agent_type.model_id, db)
            except ModelBindingError:
                logger.debug(
                    "Agent model '%s' not found; trying first available config",
                    agent_type.model_id,
                )

        # Fall back to the first available model config
        if model_config is None:
            result = await db.execute(select(ModelConfig).limit(1))
            model_config = result.scalar_one_or_none()

        if model_config is None:
            raise RuntimeError(
                "No ModelConfig available. Configure at least one LLM provider to enable plan generation."
            )

        messages = [
            {"role": "system", "content": "You generate structured JSON implementation plans for AI agents."},
            {"role": "user", "content": prompt},
        ]

        start = time.monotonic()
        response = await model_layer.complete(
            agent_type=agent_type,
            model_config=model_config,
            messages=messages,
            max_tokens=2048,
        )
        elapsed = time.monotonic() - start

        # Extract text from the response
        text = self._extract_text_from_response(response)
        logger.info(
            "LLM plan generation completed in %.2fs for agent_type=%s (model=%s)",
            elapsed,
            agent_type.id,
            agent_type.model_id,
        )
        return text

    def _extract_text_from_response(self, response: dict[str, Any]) -> str:
        """Extract text content from a provider-agnostic LLM response dict."""
        # OpenAI / LiteLLM / Azure format
        choices = response.get("choices")
        if choices and isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            content = message.get("content", "")
            if content:
                return content

        # Anthropic format
        content_blocks = response.get("content")
        if content_blocks and isinstance(content_blocks, list):
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text", "")

        return str(response)

    def _parse_plan_steps(self, raw_response: str) -> list[dict[str, Any]]:
        """Parse LLM response into a list of plan step dicts."""
        text = raw_response.strip()

        # Try to extract a JSON array from the response
        start_idx = text.find("[")
        end_idx = text.rfind("]")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = text[start_idx : end_idx + 1]
            try:
                steps = json.loads(json_str)
                if not isinstance(steps, list):
                    raise ValueError("Expected a JSON array")
                normalized: list[dict[str, Any]] = []
                for i, step in enumerate(steps):
                    if not isinstance(step, dict):
                        continue
                    normalized.append({
                        "order": int(step.get("order", i + 1)),
                        "type": str(step.get("type", "tool_call")),
                        "name": str(step.get("name", f"Step {i + 1}")),
                        "description": step.get("description") or None,
                    })
                return normalized
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("Failed to parse LLM plan JSON: %s — raw: %.200s", exc, text)

        # Fallback: single generic step
        logger.warning("Could not parse plan steps from LLM response; using fallback step")
        return [
            {
                "order": 1,
                "type": "tool_call",
                "name": "Execute Agent Task",
                "description": "Follow the configured system instruction using available skills and tools.",
            }
        ]

    async def _upsert_plan(
        self,
        agent_type_id: uuid.UUID,
        plan_steps: list[dict[str, Any]] | None,
        topology: dict[str, Any] | None,
        status: AgentPlanStatus,
        error: str | None,
        config_hash: str | None,
        db: AsyncSession,
    ) -> AgentPlan:
        """Insert or update the AgentPlan row for the given agent type."""
        result = await db.execute(
            select(AgentPlan).where(AgentPlan.agent_type_id == agent_type_id)
        )
        existing = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if existing:
            existing.plan_steps = plan_steps
            existing.topology = topology
            existing.generation_status = status
            existing.generation_error = error
            existing.agent_config_hash = config_hash
            existing.generated_at = now
            await db.flush()
            await db.refresh(existing)
            return existing
        else:
            plan = AgentPlan(
                agent_type_id=agent_type_id,
                plan_steps=plan_steps,
                topology=topology,
                generation_status=status,
                generation_error=error,
                agent_config_hash=config_hash,
                generated_at=now,
            )
            db.add(plan)
            await db.flush()
            await db.refresh(plan)
            return plan

    @staticmethod
    def _compute_config_hash(agent_type: AgentType) -> str:
        """Compute a deterministic hash of the agent configuration inputs."""
        parts = [
            str(agent_type.role_id or ""),
            str(agent_type.primary_sop_id or ""),
            str(agent_type.system_instruction or ""),
        ]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()
