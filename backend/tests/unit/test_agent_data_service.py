from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_data import AgentData
from app.db.models.agent_data_type import AgentDataType
from app.db.models.agent_output import AgentOutput, AgentOutputValidationStatus
from app.db.models.agents import AgentJob, AgentJobStatus, AgentType
from app.services.agent_data.service import AgentDataService
from app.services.outputs.service import OutputService


async def _create_agent_type(db_session: AsyncSession) -> AgentType:
    agent_type = AgentType(name=f"agent-data-test-{uuid.uuid4().hex[:8]}")
    db_session.add(agent_type)
    await db_session.flush()
    return agent_type


async def _create_agent_job(db_session: AsyncSession, agent_type_id: uuid.UUID) -> AgentJob:
    job = AgentJob(
        agent_type_id=agent_type_id,
        status=AgentJobStatus.completed,
    )
    db_session.add(job)
    await db_session.flush()
    return job


async def _create_data_type(db_session: AsyncSession) -> AgentDataType:
    data_type = AgentDataType(
        name=f"agent-data-type-{uuid.uuid4().hex[:8]}",
        slug=f"agent-data-type-{uuid.uuid4().hex[:8]}",
        description="test data type",
        fields=[{"name": "summary", "type": "string", "required": False}],
    )
    db_session.add(data_type)
    await db_session.flush()
    return data_type


@pytest.mark.asyncio
async def test_save_creates_agent_data_record(db_session: AsyncSession) -> None:
    service = AgentDataService()
    agent_type = await _create_agent_type(db_session)
    job = await _create_agent_job(db_session, agent_type.id)

    record = await service.save(
        db=db_session,
        session_id=job.id,
        data_name="incident_summary",
        data_value={"severity": "high", "count": 3},
        agent_type_id=agent_type.id,
        data_type="json",
    )

    assert isinstance(record, AgentData)
    assert record.data_name == "incident_summary"
    assert record.data_value == {"severity": "high", "count": 3}
    assert record.agent_type_id == agent_type.id
    assert record.session_id == job.id
    assert record.data_type == "json"
    assert record.is_active is True


@pytest.mark.asyncio
async def test_query_by_filters_with_data_name(db_session: AsyncSession) -> None:
    service = AgentDataService()
    agent_type = await _create_agent_type(db_session)
    job = await _create_agent_job(db_session, agent_type.id)

    await service.save(
        db=db_session,
        session_id=job.id,
        data_name="target_name",
        data_value={"v": 1},
        agent_type_id=agent_type.id,
    )
    await service.save(
        db=db_session,
        session_id=job.id,
        data_name="other_name",
        data_value={"v": 2},
        agent_type_id=agent_type.id,
    )

    records = await service.query_by_filters(db=db_session, data_name="target_name")

    assert len(records) == 1
    assert records[0].data_name == "target_name"


@pytest.mark.asyncio
async def test_query_by_filters_with_agent_type_id(db_session: AsyncSession) -> None:
    service = AgentDataService()
    agent_type_1 = await _create_agent_type(db_session)
    agent_type_2 = await _create_agent_type(db_session)
    job_1 = await _create_agent_job(db_session, agent_type_1.id)
    job_2 = await _create_agent_job(db_session, agent_type_2.id)

    await service.save(
        db=db_session,
        session_id=job_1.id,
        data_name="shared_name",
        data_value={"v": 1},
        agent_type_id=agent_type_1.id,
    )
    await service.save(
        db=db_session,
        session_id=job_2.id,
        data_name="shared_name",
        data_value={"v": 2},
        agent_type_id=agent_type_2.id,
    )

    records = await service.query_by_filters(db=db_session, agent_type_id=agent_type_1.id)

    assert len(records) == 1
    assert records[0].agent_type_id == agent_type_1.id


@pytest.mark.asyncio
async def test_query_by_filters_with_session_id(db_session: AsyncSession) -> None:
    service = AgentDataService()
    agent_type = await _create_agent_type(db_session)
    job_1 = await _create_agent_job(db_session, agent_type.id)
    job_2 = await _create_agent_job(db_session, agent_type.id)

    await service.save(
        db=db_session,
        session_id=job_1.id,
        data_name="session_data",
        data_value={"v": 1},
        agent_type_id=agent_type.id,
    )
    await service.save(
        db=db_session,
        session_id=job_2.id,
        data_name="session_data",
        data_value={"v": 2},
        agent_type_id=agent_type.id,
    )

    records = await service.query_by_filters(db=db_session, session_id=job_1.id)

    assert len(records) == 1
    assert records[0].session_id == job_1.id


@pytest.mark.asyncio
async def test_query_by_filters_with_combined_filters(db_session: AsyncSession) -> None:
    service = AgentDataService()
    agent_type_1 = await _create_agent_type(db_session)
    agent_type_2 = await _create_agent_type(db_session)
    job_1 = await _create_agent_job(db_session, agent_type_1.id)
    job_2 = await _create_agent_job(db_session, agent_type_2.id)

    await service.save(
        db=db_session,
        session_id=job_1.id,
        data_name="combined",
        data_value={"v": "match"},
        agent_type_id=agent_type_1.id,
    )
    await service.save(
        db=db_session,
        session_id=job_2.id,
        data_name="combined",
        data_value={"v": "non-match"},
        agent_type_id=agent_type_2.id,
    )

    records = await service.query_by_filters(
        db=db_session,
        data_name="combined",
        agent_type_id=agent_type_1.id,
        session_id=job_1.id,
    )

    assert len(records) == 1
    assert records[0].data_value == {"v": "match"}


@pytest.mark.asyncio
async def test_query_by_filters_without_filters_raises(db_session: AsyncSession) -> None:
    service = AgentDataService()

    with pytest.raises(ValueError, match="At least one filter"):
        await service.query_by_filters(db=db_session)


@pytest.mark.asyncio
async def test_query_output_history_returns_filtered_records(db_session: AsyncSession) -> None:
    output_service = OutputService()

    agent_type_1 = await _create_agent_type(db_session)
    agent_type_2 = await _create_agent_type(db_session)
    job_1 = await _create_agent_job(db_session, agent_type_1.id)
    job_2 = await _create_agent_job(db_session, agent_type_2.id)
    data_type = await _create_data_type(db_session)

    now = datetime.now(UTC)
    inside_window = now - timedelta(hours=1)
    outside_window = now - timedelta(days=5)

    output_1 = AgentOutput(
        data_type_id=data_type.id,
        agent_type_id=agent_type_1.id,
        execution_session_id=job_1.id,
        field_values={"summary": "inside"},
        validation_status=AgentOutputValidationStatus.valid,
        raw_output="inside",
        created_at=inside_window,
    )
    output_2 = AgentOutput(
        data_type_id=data_type.id,
        agent_type_id=agent_type_2.id,
        execution_session_id=job_2.id,
        field_values={"summary": "outside"},
        validation_status=AgentOutputValidationStatus.valid,
        raw_output="outside",
        created_at=outside_window,
    )

    db_session.add_all([output_1, output_2])
    await db_session.flush()

    records = await output_service.query_output_history(
        db=db_session,
        date_from=(now - timedelta(days=1)).isoformat(),
        date_to=now.isoformat(),
    )

    assert len(records) == 1
    assert records[0].id == output_1.id

    by_session = await output_service.query_output_history(db=db_session, session_id=job_1.id)
    assert len(by_session) == 1
    assert by_session[0].execution_session_id == job_1.id
