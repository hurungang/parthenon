"""AgentType service — manages Agent Type CRUD and binding operations."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentType, AgentTypeSopBinding, AgentTypeSkillBinding
from app.schemas.agent_type_bindings import SkillBindingCreate, SopBindingCreate

logger = logging.getLogger(__name__)


class AgentTypeService:
    """Service layer for AgentType CRUD and binding management."""

    async def set_bindings(
        self,
        db: AsyncSession,
        agent_type_id: uuid.UUID,
        sop_bindings: list[SopBindingCreate],
        skill_bindings: list[SkillBindingCreate],
    ) -> None:
        """Atomically replace all bindings for the given agent type.

        1. Delete all existing AgentTypeSopBinding and AgentTypeSkillBinding rows.
        2. Create new rows from the input lists.
        3. Commit.
        """
        # Delete existing bindings
        await db.execute(
            select(AgentTypeSopBinding).where(
                AgentTypeSopBinding.agent_type_id == agent_type_id
            )
        )
        existing_sop = await db.execute(
            select(AgentTypeSopBinding).where(
                AgentTypeSopBinding.agent_type_id == agent_type_id
            )
        )
        for row in existing_sop.scalars().all():
            await db.delete(row)

        existing_skill = await db.execute(
            select(AgentTypeSkillBinding).where(
                AgentTypeSkillBinding.agent_type_id == agent_type_id
            )
        )
        for row in existing_skill.scalars().all():
            await db.delete(row)

        await db.flush()

        # Create new SOP bindings
        now = datetime.now(timezone.utc)
        for item in sop_bindings:
            binding = AgentTypeSopBinding(
                id=uuid.uuid4(),
                agent_type_id=agent_type_id,
                sop_id=item.sop_id,
                order=item.order,
                created_at=now,
            )
            db.add(binding)

        # Create new Skill bindings
        for item in skill_bindings:
            binding = AgentTypeSkillBinding(
                id=uuid.uuid4(),
                agent_type_id=agent_type_id,
                skill_id=item.skill_id,
                order=item.order,
                created_at=now,
            )
            db.add(binding)

        await db.flush()
        logger.info(
            "Set %d SOP bindings and %d Skill bindings for agent_type=%s",
            len(sop_bindings),
            len(skill_bindings),
            agent_type_id,
        )

    async def get_bindings(
        self,
        db: AsyncSession,
        agent_type_id: uuid.UUID,
    ) -> tuple[list[AgentTypeSopBinding], list[AgentTypeSkillBinding]]:
        """Return the current bindings for the given agent type."""
        from sqlalchemy.orm import selectinload

        sop_result = await db.execute(
            select(AgentTypeSopBinding)
            .where(AgentTypeSopBinding.agent_type_id == agent_type_id)
            .options(selectinload(AgentTypeSopBinding.sop))
            .order_by(AgentTypeSopBinding.order)
        )
        sop_bindings = list(sop_result.scalars().all())

        skill_result = await db.execute(
            select(AgentTypeSkillBinding)
            .where(AgentTypeSkillBinding.agent_type_id == agent_type_id)
            .options(selectinload(AgentTypeSkillBinding.skill))
            .order_by(AgentTypeSkillBinding.order)
        )
        skill_bindings = list(skill_result.scalars().all())

        return sop_bindings, skill_bindings
