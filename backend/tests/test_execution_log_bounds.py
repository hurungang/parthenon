"""``get_execution_log`` reference selection + bounded text log.

The optimizer must learn from the latest SUCCESSFUL *normal* execution, not
from its own in-flight optimization run. The internal tool therefore:

- lists recent normal executions (newest first), excluding command
  (optimization side) runs and the current session;
- selects the latest completed normal execution (or an explicit ``session_id``);
- returns that execution's TEXT LOG in chronological order, bounded by
  ``limit`` (default 100, max 500).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_service_certificate
from app.db.models.agents import (
    AgentInputType,
    AgentJob,
    AgentJobStatus,
    AgentOutputType,
    AgentType,
)
from app.db.models.session_logs import ExecutionLogEntry
from app.db.session import get_db
from app.main import create_app
from app.services.tenancy.root_tenant import ensure_root_tenant


def _bypass_service_cert():
    async def override():
        return {"cert_type": "service", "service_name": "agent-runtime"}

    return override


@pytest_asyncio.fixture
async def internal_client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    app = create_app()
    app.dependency_overrides[require_service_certificate] = _bypass_service_cert()

    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db

    async with SessionLocal() as session:
        await ensure_root_tenant(session)
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def _call(
    client: AsyncClient,
    tool: str,
    tool_args: dict[str, Any],
    *,
    session_id: uuid.UUID | None = None,
) -> dict:
    resp = await client.post(
        f"/api/v1/internal/system-tools/{tool}",
        json={
            "session_id": str(session_id or uuid.uuid4()),
            "tool_args": tool_args,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["result"]


def _session_factory(test_engine):
    return async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )


async def _seed_agent_type(
    test_engine, *, input_schema: dict[str, Any] | None = None
) -> uuid.UUID:
    agent_type_id = uuid.uuid4()
    SessionLocal = _session_factory(test_engine)
    async with SessionLocal() as session:
        session.add(
            AgentType(
                id=agent_type_id,
                name=f"log-{agent_type_id.hex[:8]}",
                input_type=(
                    AgentInputType.typed
                    if input_schema is not None
                    else AgentInputType.none
                ),
                input_schema=input_schema,
                output_type=AgentOutputType.markdown,
            )
        )
        await session.commit()
    return agent_type_id


async def _seed_job(
    test_engine,
    *,
    agent_type_id: uuid.UUID,
    status: AgentJobStatus,
    created_at: datetime,
    command: bool = False,
    messages: list[str] | None = None,
    input_payload: dict[str, Any] | None = None,
) -> uuid.UUID:
    """Create one AgentJob (normal or command) plus its log entries."""
    job_id = uuid.uuid4()
    SessionLocal = _session_factory(test_engine)
    async with SessionLocal() as session:
        input_data: dict[str, Any] = (
            dict(input_payload) if input_payload is not None else {"message": "run"}
        )
        if command:
            input_data["__command"] = "optimize-and-verify"
        session.add(
            AgentJob(
                id=job_id,
                agent_type_id=agent_type_id,
                status=status,
                input_data=input_data,
                created_at=created_at,
                started_at=created_at,
                completed_at=(
                    created_at + timedelta(seconds=30)
                    if status is AgentJobStatus.completed
                    else None
                ),
            )
        )
        await session.flush()
        for index, message in enumerate(messages or []):
            session.add(
                ExecutionLogEntry(
                    session_id=job_id,
                    timestamp=created_at + timedelta(seconds=index),
                    log_level="INFO",
                    event_type="tool_call",
                    message=message,
                )
            )
        await session.commit()
    return job_id


async def _seed_entries(
    test_engine, *, session_id: uuid.UUID, count: int, prefix: str = "entry"
) -> None:
    """Seed *count* rising-timestamp entries on an existing job."""
    base = datetime.now(UTC) - timedelta(minutes=count + 1)
    SessionLocal = _session_factory(test_engine)
    async with SessionLocal() as session:
        for index in range(count):
            session.add(
                ExecutionLogEntry(
                    session_id=session_id,
                    timestamp=base + timedelta(seconds=index),
                    log_level="INFO",
                    event_type="llm_call",
                    message=f"{prefix}-{index}",
                )
            )
        await session.commit()


class TestExecutionLogSelection:
    async def test_selects_latest_completed_normal_run_and_excludes_current(
        self, internal_client, test_engine
    ):
        agent_type_id = await _seed_agent_type(test_engine)
        now = datetime.now(UTC)
        await _seed_job(
            test_engine,
            agent_type_id=agent_type_id,
            status=AgentJobStatus.completed,
            created_at=now - timedelta(hours=3),
            messages=["old-run"],
        )
        await _seed_job(
            test_engine,
            agent_type_id=agent_type_id,
            status=AgentJobStatus.failed,
            created_at=now - timedelta(hours=2),
            messages=["failed-run"],
        )
        latest_completed = await _seed_job(
            test_engine,
            agent_type_id=agent_type_id,
            status=AgentJobStatus.completed,
            created_at=now - timedelta(hours=1),
            messages=["good-run-start", "good-run-end"],
        )
        current_optimize = await _seed_job(
            test_engine,
            agent_type_id=agent_type_id,
            status=AgentJobStatus.running,
            created_at=now,
            command=True,
            messages=["optimize-own-log"],
        )

        result = await _call(
            internal_client,
            "get-execution-log",
            {"agent_type_id": str(agent_type_id)},
            session_id=current_optimize,
        )

        assert result["selected_session_id"] == str(latest_completed)
        assert result["selected_status"] == "completed"
        assert result["selection"] == "latest_successful_execution"
        assert [e["message"] for e in result["entries"]] == [
            "good-run-start",
            "good-run-end",
        ]
        assert "good-run-start" in result["text"]
        # The list contains normal runs only — never command runs / the
        # current optimization session.
        listed_ids = {e["session_id"] for e in result["executions"]}
        assert str(current_optimize) not in listed_ids
        assert len(listed_ids) == 3
        assert all(e["status"] != "running" for e in result["executions"])

    async def test_explicit_session_id_selects_that_execution(
        self, internal_client, test_engine
    ):
        agent_type_id = await _seed_agent_type(test_engine)
        now = datetime.now(UTC)
        older = await _seed_job(
            test_engine,
            agent_type_id=agent_type_id,
            status=AgentJobStatus.completed,
            created_at=now - timedelta(hours=2),
            messages=["older-run"],
        )
        await _seed_job(
            test_engine,
            agent_type_id=agent_type_id,
            status=AgentJobStatus.completed,
            created_at=now - timedelta(hours=1),
            messages=["newer-run"],
        )

        result = await _call(
            internal_client,
            "get-execution-log",
            {"agent_type_id": str(agent_type_id), "session_id": str(older)},
        )

        assert result["selection"] == "explicit_session"
        assert result["selected_session_id"] == str(older)
        assert [e["message"] for e in result["entries"]] == ["older-run"]

    async def test_returns_reference_input_and_input_schema(
        self, internal_client, test_engine
    ):
        """The optimizer gets the reference run's real input keys + schema.

        This is what prevents guessed/renamed context keys (e.g. ``date``
        instead of ``travel_date``) in authored scripts.
        """
        schema = {
            "type": "object",
            "properties": {
                "origin": {"type": "string"},
                "destination": {"type": "string"},
                "travel_date": {"type": "string"},
            },
            "required": ["origin", "destination", "travel_date"],
        }
        agent_type_id = await _seed_agent_type(test_engine, input_schema=schema)
        latest = await _seed_job(
            test_engine,
            agent_type_id=agent_type_id,
            status=AgentJobStatus.completed,
            created_at=datetime.now(UTC) - timedelta(hours=1),
            messages=["run"],
            input_payload={
                "origin": "MEL",
                "destination": "SYD",
                "travel_date": "2026-11-15",
                "__conv_session_id": "internal-only",
            },
        )

        result = await _call(
            internal_client, "get-execution-log", {"agent_type_id": str(agent_type_id)}
        )

        assert result["selected_session_id"] == str(latest)
        assert result["input"] == {
            "origin": "MEL",
            "destination": "SYD",
            "travel_date": "2026-11-15",
        }
        assert result["input_schema"] == schema

    async def test_falls_back_to_latest_run_when_none_completed(
        self, internal_client, test_engine
    ):
        agent_type_id = await _seed_agent_type(test_engine)
        await _seed_job(
            test_engine,
            agent_type_id=agent_type_id,
            status=AgentJobStatus.failed,
            created_at=datetime.now(UTC) - timedelta(hours=1),
            messages=["failed-only"],
        )

        result = await _call(
            internal_client, "get-execution-log", {"agent_type_id": str(agent_type_id)}
        )

        assert result["selection"] == "latest_execution_no_success"
        assert result["selected_status"] == "failed"
        assert [e["message"] for e in result["entries"]] == ["failed-only"]

    async def test_empty_history_is_a_valid_result(self, internal_client):
        result = await _call(
            internal_client,
            "get-execution-log",
            {"agent_type_id": str(uuid.uuid4())},
        )
        assert result["selection"] == "none"
        assert result["selected_session_id"] is None
        assert result["entries"] == []
        assert result["executions"] == []
        assert "message" in result

    async def test_agent_type_id_is_required(self, internal_client):
        resp = await internal_client.post(
            "/api/v1/internal/system-tools/get-execution-log",
            json={"session_id": str(uuid.uuid4()), "tool_args": {}},
        )
        assert resp.status_code == 400


class TestExecutionLogBounds:
    async def test_default_limit_is_one_hundred_chronological(
        self, internal_client, test_engine
    ):
        agent_type_id = await _seed_agent_type(test_engine)
        job_id = await _seed_job(
            test_engine,
            agent_type_id=agent_type_id,
            status=AgentJobStatus.completed,
            created_at=datetime.now(UTC) - timedelta(hours=1),
        )
        await _seed_entries(test_engine, session_id=job_id, count=150)

        result = await _call(
            internal_client, "get-execution-log", {"agent_type_id": str(agent_type_id)}
        )

        assert len(result["entries"]) == 100
        # Chronological: the last 100 entries (50..149), oldest first.
        assert result["entries"][0]["message"] == "entry-50"
        assert result["entries"][-1]["message"] == "entry-149"

    async def test_limit_is_clamped_to_max_five_hundred(
        self, internal_client, test_engine
    ):
        agent_type_id = await _seed_agent_type(test_engine)
        job_id = await _seed_job(
            test_engine,
            agent_type_id=agent_type_id,
            status=AgentJobStatus.completed,
            created_at=datetime.now(UTC) - timedelta(hours=1),
        )
        await _seed_entries(test_engine, session_id=job_id, count=600)

        result = await _call(
            internal_client,
            "get-execution-log",
            {"agent_type_id": str(agent_type_id), "limit": 5_000},
        )

        assert len(result["entries"]) == 500
        assert result["entries"][-1]["message"] == "entry-599"

    async def test_invalid_limit_falls_back_to_default(
        self, internal_client, test_engine
    ):
        agent_type_id = await _seed_agent_type(test_engine)
        job_id = await _seed_job(
            test_engine,
            agent_type_id=agent_type_id,
            status=AgentJobStatus.completed,
            created_at=datetime.now(UTC) - timedelta(hours=1),
        )
        await _seed_entries(test_engine, session_id=job_id, count=5)

        result = await _call(
            internal_client,
            "get-execution-log",
            {"agent_type_id": str(agent_type_id), "limit": "not-a-number"},
        )

        assert len(result["entries"]) == 5

    async def test_executions_list_is_bounded(self, internal_client, test_engine):
        agent_type_id = await _seed_agent_type(test_engine)
        now = datetime.now(UTC)
        for index in range(6):
            await _seed_job(
                test_engine,
                agent_type_id=agent_type_id,
                status=AgentJobStatus.completed,
                created_at=now - timedelta(hours=index + 1),
                messages=[f"run-{index}"],
            )

        result = await _call(
            internal_client,
            "get-execution-log",
            {"agent_type_id": str(agent_type_id), "executions_limit": 2},
        )

        assert len(result["executions"]) == 2
