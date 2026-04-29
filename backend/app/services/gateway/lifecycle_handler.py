"""Gateway Lifecycle Handler — orchestrates the gateway state machine."""
import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentInstanceStatus, AgentMode
from app.services.agents.instance_manager import AgentInstanceManager, InstanceLimitError
from app.services.agents.sop_executor import SopAgentExecutor
from app.services.agents.skillful_executor import SkillfulAgentExecutor

logger = logging.getLogger(__name__)

# In-memory store for pending questions per session handle
# In production this would be backed by Redis
_pending_questions: dict[str, asyncio.Queue] = {}
_pending_answers: dict[str, asyncio.Queue] = {}


class GatewayLifecycleHandler:
    """
    Orchestrates the gateway state machine:
    init → request (question → answer) → close
    """

    def __init__(self) -> None:
        self._instance_manager = AgentInstanceManager()
        self._sop_executor = SopAgentExecutor()
        self._skillful_executor = SkillfulAgentExecutor()

    async def init(
        self,
        agent_type_id: Any,
        initiator_subject: str | None,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Initialize an agent instance and return the session handle."""
        try:
            instance = await self._instance_manager.spawn(
                agent_type_id=agent_type_id,
                initiator_subject=initiator_subject,
                db=db,
            )
            instance = await self._instance_manager.activate(instance.id, db)
        except InstanceLimitError as exc:
            raise ValueError(str(exc))

        # Initialize question/answer queues for this session
        _pending_questions[instance.session_handle] = asyncio.Queue()
        _pending_answers[instance.session_handle] = asyncio.Queue()

        logger.info("Gateway init: instance %s, handle=%s", instance.id, instance.session_handle)
        return {
            "session_handle": instance.session_handle,
            "instance_id": str(instance.id),
            "agent_type_id": str(agent_type_id),
        }

    async def request(
        self,
        session_handle: str,
        prompt: str,
        context: dict[str, Any] | None,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Forward a prompt to the agent instance and return its response."""
        instance = await self._instance_manager.get_by_handle(session_handle, db)
        if not instance:
            raise ValueError(f"Session handle not found: {session_handle}")
        if instance.status != AgentInstanceStatus.active:
            raise ValueError(f"Instance is not active (status={instance.status})")

        from app.db.models.agents import AgentType
        agent_type = await db.get(AgentType, instance.agent_type_id)
        if not agent_type:
            raise ValueError(f"Agent type not found: {instance.agent_type_id}")

        if agent_type.mode == AgentMode.sop_agent:
            result = await self._sop_executor.execute(
                instance=instance, prompt=prompt, context=context, db=db
            )
        else:
            result = await self._skillful_executor.execute(
                instance=instance, prompt=prompt, context=context, db=db
            )

        return {
            "response": result.get("answer", str(result)),
            "instance_id": str(instance.id),
            "session_handle": session_handle,
            "has_question": False,
        }

    async def get_question(
        self, session_handle: str, timeout: float = 5.0
    ) -> dict[str, Any]:
        """Long-poll for a pending agent question. Returns None if no question within timeout."""
        queue = _pending_questions.get(session_handle)
        if not queue:
            raise ValueError(f"Session handle not found: {session_handle}")

        try:
            question = await asyncio.wait_for(queue.get(), timeout=timeout)
            return {"question": question, "pending": True}
        except asyncio.TimeoutError:
            return {"question": None, "pending": False}

    async def answer(
        self, session_handle: str, answer_text: str
    ) -> dict[str, Any]:
        """Provide an answer to a pending agent question."""
        queue = _pending_answers.get(session_handle)
        if not queue:
            raise ValueError(f"Session handle not found: {session_handle}")

        await queue.put(answer_text)
        return {"acknowledged": True}

    async def close(
        self, session_handle: str, db: AsyncSession
    ) -> dict[str, Any]:
        """Close the agent instance and clean up the session."""
        instance = await self._instance_manager.get_by_handle(session_handle, db)
        if not instance:
            raise ValueError(f"Session handle not found: {session_handle}")

        await self._instance_manager.close(instance.id, db)

        # Clean up queues
        _pending_questions.pop(session_handle, None)
        _pending_answers.pop(session_handle, None)

        logger.info("Gateway closed session %s (instance %s)", session_handle, instance.id)
        return {"closed": True, "instance_id": str(instance.id)}
