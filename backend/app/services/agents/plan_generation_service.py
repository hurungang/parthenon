"""PlanGenerationService — explicit-request LLM plan authoring.

Traverses the role→SOP→Skill→Tool graph, constructs a detailed prompt with
agent context, invokes the workspace AUTHORING model, parses the response into
structured plan steps, calls TopologyBuilderService for the topology payload,
and upserts the AgentPlan row.

Authoring model policy: implementation plans are authored by the workspace's
single tenant-level authoring model (``TenantSetting.workflow_generation_model_id``)
— never ``AgentType.model_id`` (the agent RUNTIME model) and never a
first-available ``ModelConfig``. An unset/disabled authoring model raises
``AuthoringModelNotConfigured`` (mapped to a structured 412 by the API) and
writes nothing.

Generation is EXPLICIT ONLY: the API endpoint ``POST /agents/types/{id}/regenerate-plan``
is the single caller that authors a plan — agent create/update never schedules
generation. A failed attempt preserves the last successful plan.
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
from sqlalchemy.orm import selectinload

from app.db.models.agents import AgentPlan, AgentPlanStatus, AgentType
from app.services.agents.tool_naming import build_tool_name, parse_tool_name
from app.services.agents.topology_builder_service import TopologyBuilderService
from app.services.agents.workflow_generation_settings import (
    AuthoringModelNotConfigured,
    require_authoring_model,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

_topology_builder = TopologyBuilderService()


def _canonicalize_mcp_tool_name(name: str, server_slug: str | None, original_name: str | None) -> str:
    """Return canonical ``server____tool`` for MCP tool identifiers."""
    if server_slug and isinstance(original_name, str) and original_name:
        return build_tool_name(server_slug, original_name)

    try:
        parsed_server, parsed_tool = parse_tool_name(name)
        return build_tool_name(parsed_server, parsed_tool)
    except ValueError:
        if "/" in name:
            parsed_server, parsed_tool = name.split("/", 1)
            return build_tool_name(parsed_server, parsed_tool)
        return name


class PlanGenerationService:
    """
    Orchestrates LLM-based plan authoring on an EXPLICIT user request.

    Call generate_plan(agent_type, db) from ``POST /agents/types/{id}/regenerate-plan``
    only. The method is non-blocking for model failures (a failed AgentPlan
    generation_status/error is written and the last successful plan is kept),
    but ``AuthoringModelNotConfigured`` propagates so the API can return the
    structured "not configured / re-select" 412 without writing anything.
    """

    async def generate_plan(
        self,
        agent_type: AgentType,
        db: AsyncSession,
        *,
        user_requirement: str | None = None,
    ) -> AgentPlan:
        """
        Generate a plan for the given agent type and upsert the AgentPlan row.

        Args:
            agent_type: The saved AgentType ORM instance.
            db: Active async SQLAlchemy session.
            user_requirement: Optional verbatim user requirement / session
                input for this run. When provided it is included in the plan
                prompt so the authored composition serves it exactly.

        Returns:
            The upserted AgentPlan row (success or failed status).

        Raises:
            AuthoringModelNotConfigured: the workspace authoring model is unset
                or no longer enabled. Nothing is written.
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
                plan_steps, topology, fully_scripted = await self._do_generate(
                    agent_type, db, user_requirement=user_requirement
                )
                plan = await self._upsert_plan(
                    agent_type_id=agent_type.id,
                    plan_steps=plan_steps,
                    topology=topology,
                    status=AgentPlanStatus.success,
                    error=None,
                    config_hash=config_hash,
                    db=db,
                    fully_scripted=fully_scripted,
                )
                span.set_attribute("status", "success")
                span.set_attribute("step_count", len(plan_steps))
                logger.info(
                    "Plan generation succeeded for agent_type=%s: %d steps",
                    agent_type.id,
                    len(plan_steps),
                )
                return plan

            except AuthoringModelNotConfigured as exc:
                # No authoring model → nothing is authored and NOTHING is
                # written (no plan row is created, no existing plan touched).
                span.set_attribute("status", "authoring_model_unavailable")
                span.set_attribute("reason_code", exc.reason_code)
                logger.warning(
                    "Plan generation unavailable for agent_type=%s (%s): %s",
                    agent_type.id,
                    exc.reason_code,
                    exc.message,
                )
                raise

            except Exception as exc:
                error_msg = str(exc)[:990]
                logger.warning(
                    "Plan generation failed for agent_type=%s (previous plan kept): %s",
                    agent_type.id,
                    error_msg,
                )
                span.set_attribute("status", "failed")
                span.set_attribute("error", error_msg)
                return await self._mark_failed(
                    agent_type_id=agent_type.id,
                    error=error_msg,
                    config_hash=config_hash,
                    db=db,
                )

    # ── Internal orchestration ────────────────────────────────────────────────

    async def _do_generate(
        self,
        agent_type: AgentType,
        db: AsyncSession,
        *,
        user_requirement: str | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        """Core generation logic — raises on failure (caller handles non-blocking).
        Returns ``(plan_steps, topology, fully_scripted)``."""
        # Step 1: Resolve the role→SOP→Skill→Tool graph
        graph = await self._resolve_graph(agent_type, db)

        # Step 2: Construct prompt
        prompt = self._build_prompt(agent_type, graph, user_requirement)

        # Step 3: Invoke LLM
        raw_response = await self._invoke_llm(agent_type, db, prompt)

        # Step 4: Parse plan steps (and the fully_scripted execution-semantics mark)
        plan_steps = self._parse_plan_steps(raw_response)
        # Hard rule: a typed step must reference an entity the agent actually
        # has (SOP/skill/tool/delegated agent); everything else is processing.
        plan_steps = self._enforce_step_types(plan_steps, graph)
        fully_scripted = self._parse_fully_scripted(raw_response)

        # Step 5: Build topology
        topology = _topology_builder.build_topology(graph)

        return plan_steps, topology, fully_scripted

    async def _resolve_graph(
        self, agent_type: AgentType, db: AsyncSession
    ) -> dict[str, Any]:
        """Traverse role→SOP→Skill→Tool graph and return a structured dict."""
        from app.db.models.agents import AgentIdentity, AgentRole, AgentRoleSOP, AgentRoleSkill, AgentRoleMcpSession
        from app.db.models.skills import Skill, SkillToolBinding, Sop, SopStep, SopStepType
        from app.db.models.mcp_hub import McpTool, McpServer, McpSession

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

        # Load MCP sessions assigned to this role: build server_id → session info map
        session_rows = await db.execute(
            select(AgentRoleMcpSession, McpSession)
            .join(McpSession, AgentRoleMcpSession.mcp_session_id == McpSession.id)
            .where(AgentRoleMcpSession.role_id == role.id)
        )
        server_session_map: dict[str, dict[str, str]] = {}
        for assoc, session in session_rows.all():
            server_session_map[str(assoc.server_id)] = {
                "session_name": session.name,
                "auth_type": session.auth_type.value,
            }

        # Load SOPs assigned to role
        sop_rows = await db.execute(
            select(AgentRoleSOP.sop_id).where(AgentRoleSOP.role_id == role.id)
        )
        sop_ids = [row[0] for row in sop_rows.fetchall()]

        sop_data_list: list[dict[str, Any]] = []
        sop_skill_ids: dict[str, list[str]] = {}
        delegated_agent_type_ids: set[str] = set()

        if sop_ids:
            sops_result = await db.execute(
                select(Sop)
                .where(Sop.id.in_(sop_ids))
                .options(selectinload(Sop.steps))
            )
            for sop in sops_result.scalars().all():
                sop_steps = sorted(sop.steps, key=lambda s: s.order)
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
                            "target_agent_type_id": str(step.target_agent_type_id) if step.target_agent_type_id else None,
                        }
                        for step in sop_steps
                    ],
                })
                # Collect skill IDs and delegated agent IDs from SOP steps
                for step in sop_steps:
                    if step.step_type == SopStepType.skill_invocation and step.skill_id:
                        sop_skill_ids.setdefault(str(sop.id), []).append(str(step.skill_id))
                    if step.step_type == SopStepType.agent_delegation and step.target_agent_type_id:
                        delegated_agent_type_ids.add(str(step.target_agent_type_id))

        # Filter sop_data_list based on bindings and system instruction references
        sop_scope_narrowed = False
        if sop_data_list:
            system_instruction_lower = (agent_type.system_instruction or "").lower()
            mentioned = [
                sop for sop in sop_data_list
                if sop["name"].lower() in system_instruction_lower
            ]
            if mentioned:
                sop_data_list = mentioned
                sop_scope_narrowed = True
            else:
                # No SOPs named in system instruction — use bound SOPs if bindings exist
                bound_sop_ids = await self._get_bound_sop_ids(agent_type, db)
                if bound_sop_ids:
                    sop_data_list = [
                        sop for sop in sop_data_list
                        if sop["id"] in bound_sop_ids
                    ]
                    sop_scope_narrowed = True
                # else: no bindings either → keep all role SOPs (fallback)

        # Prune sop_skill_ids and delegated_agent_type_ids to only include SOPs that survived filtering
        filtered_sop_ids = {sop["id"] for sop in sop_data_list}
        sop_skill_ids = {
            sid: ids for sid, ids in sop_skill_ids.items()
            if sid in filtered_sop_ids
        }
        delegated_agent_type_ids = {
            step["target_agent_type_id"]
            for sop in sop_data_list
            for step in sop.get("steps", [])
            if step.get("step_type") == "agent_delegation" and step.get("target_agent_type_id")
        }

        delegated_agents: list[dict[str, Any]] = []
        if delegated_agent_type_ids:
            delegated_rows = await db.execute(
                select(AgentType)
                .where(AgentType.id.in_([uuid.UUID(agent_id) for agent_id in delegated_agent_type_ids]))
            )
            delegated_by_id = {str(agent.id): agent for agent in delegated_rows.scalars().all()}
            for agent_id in sorted(delegated_agent_type_ids):
                delegated = delegated_by_id.get(agent_id)
                delegated_agents.append(
                    {
                        "id": agent_id,
                        "name": delegated.name if delegated else agent_id,
                    }
                )

        # Collect all skill IDs: from SOP steps + directly assigned
        direct_skill_rows = await db.execute(
            select(AgentRoleSkill.skill_id).where(AgentRoleSkill.role_id == role.id)
        )
        direct_skill_ids = {str(row[0]) for row in direct_skill_rows.fetchall()}

        sop_step_skill_ids: set[str] = set()
        for ids in sop_skill_ids.values():
            sop_step_skill_ids.update(ids)

        # When SOP scope is narrowed (bindings or system instruction), only use skills
        # from those SOPs — don't pull in unrelated role-assigned skills
        if sop_scope_narrowed:
            all_skill_ids_str = sop_step_skill_ids
        else:
            all_skill_ids_str = direct_skill_ids | sop_step_skill_ids
        all_skill_ids = [uuid.UUID(sid) for sid in all_skill_ids_str]

        skill_data_list: list[dict[str, Any]] = []
        tool_data_list: list[dict[str, Any]] = []

        if all_skill_ids:
            skills_result = await db.execute(
                select(Skill)
                .where(Skill.id.in_(all_skill_ids))
                .options(
                    selectinload(Skill.tool_bindings).selectinload(SkillToolBinding.tool).selectinload(McpTool.server)
                )
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
                        canonical_tool_name = _canonicalize_mcp_tool_name(
                            binding.tool.name,
                            binding.tool.server.slug if binding.tool.server is not None else None,
                            binding.tool.original_name,
                        )
                        tool_data: dict[str, Any] = {
                            "name": canonical_tool_name,
                            "description": binding.tool.description,
                            "skill_id": str(skill.id),
                            "server_id": str(binding.tool.server_id),
                        }
                        # Attach session info if this server has a role-assigned session
                        srv_key = str(binding.tool.server_id)
                        if srv_key in server_session_map:
                            tool_data["session_name"] = server_session_map[srv_key]["session_name"]
                            tool_data["auth_type"] = server_session_map[srv_key]["auth_type"]
                        tool_data_list.append(tool_data)

        # Filter skill_data_list based on bindings
        bound_skill_ids = await self._get_bound_skill_ids(agent_type, db)
        if bound_skill_ids:
            skill_data_list = [
                skill for skill in skill_data_list
                if skill["id"] in bound_skill_ids
            ]
            # Also prune tools to only those owned by surviving skills
            surviving_skill_ids = {s["id"] for s in skill_data_list}
            tool_data_list = [
                t for t in tool_data_list
                if t["skill_id"] in surviving_skill_ids
            ]

        return {
            "agent": agent_data,
            "identity": identity_data,
            "role": role_data,
            "sops": sop_data_list,
            "skills": skill_data_list,
            "tools": tool_data_list,
            "delegated_agents": delegated_agents,
        }

    async def _get_bound_sop_ids(
        self, agent_type: AgentType, db: AsyncSession
    ) -> set[str]:
        """Return the set of SOP IDs that are bound to this agent type."""
        from app.db.models.agents import AgentTypeSopBinding

        result = await db.execute(
            select(AgentTypeSopBinding.sop_id).where(
                AgentTypeSopBinding.agent_type_id == agent_type.id
            )
        )
        return {str(row[0]) for row in result.fetchall()}

    async def _get_bound_skill_ids(
        self, agent_type: AgentType, db: AsyncSession
    ) -> set[str]:
        """Return the set of Skill IDs that are bound to this agent type."""
        from app.db.models.agents import AgentTypeSkillBinding

        result = await db.execute(
            select(AgentTypeSkillBinding.skill_id).where(
                AgentTypeSkillBinding.agent_type_id == agent_type.id
            )
        )
        return {str(row[0]) for row in result.fetchall()}

    def _build_prompt(
        self,
        agent_type: AgentType,
        graph: dict[str, Any],
        user_requirement: str | None = None,
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

        if user_requirement:
            lines.extend([
                "",
                "## User Requirement (context only)",
                "```",
                user_requirement.strip(),
                "```",
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
            "  1. The action type (see the hard rule below): `sop_invocation`, `skill_invocation`, `agent_delegation`, `tool_call`, or `processing`",
            "  2. A concise name for the step",
            "  3. A human-readable description of what the agent does in this step",
            "  4. When a step is a sub-step of another, set its optional `parent_order` to the parent step's `order`; omit it for top-level steps.",
            "",
            "HARD RULE for the action type:",
            "  - `sop_invocation` ONLY when the step invokes one of the SOPs listed above; name it explicitly.",
            "  - `skill_invocation` ONLY when the step invokes one of the skills listed above; name it explicitly.",
            "  - `tool_call` ONLY when the step invokes one of the MCP tools listed above; name the tool explicitly (use its exact name).",
            "  - `agent_delegation` ONLY when the step hands work to one of the delegated agents listed above.",
            "  - `processing` for everything else: validation, selection, calculation, formatting, decisions and output assembly.",
            "Do not label validation/formatting/selection steps as skill or SOP invocations.",
            "",
            "Respond ONLY with a valid JSON array. Each element must be an object with these exact keys:",
            '  {"order": <integer>, "parent_order": <integer or null>, "type": "<sop_invocation|skill_invocation|agent_delegation|tool_call|processing>", "name": "<string>", "description": "<string or null>"}',
            "",
            "Do not include any text before or after the JSON array.",
        ])
        return "\n".join(lines)

    async def _invoke_llm(
        self, agent_type: AgentType, db: AsyncSession, prompt: str
    ) -> str:
        """Author ``prompt`` with the workspace AUTHORING model.

        Resolution is delegated to ``require_authoring_model`` (tenant-scoped,
        no fallback). ``agent_type`` is NOT used to pick the model — its
        ``model_id`` is the agent RUNTIME model, never an authoring model.

        The ORM ``ModelBindingLayer.complete()`` cannot be used here because it
        derives the model name from ``AgentType.model_id``; instead the resolved
        tenant ``ModelConfig`` is turned into the context dict and dispatched
        through ``complete_from_context``.
        """
        from app.services.agents.model_binding import ModelBindingLayer
        import time

        authoring = await require_authoring_model(db)
        model_layer = ModelBindingLayer()
        provider_type = authoring.model_config.provider_type
        model_config_dict = model_layer.build_completion_context(authoring.model_config)

        messages = [
            {"role": "system", "content": "You generate structured JSON implementation plans for AI agents."},
            {"role": "user", "content": prompt},
        ]

        start = time.monotonic()
        # Bound the call so a slow provider fails fast instead of hanging the
        # regenerate request indefinitely (frontend uses the matching 180s
        # client timeout).
        import asyncio
        try:
            response = await asyncio.wait_for(
                model_layer.complete_from_context(
                    model_id=authoring.model_id,
                    model_config_dict=model_config_dict,
                    messages=messages,
                    max_tokens=8192,
                ),
                timeout=180.0,
            )
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                "Plan generation timed out after 180s — the model did not "
                "respond. Check the model provider connectivity."
            ) from exc
        elapsed = time.monotonic() - start

        # Extract text from the response (provider-specific envelope)
        text = ModelBindingLayer.extract_text(response, provider_type)
        if not text:
            text = str(response)
        logger.info(
            "LLM plan generation completed in %.2fs for agent_type=%s (authoring model=%s)",
            elapsed,
            agent_type.id,
            authoring.model_id,
        )
        return text

    def _extract_text_from_response(self, response: Any) -> str:
        """Extract text content from a LangChain AIMessage via ModelBindingLayer."""
        from app.services.agents.model_binding import ModelBindingLayer
        # Provider is not needed — AIMessage path in extract_text is provider-agnostic.
        # Pass a placeholder so the signature is satisfied; the AIMessage branch
        # always fires first and returns before any provider branching.
        text = ModelBindingLayer.extract_text(response, "openai")
        return text if text else str(response)

    def _parse_plan_steps(self, raw_response: str) -> list[dict[str, Any]]:
        """Parse LLM response into a list of plan step dicts."""
        text = raw_response.strip()

        # Try to extract a JSON array from the response. The plan LLM may
        # also emit an object ``{"fully_scripted": <bool>, "steps": [...]}``
        # (execution-semantics decision) — accept both shapes.
        start_idx = text.find("[")
        obj_start_idx = text.find("{")
        if obj_start_idx != -1 and (start_idx == -1 or obj_start_idx < start_idx):
            try:
                obj_end_idx = text.rfind("}")
                candidate = json.loads(text[obj_start_idx : obj_end_idx + 1])
                if isinstance(candidate, dict) and isinstance(
                    candidate.get("steps"), list
                ):
                    text = json.dumps(candidate["steps"])
            except json.JSONDecodeError:
                pass
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
                    parent_order = step.get("parent_order")
                    normalized.append({
                        "order": int(step.get("order", i + 1)),
                        # Optional step-tree link: a child step points at its
                        # parent's order. Malformed values are dropped, not
                        # fatal — the flat order remains the source of truth.
                        "parent_order": (
                            int(parent_order)
                            if parent_order is not None
                            and str(parent_order).lstrip("-").isdigit()
                            else None
                        ),
                        "type": str(step.get("type", "tool_call")),
                        "name": str(step.get("name", f"Step {i + 1}")),
                        "description": step.get("description") or None,
                        # Optional explicit entity reference — used by the
                        # step-type hard rule when the plan LLM provides it.
                        "sop_id": step.get("sop_id") or None,
                        "skill_id": step.get("skill_id") or None,
                        "tool_name": step.get("tool_name") or None,
                        "target_agent_type_id": step.get("target_agent_type_id") or None,
                        # Scriptability marks (Software 3.0): preserved when
                        # the plan LLM provides them, defaulted otherwise.
                        "scriptable": bool(step.get("scriptable", True)),
                        # Model-authored composition emission (Phase 2.1):
                        # sandboxed Python source per scriptable segment.
                        "python_source": step.get("python_source") or None,
                        "output_mode": step.get("output_mode") or None,
                        "output_template": step.get("output_template") or None,
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

    #: Step types that claim a concrete, existing entity.
    _ENTITY_STEP_TYPES = (
        "sop_invocation",
        "skill_invocation",
        "tool_call",
        "agent_delegation",
    )

    @staticmethod
    def _entity_terms(
        items: list[dict[str, Any]],
        keys: tuple[str, ...],
    ) -> set[str]:
        """Lower-cased names/ids of available entities, incl. bare tool names."""
        terms: set[str] = set()
        for item in items:
            for key in keys:
                value = item.get(key)
                if value:
                    terms.add(str(value).strip().lower())
            name = item.get("name")
            if name and "____" in str(name):
                # ``server____searchFlights`` may be referenced by its bare name.
                terms.add(str(name).split("____", 1)[1].strip().lower())
        return {term for term in terms if term}

    def _enforce_step_types(
        self,
        steps: list[dict[str, Any]],
        graph: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Apply the plan step-type hard rule.

        ``sop_invocation`` / ``skill_invocation`` / ``tool_call`` /
        ``agent_delegation`` are only valid when the step references an entity
        the agent actually has (explicit id/name field or the entity name in the
        step text). All other steps become ``processing`` — validation,
        selection, formatting, decisions and output assembly are not
        invocations.
        """
        allowed: dict[str, set[str]] = {
            "sop_invocation": self._entity_terms(
                list(graph.get("sops") or []), ("id", "name")
            ),
            "skill_invocation": self._entity_terms(
                list(graph.get("skills") or []), ("id", "name")
            ),
            "tool_call": self._entity_terms(
                list(graph.get("tools") or []), ("name",)
            ),
            "agent_delegation": self._entity_terms(
                list(graph.get("delegated_agents") or []), ("id", "name")
            ),
        }
        ref_keys = {
            "sop_invocation": ("sop_id",),
            "skill_invocation": ("skill_id",),
            "tool_call": ("tool_name",),
            "agent_delegation": ("target_agent_type_id",),
        }

        for step in steps:
            step_type = str(step.get("type") or "processing").strip().lower()
            if step_type not in self._ENTITY_STEP_TYPES:
                step["type"] = "processing"
                continue

            terms = allowed[step_type]
            explicit_refs = [
                str(step.get(key)).strip().lower()
                for key in ref_keys[step_type]
                if step.get(key)
            ]
            if explicit_refs:
                # An explicit reference is authoritative: keep the type only
                # when it points at an allowed entity.
                if not any(ref in terms for ref in explicit_refs):
                    step["type"] = "processing"
                continue

            text = f"{step.get('name') or ''} {step.get('description') or ''}".lower()
            if not any(term in text for term in terms):
                step["type"] = "processing"

        return steps

    def _parse_fully_scripted(self, raw_response: str) -> bool:
        """Extract the plan LLM's ``fully_scripted`` execution-semantics mark.

        True only when the response carries an explicit
        ``{"fully_scripted": true, ...}`` object — i.e. no/typed input AND a
        SINGLE script can achieve the requirement end-to-end. Anything else
        (array-only responses, missing mark) defaults to tool-mode.
        """
        text = raw_response.strip()
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx == -1 or end_idx <= start_idx:
            return False
        try:
            candidate = json.loads(text[start_idx : end_idx + 1])
        except json.JSONDecodeError:
            return False
        if isinstance(candidate, dict):
            return candidate.get("fully_scripted") is True
        return False

    async def _upsert_plan(
        self,
        agent_type_id: uuid.UUID,
        plan_steps: list[dict[str, Any]] | None,
        topology: dict[str, Any] | None,
        status: AgentPlanStatus,
        error: str | None,
        config_hash: str | None,
        db: AsyncSession,
        fully_scripted: bool | None = None,
        preserve_plan_on_failure: bool = False,
    ) -> AgentPlan:
        """Insert or update the AgentPlan row for the given agent type.

        ``preserve_plan_on_failure`` is set by ``_mark_failed``: on a FAILED
        attempt an existing row keeps its ``plan_steps``, ``topology``,
        ``agent_config_hash``, ``fully_scripted`` and ``generated_at`` (the last
        successful authoring) and only the status/error are updated, so the
        plan stays readable while the UI surfaces the failure reason.
        """
        result = await db.execute(
            select(AgentPlan).where(AgentPlan.agent_type_id == agent_type_id)
        )
        existing = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if existing:
            keep_previous_plan = (
                preserve_plan_on_failure and status == AgentPlanStatus.failed
            )
            if not keep_previous_plan:
                existing.plan_steps = plan_steps
                existing.topology = topology
                existing.agent_config_hash = config_hash
                existing.generated_at = now
                if fully_scripted is not None or status == AgentPlanStatus.success:
                    existing.fully_scripted = fully_scripted
            existing.generation_status = status
            existing.generation_error = error
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
                fully_scripted=fully_scripted,
            )
            db.add(plan)
            await db.flush()
            await db.refresh(plan)
            return plan

    async def _mark_failed(
        self,
        *,
        agent_type_id: uuid.UUID,
        error: str | None,
        config_hash: str | None,
        db: AsyncSession,
    ) -> AgentPlan:
        """Record a failed attempt WITHOUT discarding the last successful plan.

        Delegates to ``_upsert_plan(..., preserve_plan_on_failure=True)``: an
        existing row only gets ``generation_status``/``generation_error``
        updated — ``plan_steps``, ``topology``, ``agent_config_hash``,
        ``fully_scripted`` and ``generated_at`` of the last successful
        authoring are preserved so the plan stays readable while the UI
        surfaces the failure reason.  When no row exists yet (the very first
        attempt failed), a failed row is inserted so the reason is visible;
        nothing is overwritten.
        """
        return await self._upsert_plan(
            agent_type_id=agent_type_id,
            plan_steps=None,
            topology=None,
            status=AgentPlanStatus.failed,
            error=error,
            config_hash=config_hash,
            db=db,
            fully_scripted=None,
            preserve_plan_on_failure=True,
        )

    @staticmethod
    def _compute_config_hash(agent_type: AgentType) -> str:
        """Compute a deterministic hash of the agent configuration inputs."""
        from sqlalchemy.orm import attributes

        state = attributes.instance_state(agent_type)

        sop_binding_ids: list[str] = []
        if "sop_bindings" not in state.unloaded:
            sop_binding_ids = sorted(
                str(b.sop_id) for b in agent_type.sop_bindings  # type: ignore[union-attr]
            )

        skill_binding_ids: list[str] = []
        if "skill_bindings" not in state.unloaded:
            skill_binding_ids = sorted(
                str(b.skill_id) for b in agent_type.skill_bindings  # type: ignore[union-attr]
            )
        parts = [
            str(agent_type.role_id or ""),
            "|".join(sop_binding_ids),
            "|".join(skill_binding_ids),
            str(agent_type.system_instruction or ""),
        ]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()
