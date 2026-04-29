"""SOP Agent Executor — handles sop-agent prompt execution via SopOrchestrator."""
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentInstance, AgentMode
from app.services.skills.sop_orchestrator import SopOrchestrator

logger = logging.getLogger(__name__)


class SopAgentError(Exception):
    """Raised when a SOP agent execution fails."""


class SopAgentExecutor:
    """
    Executes a user prompt for a sop-agent instance by loading
    the bound SOP and delegating to SopOrchestrator.
    """

    def __init__(self, orchestrator: SopOrchestrator | None = None) -> None:
        self._orchestrator = orchestrator or SopOrchestrator()

    async def execute(
        self,
        instance: AgentInstance,
        prompt: str,
        context: dict[str, Any] | None,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        Execute a prompt against a sop-agent instance.

        Args:
            instance: The active AgentInstance.
            prompt: User prompt to process.
            context: Optional additional context.
            db: Database session.

        Returns:
            Orchestrated SOP result.
        """
        # Load agent type to get the bound SOP
        from app.db.models.agents import AgentType

        agent_type = await db.get(AgentType, instance.agent_type_id)
        if not agent_type:
            raise SopAgentError(f"Agent type {instance.agent_type_id} not found")

        if agent_type.mode != AgentMode.sop_agent:
            raise SopAgentError(
                f"Agent type '{agent_type.name}' is not a sop-agent (mode={agent_type.mode})"
            )

        if not agent_type.sop_id:
            raise SopAgentError(
                f"sop-agent '{agent_type.name}' has no bound SOP"
            )

        logger.info(
            "sop-agent instance %s executing SOP %s for prompt: %s...",
            instance.id,
            agent_type.sop_id,
            prompt[:100],
        )

        result = await self._orchestrator.execute(
            sop_id=agent_type.sop_id,
            prompt=prompt,
            context=context,
            db=db,
        )

        return {
            "agent_type": agent_type.name,
            "instance_id": str(instance.id),
            "sop_result": result,
        }
