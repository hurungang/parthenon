"""Agent Instance Manager — spawns and destroys agent instances with max_instances enforcement."""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentInstance, AgentInstanceStatus, AgentType

logger = logging.getLogger(__name__)


class InstanceLimitError(Exception):
    """Raised when max_instances limit is reached."""


class AgentInstanceManager:
    """
    Manages agent instance lifecycle: spawn, track, and destroy.
    Enforces max_instances per agent type.
    """

    async def spawn(
        self,
        agent_type_id: Any,
        initiator_subject: str | None,
        db: AsyncSession,
    ) -> AgentInstance:
        """
        Create a new AgentInstance for the given agent type.

        Raises InstanceLimitError if max_instances is reached.
        """
        # Load agent type
        agent_type = await db.get(AgentType, agent_type_id)
        if not agent_type:
            raise ValueError(f"AgentType {agent_type_id} not found")
        if not agent_type.is_active:
            raise ValueError(f"AgentType '{agent_type.name}' is not active")

        # NOTE: max_instances enforcement removed; capacity is now managed by the AgentJob queue.

        instance = AgentInstance(
            agent_type_id=agent_type_id,
            status=AgentInstanceStatus.created,
            session_handle=str(uuid.uuid4()),
            initiator_subject=initiator_subject,
        )
        db.add(instance)
        await db.flush()
        await db.refresh(instance)

        logger.info(
            "Spawned agent instance %s for type %s (initiator=%s)",
            instance.id,
            agent_type_id,
            initiator_subject,
        )
        return instance

    async def activate(self, instance_id: Any, db: AsyncSession) -> AgentInstance:
        """Transition an instance from created → active."""
        instance = await db.get(AgentInstance, instance_id)
        if not instance:
            raise ValueError(f"AgentInstance {instance_id} not found")
        if instance.status != AgentInstanceStatus.created:
            raise ValueError(
                f"Cannot activate instance in status '{instance.status}'"
            )
        instance.status = AgentInstanceStatus.active
        await db.flush()
        await db.refresh(instance)
        return instance

    async def close(self, instance_id: Any, db: AsyncSession) -> AgentInstance:
        """Terminate an agent instance."""
        instance = await db.get(AgentInstance, instance_id)
        if not instance:
            raise ValueError(f"AgentInstance {instance_id} not found")
        instance.status = AgentInstanceStatus.closed
        instance.closed_at = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(instance)
        logger.info("Closed agent instance %s", instance_id)
        return instance

    async def get_by_handle(
        self, session_handle: str, db: AsyncSession
    ) -> AgentInstance | None:
        """Resolve an AgentInstance by its session handle."""
        result = await db.execute(
            select(AgentInstance).where(AgentInstance.session_handle == session_handle)
        )
        return result.scalar_one_or_none()

    async def list_active(
        self, agent_type_id: Any, db: AsyncSession
    ) -> list[AgentInstance]:
        """List all active (created or active) instances for an agent type."""
        result = await db.execute(
            select(AgentInstance).where(
                AgentInstance.agent_type_id == agent_type_id,
                AgentInstance.status.in_(
                    [AgentInstanceStatus.created, AgentInstanceStatus.active]
                ),
            )
        )
        return list(result.scalars().all())
