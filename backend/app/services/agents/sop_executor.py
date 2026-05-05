"""SOP Agent Executor — handles sop-agent prompt execution via SopOrchestrator."""
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentInstance
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
        # Load agent type — NOTE: SOP execution superseded by AgentJob/LangGraph in Phase 5.
        from app.db.models.agents import AgentType

        agent_type = await db.get(AgentType, instance.agent_type_id)
        if not agent_type:
            raise SopAgentError(f"Agent type {instance.agent_type_id} not found")

        raise SopAgentError(
            f"SOP-based execution for agent type '{agent_type.name}' is not supported in "
            "this version. Use the AgentJob queue (Phase 5) for agent execution."
        )
