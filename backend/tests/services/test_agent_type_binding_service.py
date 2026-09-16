"""Unit tests for AgentTypeService.set_bindings — idempotency and dedupe.

Regression coverage for the save-flow IntegrityError (uq_agent_type_skill_binding
UniqueViolationError on PUT /api/v1/agents/types/{id}): resubmitting the same
bindings and submitting lists with duplicated ids must never raise, and must
leave exactly one binding row per resource.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentInputType, AgentOutputType, AgentTypeSopBinding, AgentTypeSkillBinding
from app.db.models.agents import AgentType
from app.db.models.skills import Skill, Sop
from app.schemas.agent_type_bindings import SkillBindingCreate, SopBindingCreate
from app.services.agents.agent_type_service import AgentTypeService

pytestmark = pytest.mark.asyncio


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


async def _seed_agent_type(db: AsyncSession) -> AgentType:
    agent_type = AgentType(
        name=_unique("agent"),
        model_id="gpt-4o-mini",
        input_type=AgentInputType.conversation,
        output_type=AgentOutputType.auto,
    )
    db.add(agent_type)
    await db.flush()
    return agent_type


async def _seed_sop_and_skill(db: AsyncSession) -> tuple[Sop, Skill]:
    sop = Sop(name=_unique("sop"), description="Test SOP", instructions="Do the thing.")
    db.add(sop)
    await db.flush()
    skill = Skill(name=_unique("skill"), description="Test skill")
    db.add(skill)
    await db.flush()
    return sop, skill


async def _load_bindings(db: AsyncSession, agent_type_id: uuid.UUID) -> tuple[list[AgentTypeSopBinding], list[AgentTypeSkillBinding]]:
    sops = list(
        (
            await db.execute(
                select(AgentTypeSopBinding)
                .where(AgentTypeSopBinding.agent_type_id == agent_type_id)
                .order_by(AgentTypeSopBinding.order)
            )
        )
        .scalars()
        .all()
    )
    skills = list(
        (
            await db.execute(
                select(AgentTypeSkillBinding)
                .where(AgentTypeSkillBinding.agent_type_id == agent_type_id)
                .order_by(AgentTypeSkillBinding.order)
            )
        )
        .scalars()
        .all()
    )
    return sops, skills


class TestSetBindingsIdempotency:
    async def test_resubmitting_same_bindings_succeeds(self, db_session: AsyncSession):
        """Resubmitting the identical binding payload is a no-op — never 500s."""
        service = AgentTypeService()
        agent_type = await _seed_agent_type(db_session)
        sop, skill = await _seed_sop_and_skill(db_session)

        sop_payload = [SopBindingCreate(sop_id=sop.id, order=1)]
        skill_payload = [SkillBindingCreate(skill_id=skill.id, order=1)]

        await service.set_bindings(db_session, agent_type.id, sop_payload, skill_payload)
        await db_session.commit()

        await service.set_bindings(db_session, agent_type.id, sop_payload, skill_payload)
        await service.set_bindings(db_session, agent_type.id, list(sop_payload), list(skill_payload))
        await db_session.commit()

        sops, skills = await _load_bindings(db_session, agent_type.id)
        assert [(b.sop_id, b.order) for b in sops] == [(sop.id, 1)]
        assert [(b.skill_id, b.order) for b in skills] == [(skill.id, 1)]

    async def test_replacing_bindings_swaps_rows(self, db_session: AsyncSession):
        """Delete-then-insert: a second save with different bindings replaces the first set."""
        service = AgentTypeService()
        agent_type = await _seed_agent_type(db_session)
        sop, skill = await _seed_sop_and_skill(db_session)
        other_skill = Skill(name=_unique("skill"), description="Second skill")
        db_session.add(other_skill)
        await db_session.flush()

        await service.set_bindings(
            db_session,
            agent_type.id,
            [SopBindingCreate(sop_id=sop.id, order=1)],
            [SkillBindingCreate(skill_id=skill.id, order=1)],
        )
        await db_session.commit()

        await service.set_bindings(
            db_session,
            agent_type.id,
            [],
            [SkillBindingCreate(skill_id=other_skill.id, order=1)],
        )
        await db_session.commit()

        sops, skills = await _load_bindings(db_session, agent_type.id)
        assert sops == []
        assert [(b.skill_id, b.order) for b in skills] == [(other_skill.id, 1)]


class TestSetBindingsDedupesPayload:
    async def test_duplicate_skill_ids_in_payload_are_deduped(self, db_session: AsyncSession):
        """The same skill twice in ONE payload collapses to a single binding row."""
        service = AgentTypeService()
        agent_type = await _seed_agent_type(db_session)
        _, skill = await _seed_sop_and_skill(db_session)

        await service.set_bindings(
            db_session,
            agent_type.id,
            [],
            [
                SkillBindingCreate(skill_id=skill.id, order=1),
                SkillBindingCreate(skill_id=skill.id, order=2),
            ],
        )
        await db_session.commit()

        _, skills = await _load_bindings(db_session, agent_type.id)
        assert [(b.skill_id, b.order) for b in skills] == [(skill.id, 1)]

    async def test_duplicate_sop_ids_in_payload_are_deduped(self, db_session: AsyncSession):
        """The same SOP twice in ONE payload collapses to a single binding row."""
        service = AgentTypeService()
        agent_type = await _seed_agent_type(db_session)
        sop, _ = await _seed_sop_and_skill(db_session)

        await service.set_bindings(
            db_session,
            agent_type.id,
            [
                SopBindingCreate(sop_id=sop.id, order=2),
                SopBindingCreate(sop_id=sop.id, order=5),
            ],
            [],
        )
        await db_session.commit()

        sops, _ = await _load_bindings(db_session, agent_type.id)
        assert [(b.sop_id, b.order) for b in sops] == [(sop.id, 2)]

    async def test_dedupe_keeps_other_bindings(self, db_session: AsyncSession):
        """Dedupe only collapses repeated ids — distinct bindings all survive."""
        service = AgentTypeService()
        agent_type = await _seed_agent_type(db_session)
        _, skill1 = await _seed_sop_and_skill(db_session)
        skill2 = Skill(name=_unique("skill"), description="Second skill")
        db_session.add(skill2)
        await db_session.flush()

        await service.set_bindings(
            db_session,
            agent_type.id,
            [],
            [
                SkillBindingCreate(skill_id=skill1.id, order=1),
                SkillBindingCreate(skill_id=skill2.id, order=2),
                SkillBindingCreate(skill_id=skill1.id, order=3),
            ],
        )
        await db_session.commit()

        _, skills = await _load_bindings(db_session, agent_type.id)
        assert [(b.skill_id, b.order) for b in skills] == [
            (skill1.id, 1),
            (skill2.id, 2),
        ]
