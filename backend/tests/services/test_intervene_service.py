"""Unit tests for InterveneRequestStore service layer.

Tests business logic, state transitions, and error handling with mocked DB.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.intervene import (
    InterveneRequest,
    InterveneRequestStatus,
    InterveneResponse,
    InterventionType,
)
from app.services.agents.intervene_service import InterveneRequestStore


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def store() -> InterveneRequestStore:
    return InterveneRequestStore()


def _mock_db() -> AsyncMock:
    """Create a mocked AsyncSession with pre-configured execute chain.

    The execute return value is a MagicMock so that:
      result.scalar_one_or_none()         ← synchronous, returns MagicMock.return_value
      result.scalars().all()              ← synchronous, returns MagicMock.return_value

    This matches the service code which does NOT await .scalar_one_or_none() or .scalars().
    """
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    # Build the chain: execute → result → scalars → all
    scalars_result = MagicMock()
    scalars_result.all = MagicMock(return_value=[])

    execute_result = MagicMock()
    execute_result.scalars = MagicMock(return_value=scalars_result)
    execute_result.scalar_one_or_none = MagicMock(return_value=None)

    db.execute = AsyncMock(return_value=execute_result)

    # get() is an async method on AsyncSession — AsyncMock handles await correctly
    db.get = AsyncMock(return_value=None)

    return db


def _set_pending_check(db, existing: InterveneRequest | None):
    """Configure db.execute to return `existing` for the pending-request check."""
    db.execute.return_value.scalar_one_or_none = MagicMock(return_value=existing)


def _set_find_result(db, results: list[InterveneRequest]):
    """Configure db.execute to return `results` for list/find queries."""
    scalars_result = MagicMock()
    scalars_result.all = MagicMock(return_value=results)
    db.execute.return_value.scalars = MagicMock(return_value=scalars_result)


def _make_request(
    *,
    request_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    type_id: uuid.UUID | None = None,
    intervention_type: InterventionType = InterventionType.approval,
    status: InterveneRequestStatus = InterveneRequestStatus.pending,
    reason: str = "Test reason",
    choices: list[str] | None = None,
) -> InterveneRequest:
    request = InterveneRequest(
        id=request_id or uuid.uuid4(),
        agent_session_id=session_id or uuid.uuid4(),
        agent_type_id=type_id or uuid.uuid4(),
        intervention_type=intervention_type,
        reason=reason,
        choices=choices,
        status=status,
        created_at=datetime.now(timezone.utc),
        responded_at=None,
        expires_at=None,
    )
    request.response = None
    return request


# ── create_request ──────────────────────────────────────────────────────────

class TestCreateRequest:
    """Tests for InterveneRequestStore.create_request()."""

    @pytest.mark.asyncio
    async def test_create_approval_request(self, store):
        db = _mock_db()
        _set_pending_check(db, None)

        await store.create_request(
            db=db,
            agent_session_id=uuid.uuid4(),
            agent_type_id=uuid.uuid4(),
            intervention_type=InterventionType.approval,
            reason="Approve this action?",
        )

        db.add.assert_called_once()
        args = db.add.call_args[0][0]
        assert args.intervention_type == InterventionType.approval
        assert args.reason == "Approve this action?"
        assert args.status == InterveneRequestStatus.pending
        assert args.choices is None
        db.flush.assert_awaited_once()
        db.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_choice_request_with_choices(self, store):
        db = _mock_db()
        _set_pending_check(db, None)

        choices = ["Option A", "Option B", "Option C"]
        await store.create_request(
            db=db,
            agent_session_id=uuid.uuid4(),
            agent_type_id=uuid.uuid4(),
            intervention_type=InterventionType.choice,
            reason="Which option?",
            choices=choices,
        )

        assert db.add.call_args[0][0].choices == choices
        assert db.add.call_args[0][0].intervention_type == InterventionType.choice

    @pytest.mark.asyncio
    async def test_create_text_request(self, store):
        db = _mock_db()
        _set_pending_check(db, None)

        await store.create_request(
            db=db,
            agent_session_id=uuid.uuid4(),
            agent_type_id=uuid.uuid4(),
            intervention_type=InterventionType.text,
            reason="Please provide input:",
        )

        assert db.add.call_args[0][0].intervention_type == InterventionType.text
        assert db.add.call_args[0][0].reason == "Please provide input:"

    @pytest.mark.asyncio
    async def test_duplicate_pending_request_raises_error(self, store):
        db = _mock_db()
        session_id = uuid.uuid4()
        existing = _make_request(session_id=session_id)
        _set_pending_check(db, existing)

        with pytest.raises(ValueError, match="already has a pending"):
            await store.create_request(
                db=db,
                agent_session_id=session_id,
                agent_type_id=uuid.uuid4(),
                intervention_type=InterventionType.approval,
                reason="Duplicate?",
            )

        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_duplicate_allowed_if_previous_responded(self, store):
        """Creating a new request succeeds when no *pending* request exists for the session."""
        db = _mock_db()
        _set_pending_check(db, None)

        await store.create_request(
            db=db,
            agent_session_id=uuid.uuid4(),
            agent_type_id=uuid.uuid4(),
            intervention_type=InterventionType.approval,
            reason="Second request",
        )

        db.add.assert_called_once()
        db.flush.assert_awaited_once()


# ── get_request ─────────────────────────────────────────────────────────────

class TestGetRequest:
    """Tests for InterveneRequestStore.get_request()."""

    @pytest.mark.asyncio
    async def test_get_existing_request(self, store):
        db = _mock_db()
        request_id = uuid.uuid4()
        expected = _make_request(request_id=request_id)
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=expected)

        result = await store.get_request(db=db, request_id=request_id)

        assert result is not None
        assert result.id == request_id
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_nonexistent_request(self, store):
        db = _mock_db()
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

        result = await store.get_request(db=db, request_id=uuid.uuid4())

        assert result is None


# ── list_requests ───────────────────────────────────────────────────────────

class TestListRequests:
    """Tests for InterveneRequestStore.list_requests()."""

    @pytest.mark.asyncio
    async def test_list_all_requests(self, store):
        db = _mock_db()
        _set_find_result(db, [_make_request(), _make_request()])

        results = await store.list_requests(db=db)

        assert len(results) == 2
        assert isinstance(results[0], InterveneRequest)

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self, store):
        db = _mock_db()
        pending = _make_request(status=InterveneRequestStatus.pending)
        _set_find_result(db, [pending])

        results = await store.list_requests(db=db, status=InterveneRequestStatus.pending)

        assert len(results) == 1
        assert results[0].status == InterveneRequestStatus.pending

    @pytest.mark.asyncio
    async def test_list_filter_by_intervention_type(self, store):
        db = _mock_db()
        approval = _make_request(intervention_type=InterventionType.approval)
        _set_find_result(db, [approval])

        results = await store.list_requests(db=db, intervention_type=InterventionType.approval)

        assert len(results) == 1
        assert results[0].intervention_type == InterventionType.approval

    @pytest.mark.asyncio
    async def test_list_filter_by_session_id(self, store):
        db = _mock_db()
        session_id = uuid.uuid4()
        req = _make_request(session_id=session_id)
        _set_find_result(db, [req])

        results = await store.list_requests(db=db, agent_session_id=session_id)

        assert len(results) == 1
        assert results[0].agent_session_id == session_id

    @pytest.mark.asyncio
    async def test_list_returns_empty_when_no_matches(self, store):
        db = _mock_db()
        _set_find_result(db, [])

        results = await store.list_requests(db=db, status=InterveneRequestStatus.responded)

        assert results == []

    @pytest.mark.asyncio
    async def test_list_respects_limit_and_offset(self, store):
        db = _mock_db()
        _set_find_result(db, [])

        results = await store.list_requests(db=db, limit=10, offset=5)

        assert results == []


# ── submit_response ─────────────────────────────────────────────────────────

class TestSubmitResponse:
    """Tests for InterveneRequestStore.submit_response()."""

    def _setup_db_with_request(
        self, db, req: InterveneRequest, job_status: str = "waiting_for_human"
    ):
        """Configure db.get to return the request and optionally an AgentJob."""
        mock_job = MagicMock()
        mock_job.id = req.agent_session_id
        mock_job.status = job_status

        async def _get_side_effect(model, pk):
            if model == InterveneRequest:
                return req
            return mock_job

        db.get = AsyncMock(side_effect=_get_side_effect)
        return mock_job

    @pytest.mark.asyncio
    async def test_submit_approval_true(self, store):
        db = _mock_db()
        request_id = uuid.uuid4()
        req = _make_request(
            request_id=request_id,
            intervention_type=InterventionType.approval,
            status=InterveneRequestStatus.pending,
        )
        job = self._setup_db_with_request(db, req)

        response = await store.submit_response(
            db=db,
            request_id=request_id,
            operator_user_id=uuid.uuid4(),
            approval_value=True,
        )

        assert response.approval_value is True
        assert req.status == InterveneRequestStatus.responded
        assert req.responded_at is not None
        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        db.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_submit_approval_false(self, store):
        db = _mock_db()
        request_id = uuid.uuid4()
        req = _make_request(request_id=request_id, status=InterveneRequestStatus.pending)
        self._setup_db_with_request(db, req)

        response = await store.submit_response(
            db=db,
            request_id=request_id,
            operator_user_id=uuid.uuid4(),
            approval_value=False,
        )

        assert response.approval_value is False

    @pytest.mark.asyncio
    async def test_submit_choice(self, store):
        db = _mock_db()
        request_id = uuid.uuid4()
        req = _make_request(
            request_id=request_id,
            intervention_type=InterventionType.choice,
            status=InterveneRequestStatus.pending,
            choices=["A", "B", "C"],
        )
        self._setup_db_with_request(db, req)

        response = await store.submit_response(
            db=db,
            request_id=request_id,
            operator_user_id=uuid.uuid4(),
            selected_choice="B",
        )

        assert response.selected_choice == "B"
        assert req.status == InterveneRequestStatus.responded

    @pytest.mark.asyncio
    async def test_submit_text(self, store):
        db = _mock_db()
        request_id = uuid.uuid4()
        req = _make_request(
            request_id=request_id,
            intervention_type=InterventionType.text,
            status=InterveneRequestStatus.pending,
        )
        self._setup_db_with_request(db, req)

        response = await store.submit_response(
            db=db,
            request_id=request_id,
            operator_user_id=uuid.uuid4(),
            text_value="This is my response text",
        )

        assert response.text_value == "This is my response text"
        assert req.status == InterveneRequestStatus.responded

    @pytest.mark.asyncio
    async def test_respond_to_non_pending_raises_error(self, store):
        db = _mock_db()
        request_id = uuid.uuid4()
        req = _make_request(request_id=request_id, status=InterveneRequestStatus.responded)
        db.get = AsyncMock(return_value=req)

        with pytest.raises(ValueError, match="Cannot respond to request"):
            await store.submit_response(
                db=db,
                request_id=request_id,
                operator_user_id=uuid.uuid4(),
                approval_value=True,
            )

    @pytest.mark.asyncio
    async def test_respond_to_cancelled_raises_error(self, store):
        db = _mock_db()
        request_id = uuid.uuid4()
        req = _make_request(request_id=request_id, status=InterveneRequestStatus.cancelled)
        db.get = AsyncMock(return_value=req)

        with pytest.raises(ValueError, match="Cannot respond to request"):
            await store.submit_response(
                db=db,
                request_id=request_id,
                operator_user_id=uuid.uuid4(),
                approval_value=True,
            )

    @pytest.mark.asyncio
    async def test_respond_to_expired_raises_error(self, store):
        db = _mock_db()
        request_id = uuid.uuid4()
        req = _make_request(request_id=request_id, status=InterveneRequestStatus.expired)
        db.get = AsyncMock(return_value=req)

        with pytest.raises(ValueError, match="Cannot respond to request"):
            await store.submit_response(
                db=db,
                request_id=request_id,
                operator_user_id=uuid.uuid4(),
                approval_value=True,
            )

    @pytest.mark.asyncio
    async def test_respond_to_nonexistent_raises_error(self, store):
        db = _mock_db()
        db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="not found"):
            await store.submit_response(
                db=db,
                request_id=uuid.uuid4(),
                operator_user_id=uuid.uuid4(),
                approval_value=True,
            )


# ── cancel_request ──────────────────────────────────────────────────────────

class TestCancelRequest:
    """Tests for InterveneRequestStore.cancel_request()."""

    @pytest.mark.asyncio
    async def test_cancel_pending_request(self, store):
        db = _mock_db()
        request_id = uuid.uuid4()
        req = _make_request(request_id=request_id, status=InterveneRequestStatus.pending)
        db.get = AsyncMock(return_value=req)

        result = await store.cancel_request(db=db, request_id=request_id)

        assert result.status == InterveneRequestStatus.cancelled
        db.flush.assert_awaited_once()
        db.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancel_non_pending_raises_error(self, store):
        db = _mock_db()
        request_id = uuid.uuid4()
        req = _make_request(request_id=request_id, status=InterveneRequestStatus.responded)
        db.get = AsyncMock(return_value=req)

        with pytest.raises(ValueError, match="Cannot cancel request"):
            await store.cancel_request(db=db, request_id=request_id)

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_raises_error(self, store):
        db = _mock_db()
        db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="not found"):
            await store.cancel_request(db=db, request_id=uuid.uuid4())


# ── get_metrics ─────────────────────────────────────────────────────────────

class TestGetMetrics:
    """Tests for InterveneRequestStore.get_metrics()."""

    def _configure_metrics(self, db, *, total, pending, resolved, avg_time):
        """Set up the four execute calls made by get_metrics()."""
        results = [
            MagicMock(scalar=MagicMock(return_value=total)),
            MagicMock(scalar=MagicMock(return_value=pending)),
            MagicMock(scalar=MagicMock(return_value=resolved)),
            MagicMock(scalar=MagicMock(return_value=avg_time)),
        ]
        db.execute.side_effect = [r for r in results]

    @pytest.mark.asyncio
    async def test_metrics_with_no_requests(self, store):
        db = _mock_db()
        self._configure_metrics(db, total=0, pending=0, resolved=0, avg_time=None)

        metrics = await store.get_metrics(db=db)

        assert metrics["pending_count"] == 0
        assert metrics["avg_response_time_seconds"] == 0.0
        assert metrics["resolution_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_metrics_with_one_pending(self, store):
        db = _mock_db()
        self._configure_metrics(db, total=1, pending=1, resolved=0, avg_time=None)

        metrics = await store.get_metrics(db=db)

        assert metrics["pending_count"] == 1
        assert metrics["resolution_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_metrics_with_resolved_requests(self, store):
        db = _mock_db()
        self._configure_metrics(db, total=2, pending=0, resolved=2, avg_time=45.0)

        metrics = await store.get_metrics(db=db)

        assert metrics["pending_count"] == 0
        assert metrics["avg_response_time_seconds"] == 45.0
        assert metrics["resolution_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_metrics_partial_resolution(self, store):
        db = _mock_db()
        self._configure_metrics(db, total=5, pending=3, resolved=2, avg_time=120.0)

        metrics = await store.get_metrics(db=db)

        assert metrics["pending_count"] == 3
        assert metrics["avg_response_time_seconds"] == 120.0
        assert metrics["resolution_rate"] == 0.4  # 2/5
