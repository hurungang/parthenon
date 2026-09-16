"""AgentType service — manages Agent Type CRUD and binding operations."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, TypeVar

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentType, AgentTypeSopBinding, AgentTypeSkillBinding
from app.schemas.agent_type_bindings import SkillBindingCreate, SopBindingCreate

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


def _dedupe_by_id(items: list[_T], id_of: Any) -> list[_T]:
    """Return *items* with duplicate ids removed — first occurrence wins.

    Keeps the payload idempotent: a client that (re)submits the same binding
    list — possibly with duplicated entries — never trips the per-agent-type
    unique binding constraints. Order of first occurrences is preserved so
    the caller's binding order semantics survive deduplication.
    """
    seen: set[Any] = set()
    deduped: list[_T] = []
    for item in items:
        key = id_of(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


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

        1. Deduplicate the incoming lists by sop_id / skill_id (first
           occurrence wins — repeated saves of the same payload are a no-op).
        2. Bulk-delete all existing AgentTypeSopBinding and
           AgentTypeSkillBinding rows.
        3. Create new rows from the deduplicated lists and flush.

        The caller owns the transaction (flush only, no commit).
        """
        deduped_sop_bindings = _dedupe_by_id(sop_bindings, lambda b: b.sop_id)
        deduped_skill_bindings = _dedupe_by_id(skill_bindings, lambda b: b.skill_id)

        dropped_sop = len(sop_bindings) - len(deduped_sop_bindings)
        dropped_skill = len(skill_bindings) - len(deduped_skill_bindings)
        if dropped_sop or dropped_skill:
            logger.warning(
                "Deduplicated binding payload for agent_type=%s: dropped %d duplicate SOP "
                "and %d duplicate Skill entries (first occurrence wins)",
                agent_type_id,
                dropped_sop,
                dropped_skill,
            )

        # Bulk-delete existing bindings (single DELETE per table).
        await db.execute(
            delete(AgentTypeSopBinding).where(
                AgentTypeSopBinding.agent_type_id == agent_type_id
            )
        )
        await db.execute(
            delete(AgentTypeSkillBinding).where(
                AgentTypeSkillBinding.agent_type_id == agent_type_id
            )
        )

        await db.flush()

        # Create new SOP bindings
        now = datetime.now(timezone.utc)
        for item in deduped_sop_bindings:
            binding = AgentTypeSopBinding(
                id=uuid.uuid4(),
                agent_type_id=agent_type_id,
                sop_id=item.sop_id,
                order=item.order,
                created_at=now,
            )
            db.add(binding)

        # Create new Skill bindings
        for item in deduped_skill_bindings:
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
            len(deduped_sop_bindings),
            len(deduped_skill_bindings),
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
