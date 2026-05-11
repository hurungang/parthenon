"""AgentRuntimeLoader — loads the saved plan for an agent type and injects it into system context.

When an agent session is initialized, the runtime loader queries the agent_plans table
for a successful plan associated with the agent type. If found, the plan steps are
formatted as a structured text block and appended to the agent's system instruction,
instructing the LLM to follow the pre-approved implementation plan during execution.

If no plan exists or generation_status != success, the agent runs without plan guidance
(graceful degradation).
"""
import json
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentPlan, AgentPlanStatus

logger = logging.getLogger(__name__)

# Header injected before the plan steps in the system instruction
_PLAN_HEADER = (
    "\n\n---\n"
    "## Pre-Approved Implementation Plan\n\n"
    "You MUST follow this pre-approved implementation plan during execution. "
    "The plan outlines the steps, SOPs, skills, and tools you should use. "
    "Do not deviate from this plan unless the user explicitly requests otherwise.\n\n"
)
_PLAN_FOOTER = "\n---\n"


class AgentRuntimeLoader:
    """
    Loads the saved plan from the agent_plans table when initializing an agent session
    and injects the plan into the agent's system context.
    """

    async def load_plan_for_agent_type(
        self, agent_type_id: uuid.UUID, db: AsyncSession
    ) -> AgentPlan | None:
        """
        Fetch the successful plan for the given agent type.

        Returns None if no plan exists or the plan has a failed/pending status.
        """
        result = await db.execute(
            select(AgentPlan).where(
                AgentPlan.agent_type_id == agent_type_id,
                AgentPlan.generation_status == AgentPlanStatus.success,
            )
        )
        plan = result.scalar_one_or_none()
        if plan:
            logger.info(
                "Loaded saved plan for agent_type=%s (%d steps)",
                agent_type_id,
                len(plan.plan_steps or []),
            )
        else:
            logger.debug(
                "No successful plan found for agent_type=%s — running without plan guidance",
                agent_type_id,
            )
        return plan

    def format_plan_for_injection(self, plan: AgentPlan) -> str:
        """
        Format the plan steps as a human-readable text block for injection into
        the agent's system instruction.

        Returns an empty string if plan_steps is empty or None.
        """
        steps: list[dict[str, Any]] = plan.plan_steps or []
        if not steps:
            return ""

        lines: list[str] = [_PLAN_HEADER]
        for step in sorted(steps, key=lambda s: s.get("order", 0)):
            order = step.get("order", "?")
            step_type = step.get("type", "")
            name = step.get("name", "")
            description = step.get("description") or ""
            lines.append(f"**Step {order}** [{step_type}] — {name}")
            if description:
                lines.append(f"  {description}")
            lines.append("")
        lines.append(_PLAN_FOOTER)
        return "\n".join(lines)

    async def inject_plan_into_system_instruction(
        self,
        agent_type_id: uuid.UUID,
        system_instruction: str | None,
        db: AsyncSession,
    ) -> tuple[str | None, bool]:
        """
        Load the saved plan and append it to the system instruction if found.

        Args:
            agent_type_id: The UUID of the agent type being executed.
            system_instruction: The current system instruction string (may be None).
            db: Active async database session.

        Returns:
            Tuple of (updated_system_instruction, plan_was_injected).
            If no plan is found, returns the original system_instruction and False.
        """
        plan = await self.load_plan_for_agent_type(agent_type_id, db)
        if not plan:
            return system_instruction, False

        plan_text = self.format_plan_for_injection(plan)
        if not plan_text.strip():
            return system_instruction, False

        base = system_instruction or ""
        updated = f"{base}{plan_text}".strip()
        logger.info(
            "Injected plan (%d steps) into system instruction for agent_type=%s",
            len(plan.plan_steps or []),
            agent_type_id,
        )
        return updated, True
