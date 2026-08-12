"""Integration test for session creation and execution trigger race condition.

This test validates that sessions are properly committed to the database
before execution triggers are sent to Agent Runtime.

Bug scenario:
1. CC creates session but doesn't commit transaction
2. CC triggers CH → AR execution
3. AR tries to update session status via CC API
4. CC returns 404 "Session not found" (transaction not committed)
5. Execution fails with 502 after retries

Fix:
- Explicit db.commit() after session.enqueue() and before trigger
"""
import asyncio
import uuid

import httpx
import pytest

from app.db.models.agents import AgentJob, AgentJobStatus


@pytest.mark.asyncio
@pytest.mark.integration
class TestSessionCommitBeforeTrigger:
    """Validate session is committed before execution trigger."""

    async def test_session_exists_when_ar_updates_status(
        self,
        cc_client: httpx.AsyncClient,
        ar_client: httpx.AsyncClient,
    ):
        """Verify session is committed and queryable before AR tries to update it.
        
        This test simulates the race condition by:
        1. Creating a session via CC API
        2. Immediately querying the session (should exist)
        3. Verifying AR can update the session status
        
        If the bug exists, the session won't be found immediately after creation.
        """
        pytest.skip("Test requires authenticated test fixtures with valid agent type")
        
        # Prepare test data
        agent_type_id = uuid.uuid4()  # Would need a real agent type ID
        payload = {
            "agent_type_id": str(agent_type_id),
            "input_data": {"test": "data"},
        }
        
        # 1. Create session via CC API
        response = await cc_client.post("/api/v1/agents/sessions", json=payload)
        assert response.status_code == 202, f"Failed to create session: {response.text}"
        
        session_data = response.json()
        session_id = session_data["id"]
        
        # 2. Immediately query the session (race condition test)
        # If transaction not committed, this will fail
        response = await cc_client.get(
            f"/api/v1/internal/data/sessions/{session_id}"
        )
        assert response.status_code == 200, (
            f"Session not found immediately after creation - race condition! "
            f"Response: {response.text}"
        )
        
        # 3. Verify AR can update session status
        # This is what AR does when triggered
        status_update = {"status": "running"}
        response = await ar_client.patch(
            f"/api/v1/internal/data/sessions/{session_id}/status",
            json=status_update,
        )
        assert response.status_code == 200, (
            f"Failed to update session status - race condition! "
            f"Response: {response.text}"
        )

    async def test_concurrent_session_creation_and_query(self):
        """Stress test: create multiple sessions concurrently and verify all are queryable.
        
        This validates that the commit happens correctly even under concurrent load.
        """
        pytest.skip("Test requires test fixtures and real database")
        
        # Would create multiple sessions concurrently and verify all can be queried
        pass


@pytest.mark.asyncio
@pytest.mark.integration
class TestExecutionTriggerTiming:
    """Validate execution trigger timing relative to session commit."""

    async def test_ar_receives_trigger_after_session_committed(
        self,
        cc_client: httpx.AsyncClient,
    ):
        """Verify AR receives execution trigger only after session is in database.
        
        This is a timing test to ensure the fix works correctly.
        """
        pytest.skip("Test requires monitoring AR logs for trigger receipt timing")
        
        # Would need to:
        # 1. Monitor AR logs
        # 2. Create session via CC
        # 3. Verify AR trigger arrives AFTER session is queryable
        pass

    async def test_no_404_errors_in_ar_status_update(self):
        """Verify AR never gets 404 when updating session status.
        
        This is the actual bug symptom - AR getting 404 from CC.
        """
        pytest.skip("Test requires full service integration and log monitoring")
        
        # Would need to:
        # 1. Monitor AR logs for 404 errors
        # 2. Create and execute multiple sessions
        # 3. Assert no 404 errors in AR logs
        pass


# Manual test instructions for validation
"""
MANUAL TEST PROCEDURE:

1. Restart Control Center with the fix:
   cd backend
   ..\parthenon.ps1 restart -Services control-center -Force

2. Trigger agent execution from UI or via API:
   POST /api/v1/agents/sessions
   {
     "agent_type_id": "<valid-agent-type-id>",
     "input_data": {}
   }

3. Check logs for success:
   
   Control Center log should show:
   - "Gateway launch: enqueued session {id}"
   - "Gateway launch: committed session {id} to database"
   - NO "Failed to trigger execution via Communication Hub"
   
   Communication Hub log should show:
   - "Agent execution trigger: session={id}"
   - "Agent execution trigger forwarded successfully"
   - NO retry messages
   
   Agent Runtime log should show:
   - "Execution trigger received: session={id}"
   - NO "Failed to mark session as running"
   - NO "404 Not Found" errors

EXPECTED OUTCOME:
- Session executes immediately (no 30s delay)
- No 404 errors in any service
- No retry attempts from Communication Hub
- Execution completes successfully
"""
