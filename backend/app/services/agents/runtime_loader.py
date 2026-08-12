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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.agent_runtime.data_client import ControlCenterDataClient

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

    async def load_plan_for_agent_type_via_client(
        self,
        agent_type_id: uuid.UUID,
        data_client: "ControlCenterDataClient",
    ) -> dict[str, Any] | None:
        """Fetch the successful plan via Control Center data API.

        Returns a plan dict (plan_steps, topology, generation_status, generated_at)
        or None if no successful plan exists.
        """
        plan = await data_client.get_agent_plan(agent_type_id)
        if plan:
            logger.info(
                "Loaded saved plan for agent_type=%s via CC (%d steps)",
                agent_type_id,
                len(plan.get("plan_steps") or []),
            )
        else:
            logger.debug(
                "No successful plan found for agent_type=%s — running without plan guidance",
                agent_type_id,
            )
        return plan

    def format_plan_for_injection(self, plan: Any) -> str:
        """
        Format the plan steps as a human-readable text block for injection into
        the agent's system instruction.

        Accepts either an AgentPlan ORM object or a plain dict returned by the
        Control Center data API.

        Returns an empty string if plan_steps is empty or None.
        """
        if isinstance(plan, dict):
            steps: list[dict[str, Any]] = plan.get("plan_steps") or []
        else:
            steps = plan.plan_steps or []
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

    async def inject_plan_into_system_instruction_via_client(
        self,
        agent_type_id: uuid.UUID,
        system_instruction: str | None,
        data_client: "ControlCenterDataClient",
    ) -> tuple[str | None, bool]:
        """Load the saved plan and append it to the system instruction.

        Uses Control Center data API instead of direct DB access.

        Args:
            agent_type_id: The UUID of the agent type being executed.
            system_instruction: The current system instruction string (may be None).
            data_client: ControlCenterDataClient for fetching plan data.

        Returns:
            Tuple of (updated_system_instruction, plan_was_injected).
            If no plan is found, returns the original system_instruction and False.
        """
        plan = await self.load_plan_for_agent_type_via_client(agent_type_id, data_client)
        if not plan:
            return system_instruction, False

        plan_text = self.format_plan_for_injection(plan)
        if not plan_text.strip():
            return system_instruction, False

        base = system_instruction or ""
        updated = f"{base}{plan_text}".strip()
        logger.info(
            "Injected plan (%d steps) into system instruction for agent_type=%s",
            len(plan.get("plan_steps") or []) if isinstance(plan, dict) else 0,
            agent_type_id,
        )
        return updated, True
