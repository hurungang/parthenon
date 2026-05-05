"""Gateway Lifecycle Handler — orchestrates the gateway state machine.

Extended in the Agent Runtime with Gateway change to route inbound agent launch
requests through AgentSessionService.enqueue and return session IDs synchronously.
The legacy synchronous execution path is retained for backward compatibility but
all new agent launches use the asynchronous session queue.
"""
import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentInstanceStatus
from app.services.agents.instance_manager import AgentInstanceManager, InstanceLimitError
from app.services.agents.session_service import AgentSessionService

logger = logging.getLogger(__name__)

# In-memory store for pending questions per session handle
# In production this would be backed by Redis
_pending_questions: dict[str, asyncio.Queue] = {}
_pending_answers: dict[str, asyncio.Queue] = {}


class GatewayLifecycleHandler:
    """
    Orchestrates the gateway state machine.

    New path (Phase 5): launch → enqueue session → return session_id asynchronously.
    Legacy path: init → request (question → answer) → close (retained for compatibility).
    """

    def __init__(self) -> None:
        self._instance_manager = AgentInstanceManager()
        self._session_service = AgentSessionService()

    # ── New async launch path ──────────────────────────────────────────────────

    async def launch(
        self,
        agent_type_id: uuid.UUID,
        input_data: dict[str, Any] | None,
        user_id: uuid.UUID | None,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        Enqueue an agent session via the Session Queue and return the session ID
        synchronously. The actual execution is asynchronous.

        Returns:
            {"session_id": "<uuid>"}
        """
        job = await self._session_service.enqueue(
            agent_type_id=agent_type_id,
            input_data=input_data,
            user_id=user_id,
            db=db,
        )
        logger.info(
            "Gateway launch: enqueued session %s for type %s", job.id, agent_type_id
        )
        return {"session_id": str(job.id)}

    # ── Legacy init/request/close path ────────────────────────────────────────

    async def init(
        self,
        agent_type_id: Any,
        initiator_subject: str | None,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Initialize a legacy agent instance and return the session handle."""
        try:
            instance = await self._instance_manager.spawn(
                agent_type_id=agent_type_id,
                initiator_subject=initiator_subject,
                db=db,
            )
            instance = await self._instance_manager.activate(instance.id, db)
        except InstanceLimitError as exc:
            raise ValueError(str(exc))

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
        """Forward a prompt to the legacy agent instance."""
        instance = await self._instance_manager.get_by_handle(session_handle, db)
        if not instance:
            raise ValueError(f"Session handle not found: {session_handle}")
        if instance.status != AgentInstanceStatus.active:
            raise ValueError(f"Instance is not active (status={instance.status})")

        # NOTE: Legacy synchronous execution path. New agents use the async job queue.
        return {
            "response": (
                "This agent type uses the legacy gateway path. "
                "Use POST /api/v1/agents/sessions to launch agents via the async queue."
            ),
            "instance_id": str(instance.id),
            "session_handle": session_handle,
            "has_question": False,
        }

    async def get_question(
        self, session_handle: str, timeout: float = 5.0
    ) -> dict[str, Any]:
        """Long-poll for a pending agent question."""
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
        """Close the legacy agent instance and clean up the session."""
        instance = await self._instance_manager.get_by_handle(session_handle, db)
        if not instance:
            raise ValueError(f"Session handle not found: {session_handle}")

        await self._instance_manager.close(instance.id, db)

        _pending_questions.pop(session_handle, None)
        _pending_answers.pop(session_handle, None)

        logger.info("Gateway closed session %s (instance %s)", session_handle, instance.id)
        return {"closed": True, "instance_id": str(instance.id)}
