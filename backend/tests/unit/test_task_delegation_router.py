"""Unit tests for TaskDelegationEventRouter.

Tests the Communication Hub's task delegation event router which
routes non-conversational delegation status events and intervention
requests to execution log viewer clients.

Covers: register/unregister, push_event, push_intervene_request,
viewer connection tracking, fallback when no viewer connected.
"""

from unittest.mock import AsyncMock

import pytest

from app.communication_hub.services.task_delegation_router import (
    TaskDelegationEventRouter,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def data_client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def router(data_client: AsyncMock) -> TaskDelegationEventRouter:
    return TaskDelegationEventRouter(data_client=data_client)


# ── Tests: Viewer registry ────────────────────────────────────────────────────


class TestViewerRegistry:
    """Verify viewer registration, unregistration, and connection tracking."""

    def test_register_viewer_adds_to_set(self, router: TaskDelegationEventRouter) -> None:
        """Registering a viewer adds them to the agent job's viewer set."""
        router.register_viewer("job-1", "channel-a")
        assert router.is_viewer_connected("job-1") is True
        assert router.viewer_count("job-1") == 1

    def test_register_multiple_viewers(self, router: TaskDelegationEventRouter) -> None:
        """Multiple viewers can be registered for the same agent job."""
        router.register_viewer("job-1", "channel-a")
        router.register_viewer("job-1", "channel-b")
        router.register_viewer("job-1", "channel-c")
        assert router.viewer_count("job-1") == 3

    def test_unregister_viewer_removes_single(self, router: TaskDelegationEventRouter) -> None:
        """Unregistering a viewer removes only that channel."""
        router.register_viewer("job-1", "channel-a")
        router.register_viewer("job-1", "channel-b")
        router.unregister_viewer("job-1", "channel-a")
        assert router.viewer_count("job-1") == 1
        assert router.is_viewer_connected("job-1") is True

    def test_unregister_last_viewer_removes_entry(self, router: TaskDelegationEventRouter) -> None:
        """Unregistering the last viewer removes the entry entirely."""
        router.register_viewer("job-1", "channel-a")
        router.unregister_viewer("job-1", "channel-a")
        assert router.is_viewer_connected("job-1") is False
        assert router.viewer_count("job-1") == 0

    def test_unregister_nonexistent_viewer_no_error(
        self, router: TaskDelegationEventRouter
    ) -> None:
        """Unregistering a channel that doesn't exist should not raise."""
        router.register_viewer("job-1", "channel-a")
        router.unregister_viewer("job-1", "nonexistent")  # Should not raise

    def test_unregister_nonexistent_job_no_error(
        self, router: TaskDelegationEventRouter
    ) -> None:
        """Unregistering from a job that doesn't exist should not raise."""
        router.unregister_viewer("no-such-job", "channel-a")  # Should not raise

    def test_is_viewer_connected_for_unregistered_job(
        self, router: TaskDelegationEventRouter
    ) -> None:
        """is_viewer_connected returns False for unregistered jobs."""
        assert router.is_viewer_connected("no-such-job") is False

    def test_viewer_count_for_unregistered_job(
        self, router: TaskDelegationEventRouter
    ) -> None:
        """viewer_count returns 0 for unregistered jobs."""
        assert router.viewer_count("no-such-job") == 0

    def test_duplicate_registration_idempotent(
        self, router: TaskDelegationEventRouter
    ) -> None:
        """Registering the same channel twice is idempotent (set)."""
        router.register_viewer("job-1", "channel-a")
        router.register_viewer("job-1", "channel-a")
        assert router.viewer_count("job-1") == 1


# ── Tests: Push event ─────────────────────────────────────────────────────────


class TestPushEvent:
    """Verify push_event persists delegation events via data_client."""

    @pytest.mark.asyncio
    async def test_push_event_persists_via_data_client(
        self, router: TaskDelegationEventRouter, data_client: AsyncMock
    ) -> None:
        """push_event calls data_client.log_execution_event."""
        await router.push_event(
            agent_job_id="job-1",
            event_type="delegation_started",
            message="Delegating to sub-agent",
            data={"delegation_target": "sub-qa", "delegation_depth": 1},
        )
        data_client.log_execution_event.assert_awaited_once_with(
            session_id="job-1",
            event_type="delegation_started",
            message="Delegating to sub-agent",
            data={"delegation_target": "sub-qa", "delegation_depth": 1},
            log_level="INFO",
        )

    @pytest.mark.asyncio
    async def test_push_event_all_types(
        self, router: TaskDelegationEventRouter, data_client: AsyncMock
    ) -> None:
        """All delegation event types can be pushed."""
        event_types = [
            "delegation_started",
            "delegation_waiting",
            "delegation_resumed",
            "delegation_depth_blocked",
            "delegation_timeout",
            "delegation_failed",
        ]
        for et in event_types:
            await router.push_event(
                agent_job_id="job-1",
                event_type=et,
                message=f"Event {et}",
                data={"type": et},
            )
        assert data_client.log_execution_event.await_count == len(event_types)

    @pytest.mark.asyncio
    async def test_push_event_with_no_data_client_logs_warning(
        self, data_client: AsyncMock
    ) -> None:
        """When no data_client is configured, a warning is logged (no error)."""
        router_no_client = TaskDelegationEventRouter(data_client=None)
        # Should not raise
        await router_no_client.push_event(
            agent_job_id="job-1",
            event_type="delegation_started",
            message="test",
        )
        # data_client should NOT have been called
        data_client.log_execution_event.assert_not_called()


# ── Tests: Push intervene request ─────────────────────────────────────────────


class TestPushInterveneRequest:
    """Verify push_intervene_request routes HITL requests through event system."""

    @pytest.mark.asyncio
    async def test_push_intervene_request_persists_event(
        self, router: TaskDelegationEventRouter, data_client: AsyncMock
    ) -> None:
        """push_intervene_request persists a human_intervene log event."""
        await router.push_intervene_request(
            agent_job_id="job-1",
            payload={
                "request_id": "req-123",
                "intervention_type": "approval",
                "reason": "Approve this action",
                "agent_type": "sub-qa-agent",
                "delegation_depth": 1,
            },
        )
        # Verify the event was logged as human_intervene
        data_client.log_execution_event.assert_awaited_once()
        call_kwargs = data_client.log_execution_event.call_args.kwargs
        assert call_kwargs["event_type"] == "human_intervene"
        assert "request_id" in call_kwargs["data"]
        assert call_kwargs["data"]["intervention_type"] == "approval"

    @pytest.mark.asyncio
    async def test_push_intervene_request_contains_delegation_context(
        self, router: TaskDelegationEventRouter, data_client: AsyncMock
    ) -> None:
        """The intervention payload includes delegation context."""
        await router.push_intervene_request(
            agent_job_id="job-1",
            payload={
                "request_id": "req-456",
                "intervention_type": "choice",
                "reason": "Select option",
                "choices": ["A", "B", "C"],
                "agent_type": "review-agent",
                "delegation_depth": 1,
            },
        )
        call_kwargs = data_client.log_execution_event.call_args.kwargs
        data = call_kwargs["data"]
        assert data["sub_agent_type"] == "review-agent"
        assert data["choices"] == ["A", "B", "C"]
        assert data["delegation_depth"] == 1

    @pytest.mark.asyncio
    async def test_push_intervene_request_without_data_client(
        self, data_client: AsyncMock
    ) -> None:
        """No error when pushing intervene without data client."""
        router_no_client = TaskDelegationEventRouter(data_client=None)
        await router_no_client.push_intervene_request(
            agent_job_id="job-1",
            payload={"request_id": "req-789", "intervention_type": "text"},
        )
        data_client.log_execution_event.assert_not_called()
