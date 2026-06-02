from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run_relationship import (
    AgentRunRelationship,
    AgentRunRelationshipType,
)
from app.db.models.agents import (
    AgentInputType,
    AgentJob,
    AgentJobStatus,
    AgentOutputType,
    AgentTerminationCategory,
    AgentType,
)
from app.db.models.identity import Identity, IdentityType
from app.db.models.termination_cascade_outcome import (
    TerminationCascadeOutcome,
    TerminationOutcome,
)
from app.db.models.termination_request import (
    TerminationRequest,
    TerminationRequestStatus,
    TerminationScope,
)
from app.services.control_center.termination_orchestrator import (
    TerminationDeniedError,
    TerminationOrchestrator,
)


async def _create_agent_type(db_session: AsyncSession, suffix: str) -> AgentType:
    agent_type = AgentType(
        name=f"runtime-agent-{suffix}",
        model_id="gpt-4o-mini",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.auto,
    )
    db_session.add(agent_type)
    await db_session.flush()
    return agent_type


async def _create_job(
    db_session: AsyncSession,
    agent_type_id: uuid.UUID,
    status: AgentJobStatus,
) -> AgentJob:
    job = AgentJob(
        agent_type_id=agent_type_id,
        status=status,
        input_data={"query": "runtime-control"},
    )
    db_session.add(job)
    await db_session.flush()
    return job


@pytest.mark.asyncio
async def test_termination_cascade_persists_outcomes_and_categories(db_session: AsyncSession):
    suffix = uuid.uuid4().hex[:8]
    orchestrator = TerminationOrchestrator()

    identity = Identity(
        subject=f"runtime-op-{suffix}",
        identity_type=IdentityType.user,
        is_active=True,
    )
    db_session.add(identity)

    root_type = await _create_agent_type(db_session, f"{suffix}-root")
    child_type = await _create_agent_type(db_session, f"{suffix}-child")
    leaf_type = await _create_agent_type(db_session, f"{suffix}-leaf")

    root_job = await _create_job(db_session, root_type.id, AgentJobStatus.running)
    child_job = await _create_job(db_session, child_type.id, AgentJobStatus.running)
    completed_leaf = await _create_job(db_session, leaf_type.id, AgentJobStatus.completed)

    db_session.add_all(
        [
            AgentRunRelationship(
                parent_agent_job_id=root_job.id,
                child_agent_job_id=child_job.id,
                relationship_type=AgentRunRelationshipType.delegation,
                depth_from_root=1,
            ),
            AgentRunRelationship(
                parent_agent_job_id=child_job.id,
                child_agent_job_id=completed_leaf.id,
                relationship_type=AgentRunRelationshipType.delegation,
                depth_from_root=2,
            ),
        ]
    )
    await db_session.flush()

    request_record = await orchestrator.request_termination(
        target_session_id=root_job.id,
        requested_by_user_id=identity.id,
        scope=TerminationScope.cascade_subtree,
        operator_reason="policy intervention",
        db=db_session,
        can_terminate=True,
    )

    assert request_record.request_status == TerminationRequestStatus.completed

    outcomes = (
        (
            await db_session.execute(
                select(TerminationCascadeOutcome).where(
                    TerminationCascadeOutcome.termination_request_id == request_record.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(outcomes) == 3

    outcome_by_job = {o.affected_agent_job_id: o for o in outcomes}
    assert outcome_by_job[root_job.id].termination_outcome == TerminationOutcome.terminated
    assert outcome_by_job[child_job.id].termination_outcome == TerminationOutcome.terminated
    assert (
        outcome_by_job[completed_leaf.id].termination_outcome
        == TerminationOutcome.already_completed
    )

    refreshed_root = await db_session.get(AgentJob, root_job.id)
    refreshed_child = await db_session.get(AgentJob, child_job.id)
    refreshed_leaf = await db_session.get(AgentJob, completed_leaf.id)

    assert refreshed_root is not None
    assert refreshed_child is not None
    assert refreshed_leaf is not None

    assert refreshed_root.status == AgentJobStatus.failed
    assert refreshed_root.termination_category == AgentTerminationCategory.user_requested

    assert refreshed_child.status == AgentJobStatus.failed
    assert (
        refreshed_child.termination_category
        == AgentTerminationCategory.cascade_parent_terminated
    )

    assert refreshed_leaf.status == AgentJobStatus.completed


@pytest.mark.asyncio
async def test_termination_denial_persists_policy_rejection(db_session: AsyncSession):
    suffix = uuid.uuid4().hex[:8]
    orchestrator = TerminationOrchestrator()

    identity = Identity(
        subject=f"runtime-op-denied-{suffix}",
        identity_type=IdentityType.user,
        is_active=True,
    )
    db_session.add(identity)

    agent_type = await _create_agent_type(db_session, f"{suffix}-denied")
    target_job = await _create_job(db_session, agent_type.id, AgentJobStatus.running)

    with pytest.raises(TerminationDeniedError):
        await orchestrator.request_termination(
            target_session_id=target_job.id,
            requested_by_user_id=identity.id,
            scope=TerminationScope.node_only,
            operator_reason="unauthorized",
            db=db_session,
            can_terminate=False,
        )

    requests = (
        (
            await db_session.execute(
                select(TerminationRequest).where(
                    TerminationRequest.target_agent_job_id == target_job.id
                )
            )
        )
        .scalars()
        .all()
    )

    assert len(requests) == 1
    assert requests[0].request_status == TerminationRequestStatus.rejected
    assert "does not have runtime terminate permission" in (
        requests[0].permission_evaluation_reason or ""
    )

    outcomes = (
        (
            await db_session.execute(
                select(TerminationCascadeOutcome).where(
                    TerminationCascadeOutcome.affected_agent_job_id == target_job.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert outcomes == []
