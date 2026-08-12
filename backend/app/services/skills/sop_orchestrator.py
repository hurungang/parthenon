"""SOP Orchestrator — executes ordered SOP steps invoking SkillExecutor or agent delegation."""
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.skills import Sop, SopStep, SopStepType
from app.services.skills.executor import SkillExecutor

logger = logging.getLogger(__name__)


class SopOrchestratorError(Exception):
    """Raised when SOP orchestration fails."""


class SopOrchestrator:
    """
    Executes an ordered sequence of SOP steps.
    Delegates skill steps to SkillExecutor and agent-delegation steps to the Agent Engine.
    """

    def __init__(self, skill_executor: SkillExecutor | None = None) -> None:
        self._skill_executor = skill_executor or SkillExecutor()

    async def execute(
        self,
        sop_id: Any,
        prompt: str,
        context: dict[str, Any] | None,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        Execute a SOP by iterating its steps in order.

        Args:
            sop_id: UUID of the SOP to execute.
            prompt: Initial user prompt.
            context: Optional execution context passed to each step.
            db: Database session.

        Returns:
            Combined output dict with step results.
        """
        # Load SOP with steps
        result = await db.execute(
            select(Sop)
            .where(Sop.id == sop_id)
            .options(selectinload(Sop.steps))
        )
        sop = result.scalar_one_or_none()
        if not sop:
            raise SopOrchestratorError(f"SOP {sop_id} not found")

        if not sop.steps:
            logger.warning("SOP '%s' has no steps", sop.name)
            return {"sop_id": str(sop_id), "results": [], "prompt": prompt}

        steps = sorted(sop.steps, key=lambda s: s.order)
        step_results: list[dict[str, Any]] = []
        accumulated_context = dict(context or {})
        accumulated_context["prompt"] = prompt

        for step in steps:
            step_result = await self._execute_step(step, accumulated_context, db)
            step_results.append(
                {
                    "step_id": str(step.id),
                    "step_type": step.step_type,
                    "order": step.order,
                    "name": step.name,
                    "result": step_result,
                }
            )
            # Propagate previous step output as context for next step
            accumulated_context[f"step_{step.order}_result"] = step_result

        return {
            "sop_id": str(sop_id),
            "sop_name": sop.name,
            "prompt": prompt,
            "results": step_results,
        }

    async def _execute_step(
        self,
        step: SopStep,
        context: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Execute a single SOP step.
        
        Handles:
        - skill_invocation: Delegates to SkillExecutor.
        - agent_delegation: Sends A2A request to Communication Hub.
        """
        if step.step_type == SopStepType.skill_invocation:
            if not step.skill_id:
                raise SopOrchestratorError(
                    f"Step {step.id} is type 'skill_invocation' but has no skill_id"
                )
            logger.info(
                "Executing skill step (order=%d, skill_id=%s)", step.order, step.skill_id
            )
            tool_results = await self._skill_executor.execute(
                skill_id=step.skill_id,
                tool_input=context,
                db=db,
            )
            return {"type": "skill", "tool_results": tool_results}

        elif step.step_type == SopStepType.agent_delegation:
            if not step.target_agent_type_id:
                raise SopOrchestratorError(
                    f"Step {step.id} is type 'agent_delegation' but has no target_agent_type_id"
                )
            
            # Phase 1.2: Call Communication Hub A2A endpoint to handle delegation.
            # Get the target agent type name (slug) from the database.
            from sqlalchemy import select
            from app.db.models.agents import AgentType
            
            result = await db.execute(
                select(AgentType).where(AgentType.id == step.target_agent_type_id)
            )
            target_agent_type = result.scalar_one_or_none()
            if not target_agent_type:
                raise SopOrchestratorError(
                    f"Step {step.id} target agent type {step.target_agent_type_id} not found"
                )
            
            logger.info(
                "Delegating to agent type '%s' (step order=%d)",
                target_agent_type.name,
                step.order,
            )
            
            # Call Communication Hub A2A endpoint (Phase 1.1)
            import os
            import httpx
            from app.schemas.agents import A2ARequest, A2AResponse
            
            comm_hub_url = os.environ.get("COMM_HUB_URL", "http://localhost:8002")
            a2a_url = f"{comm_hub_url}/internal/a2a/request"
            
            a2a_request = A2ARequest(
                target_agent_type_slug=target_agent_type.name,
                conversation_metadata=context,
                request_payload=step.step_config or {},
            )
            
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        a2a_url,
                        json=a2a_request.model_dump(),
                        timeout=30.0,
                    )
                    response.raise_for_status()
                    a2a_response_data = response.json()
                    
                    return {
                        "type": "agent_delegation",
                        "target_agent_type_id": str(step.target_agent_type_id),
                        "target_agent_type_slug": target_agent_type.name,
                        "receiver_instance_id": a2a_response_data.get("receiver_instance_id"),
                        "session_link_id": a2a_response_data.get("session_link_id"),
                        "status": a2a_response_data.get("status"),
                    }
            except httpx.HTTPError as exc:
                logger.exception(
                    "A2A delegation failed to %s: %s", target_agent_type.name, exc
                )
                raise SopOrchestratorError(
                    f"A2A delegation to '{target_agent_type.name}' failed: {exc}"
                ) from exc

        else:
            raise SopOrchestratorError(f"Unknown step type: {step.step_type}")
