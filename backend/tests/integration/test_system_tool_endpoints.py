from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import _CH_ALLOWLIST, require_service_certificate
from app.db.models.agent_data import AgentData
from app.db.models.agent_data_type import AgentDataType
from app.db.models.agent_output import AgentOutput, AgentOutputValidationStatus
from app.db.models.agents import AgentJob, AgentJobStatus, AgentType
from app.db.session import get_db
from app.main import create_app
from app.services.agents.system_tool_registry import SystemToolRegistry


def _bypass_service_cert():
    async def override():
        return {"cert_type": "service", "service_name": "test-service"}

    return override


@pytest_asyncio.fixture
async def authed_client(test_engine):
    app = create_app()
    app.dependency_overrides[require_service_certificate] = _bypass_service_cert()

    SessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


async def _create_agent_type(db: AsyncSession) -> AgentType:
    agent_type = AgentType(name=f"sys-tool-agent-{uuid.uuid4().hex[:8]}")
    db.add(agent_type)
    await db.flush()
    return agent_type


async def _create_agent_job(db: AsyncSession, agent_type_id: uuid.UUID) -> AgentJob:
    job = AgentJob(
        agent_type_id=agent_type_id,
        status=AgentJobStatus.completed,
    )
    db.add(job)
    await db.flush()
    return job


async def _create_data_type(db: AsyncSession) -> AgentDataType:
    data_type = AgentDataType(
        name=f"sys-tool-dt-{uuid.uuid4().hex[:8]}",
        slug=f"sys-tool-dt-{uuid.uuid4().hex[:8]}",
        description="test",
        fields=[{"name": "summary", "type": "string", "required": False}],
    )
    db.add(data_type)
    await db.flush()
    return data_type


@pytest.mark.asyncio
async def test_save_data_endpoint_saves_record(
    authed_client: AsyncClient,
    test_engine,
) -> None:
    async with async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)() as db:
        agent_type = await _create_agent_type(db)
        job = await _create_agent_job(db, agent_type.id)
        await db.commit()

    response = await authed_client.post(
        "/api/v1/internal/system-tools/save-data",
        json={
            "session_id": str(job.id),
            "tool_args": {
                "data_name": "incident_summary",
                "data_value": {"severity": "high"},
                "agent_type_id": str(agent_type.id),
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["result"]
    assert payload["data_name"] == "incident_summary"
    assert payload["session_id"] == str(job.id)

    async with async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)() as db:
        result = await db.execute(select(AgentData).where(AgentData.data_name == "incident_summary"))
        record = result.scalar_one_or_none()
        assert record is not None
        assert record.session_id == job.id
        assert record.agent_type_id == agent_type.id


@pytest.mark.asyncio
async def test_get_data_endpoint_requires_at_least_one_filter(
    authed_client: AsyncClient,
) -> None:
    response = await authed_client.post(
        "/api/v1/internal/system-tools/get-data",
        json={
            "session_id": str(uuid.uuid4()),
            "tool_args": {},
        },
    )

    assert response.status_code == 400
    assert "At least one filter" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_output_endpoint_returns_output_history(
    authed_client: AsyncClient,
    test_engine,
) -> None:
    created_at = datetime.now(UTC)

    async with async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)() as db:
        agent_type = await _create_agent_type(db)
        job = await _create_agent_job(db, agent_type.id)
        data_type = await _create_data_type(db)

        output = AgentOutput(
            data_type_id=data_type.id,
            agent_type_id=agent_type.id,
            execution_session_id=job.id,
            field_values={"summary": "history-entry"},
            validation_status=AgentOutputValidationStatus.valid,
            raw_output="history-entry",
            created_at=created_at,
        )
        db.add(output)
        await db.commit()

    response = await authed_client.post(
        "/api/v1/internal/system-tools/get-output",
        json={
            "session_id": str(uuid.uuid4()),
            "tool_args": {
                "session_id": str(job.id),
                "date_from": (created_at.replace(microsecond=0)).isoformat(),
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["result"]
    assert payload["count"] >= 1
    assert any(r["execution_session_id"] == str(job.id) for r in payload["records"])


# ── _CH_ALLOWLIST completeness tests ──────────────────────────────────


def test_ch_allowlist_contains_all_system_tool_cc_endpoint_paths() -> None:
    """Verify every system tool's CC endpoint path is in _CH_ALLOWLIST.

    Bug FIX-20260704-070000: When CommHub proxies system-tool calls
    (save_data, get_data, get_output) to Control Center, it receives
    HTTP 403 with ``deny_reason: endpoint_not_allowlisted`` because
    these paths are missing from _CH_ALLOWLIST.  The old deprecated
    ``save-result`` path is still present but the replacement endpoints
    are not.

    This test cross-references ``SystemToolRegistry`` (single source of
    truth) against ``_CH_ALLOWLIST``.  If CommHub would reject a
    registered system tool, this test fails.
    """
    # All system-tool endpoints registered on the internal router use POST.
    method = "POST"

    missing: list[str] = []
    stale_allowlisted: list[str] = []

    # 1. Check every registered system tool's CC endpoint is allowlisted
    for name, tool in sorted(SystemToolRegistry._tools.items()):
        path = tool.cc_endpoint_path
        if (method, path) not in _CH_ALLOWLIST:
            missing.append(f"{method} {path}  (tool={name})")

    # 2. Check for stale allowlist entries — paths in _CH_ALLOWLIST that
    #    refer to system-tools but no longer match any registered tool
    registered_paths = {
        (method, tool.cc_endpoint_path)
        for tool in SystemToolRegistry._tools.values()
    }
    for entry in sorted(_CH_ALLOWLIST):
        ep_method, ep_path = entry
        if "/system-tools/" in ep_path and entry not in registered_paths:
            stale_allowlisted.append(f"{ep_method} {ep_path}  (stale)")

    # Build failure message
    lines: list[str] = []
    if missing:
        lines.append("MISSING from _CH_ALLOWLIST (CommHub calls will get 403):")
        for m in missing:
            lines.append(f"    {m}")
    if stale_allowlisted:
        if lines:
            lines.append("")
        lines.append("STALE entries in _CH_ALLOWLIST (endpoint no longer exists):")
        for s in stale_allowlisted:
            lines.append(f"    {s}")
    if not lines:
        lines.append("All system-tool CC endpoint paths are correctly allowlisted.")

    assert not missing, "\n".join(lines) if lines else ""

    # stale entries are informational only — warn the team but don't fail
    if stale_allowlisted:
        import warnings
        warnings.warn(
            f"Stale entries in _CH_ALLOWLIST:\n" + "\n".join(stale_allowlisted)
        )
