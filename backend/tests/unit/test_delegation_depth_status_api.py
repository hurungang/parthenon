"""Control Center depth plumbing unit tests.

Covers:
- the internal session payload exposing the job's persisted delegation depth,
- the delegation status endpoint returning the session agent type's CONFIGURED
  maximum depth (for two agent types with different values) with a platform
  default fallback that is never a one-level constant,
- the pending-intervention query remaining direct-child scoped.

These tests deliberately call the route handlers directly (no HTTP stack) so the
assertions are tied to the persisted column and the configured value rather than
to a constant.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.v1.agents import get_delegation_status, get_pending_intervention
from app.api.v1.internal.session_data import get_session
from app.services.agents.guardrails import PLATFORM_DEFAULT_MAX_DELEGATION_DEPTH


class _FakeResult:
    """Minimal SQLAlchemy Result stand-in for handler-level tests."""

    def __init__(self, rows: list[object] | None = None) -> None:
        self._rows = rows or []

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[object]:
        return self._rows

    def fetchall(self) -> list[object]:
        return self._rows

    def scalar_one_or_none(self) -> object | None:
        return self._rows[0] if self._rows else None


def _make_job(
    *,
    delegation_depth: int = 0,
    agent_type: object | None = None,
) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(),
        agent_type_id=uuid.uuid4(),
        triggered_by_user_id=None,
        input_data={"query": "run"},
        status=SimpleNamespace(value="running"),
        started_at=now,
        completed_at=None,
        output_data=None,
        error_message=None,
        stop_category=None,
        stop_reason=None,
        stop_details=None,
        conversation_history=None,
        created_at=now,
        delegation_depth=delegation_depth,
        agent_type=agent_type,
        parent_job_id=None,
    )


def _make_agent_type(max_delegation_depth: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="delegating-agent",
        guardrail_max_delegation_depth=max_delegation_depth,
    )


def _db_with_results(*results: _FakeResult) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(results))
    return db


# ── Internal session payload ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_internal_session_payload_exposes_persisted_delegation_depth() -> None:
    job = _make_job(delegation_depth=2)
    db = AsyncMock()
    db.get = AsyncMock(return_value=job)

    payload = await get_session(job.id, db)

    assert payload.delegation_depth == 2
    # Additive field: every existing field is still present.
    assert payload.id == job.id
    assert payload.input_data == {"query": "run"}


@pytest.mark.asyncio
async def test_internal_session_payload_delegation_depth_is_required_integer() -> None:
    """A construction site that omits the field is rejected (no silent default)."""
    from pydantic import ValidationError

    from app.api.v1.internal.session_data import SessionResponse

    with pytest.raises(ValidationError):
        SessionResponse(  # type: ignore[call-arg]
            id=uuid.uuid4(),
            agent_type_id=uuid.uuid4(),
            triggered_by_user_id=None,
            input_data=None,
            status="running",
            started_at=None,
            completed_at=None,
            output_data=None,
            error_message=None,
            stop_category=None,
            stop_reason=None,
            stop_details=None,
            conversation_history=None,
            created_at=datetime.now(timezone.utc),
        )


@pytest.mark.asyncio
async def test_root_session_payload_reports_zero_depth() -> None:
    job = _make_job(delegation_depth=0)
    db = AsyncMock()
    db.get = AsyncMock(return_value=job)

    payload = await get_session(job.id, db)

    assert payload.delegation_depth == 0


# ── Delegation status: configured maximum ────────────────────────────────────


@pytest.mark.asyncio
async def test_delegation_status_reports_configured_maximum_depth() -> None:
    job = _make_job(agent_type=_make_agent_type(3))
    db = _db_with_results(_FakeResult([]), _FakeResult([]))

    with patch(
        "app.api.v1.agents._session_service.get_session",
        AsyncMock(return_value=job),
    ):
        response = await get_delegation_status(job.id, db, {})

    assert response.max_depth == 3


@pytest.mark.asyncio
async def test_delegation_status_differs_per_agent_type_configuration() -> None:
    """Two agent types configured differently report different maximums."""
    first_job = _make_job(agent_type=_make_agent_type(3))
    second_job = _make_job(agent_type=_make_agent_type(7))

    with patch(
        "app.api.v1.agents._session_service.get_session",
        AsyncMock(return_value=first_job),
    ):
        first = await get_delegation_status(
            first_job.id, _db_with_results(_FakeResult([]), _FakeResult([])), {}
        )
    with patch(
        "app.api.v1.agents._session_service.get_session",
        AsyncMock(return_value=second_job),
    ):
        second = await get_delegation_status(
            second_job.id, _db_with_results(_FakeResult([]), _FakeResult([])), {}
        )

    assert first.max_depth == 3
    assert second.max_depth == 7
    assert first.max_depth != second.max_depth


@pytest.mark.asyncio
async def test_delegation_status_falls_back_to_platform_default_not_one() -> None:
    job = _make_job(agent_type=None)
    db = _db_with_results(_FakeResult([]), _FakeResult([]))

    with patch(
        "app.api.v1.agents._session_service.get_session",
        AsyncMock(return_value=job),
    ):
        response = await get_delegation_status(job.id, db, {})

    assert response.max_depth == PLATFORM_DEFAULT_MAX_DELEGATION_DEPTH
    assert response.max_depth != 1 or PLATFORM_DEFAULT_MAX_DELEGATION_DEPTH == 1


@pytest.mark.asyncio
async def test_delegation_status_shape_is_unchanged() -> None:
    job = _make_job(agent_type=_make_agent_type(5))
    db = _db_with_results(_FakeResult([]), _FakeResult([]))

    with patch(
        "app.api.v1.agents._session_service.get_session",
        AsyncMock(return_value=job),
    ):
        response = await get_delegation_status(job.id, db, {})

    assert set(response.model_dump().keys()) == {
        "has_active_delegation",
        "current_depth",
        "max_depth",
        "active_sub_agent_slug",
        "recent_events",
    }


# ── Pending intervention scope (direct children only) ────────────────────────


@pytest.mark.asyncio
async def test_pending_intervention_query_is_direct_child_scoped() -> None:
    job = _make_job()
    captured: list[object] = []

    async def execute(stmt: object) -> _FakeResult:
        captured.append(stmt)
        if len(captured) == 1:
            # Child-session lookup returns one direct child id.
            return _FakeResult([(uuid.uuid4(),)])
        # No pending intervene request for that child.
        return _FakeResult([])

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute)

    with patch(
        "app.api.v1.agents._session_service.get_session",
        AsyncMock(return_value=job),
    ):
        response = await get_pending_intervention(job.id, db, {})

    assert response is None
    assert len(captured) == 2

    child_sql = str(captured[0].compile(compile_kwargs={"literal_binds": False}))  # type: ignore[attr-defined]
    assert "agent_jobs.parent_job_id" in child_sql
    # No recursive CTE / descendant traversal, and no self-join tree walk.
    assert "RECURSIVE" not in child_sql.upper()
    assert "JOIN" not in child_sql.upper()
