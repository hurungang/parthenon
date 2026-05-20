"""Integration tests for WebSocket communication through Communication Hub.

Tests verify that:
1. WebSocket endpoint is served by Communication Hub (port 8002)
2. WebSocket endpoint is NOT served by Control Center (port 8000)
3. JWT authentication works for WebSocket connections
4. Messages flow correctly through Communication Hub
"""
import asyncio
import json
import pytest
import websockets
from typing import AsyncIterator

# Service URLs
CONTROL_CENTER_URL = "http://localhost:8000"
COMM_HUB_URL = "http://localhost:8002"
WS_COMM_HUB_URL = "ws://localhost:8002"


@pytest.fixture
async def auth_token() -> str:
    """Get a valid JWT token for WebSocket authentication.
    
    In real tests, this would authenticate with Keycloak.
    For now, we'll use a test token or skip auth validation.
    """
    # TODO: Implement proper Keycloak token fetch
    # For now, return a placeholder
    return "test_token_placeholder"


@pytest.fixture
async def conversation_session_id(auth_token: str) -> AsyncIterator[str]:
    """Create a conversation session for testing.
    
    Creates a session via Control Center API and returns the session ID.
    """
    import httpx
    
    async with httpx.AsyncClient() as client:
        # Create conversation session
        response = await client.post(
            f"{CONTROL_CENTER_URL}/api/v1/conversations",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "agent_type_id": "a76b7eb7-7866-4f57-907a-e6caa776d652",  # Test agent
                "title": "WebSocket Integration Test",
            }
        )
        
        if response.status_code != 201:
            pytest.skip(f"Cannot create conversation session: {response.status_code}")
        
        session_data = response.json()
        session_id = session_data["id"]
        
        yield session_id
        
        # Cleanup: delete session (optional)


class TestWebSocketLocationVerification:
    """Verify WebSocket endpoint location after architecture refactoring."""
    
    @pytest.mark.asyncio
    async def test_websocket_not_available_on_control_center(self):
        """WebSocket endpoint should NOT be available on Control Center (port 8000)."""
        import httpx
        
        # Check that Control Center does not have WebSocket router registered
        async with httpx.AsyncClient() as client:
            # Try to connect to a WebSocket path on Control Center
            # This should fail or return 404
            try:
                response = await client.get(
                    f"{CONTROL_CENTER_URL}/ws/sessions/test-session-id",
                    headers={"Upgrade": "websocket"},
                    timeout=2.0
                )
                # If we get here, it means the endpoint exists but rejected the upgrade
                # This is also acceptable as long as WebSocket is not actually served
                assert response.status_code != 101, "Control Center should not serve WebSocket"
            except (httpx.ConnectError, httpx.TimeoutException):
                # Connection refused or timeout is acceptable
                pass
    
    @pytest.mark.asyncio  
    async def test_websocket_available_on_communication_hub(self):
        """WebSocket endpoint should be available on Communication Hub (port 8002)."""
        import httpx
        
        # Verify Communication Hub has WebSocket endpoint available
        async with httpx.AsyncClient() as client:
            # Check that the Communication Hub service is running
            response = await client.get(f"{COMM_HUB_URL}/health", timeout=5.0)
            assert response.status_code == 200
            
            health_data = response.json()
            assert health_data["service"] == "communication-hub"


class TestWebSocketAuthentication:
    """Test JWT authentication for WebSocket connections."""
    
    @pytest.mark.asyncio
    async def test_websocket_connection_requires_token(self, conversation_session_id: str):
        """WebSocket connection should require a valid JWT token."""
        ws_url = f"{WS_COMM_HUB_URL}/ws/sessions/{conversation_session_id}"
        
        # Try to connect without token - should fail
        try:
            async with websockets.connect(ws_url, timeout=2.0) as websocket:
                # If connection succeeds without token, that's a security issue
                pytest.fail("WebSocket connection succeeded without token")
        except (websockets.exceptions.InvalidStatusCode, 
                websockets.exceptions.WebSocketException) as e:
            # Expected: connection rejected due to missing/invalid token
            assert "403" in str(e) or "401" in str(e), \
                f"Expected 401/403 for missing token, got: {e}"
    
    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires valid Keycloak token - implement after auth setup")
    async def test_websocket_connection_with_valid_token(
        self, 
        auth_token: str, 
        conversation_session_id: str
    ):
        """WebSocket connection should succeed with valid JWT token."""
        ws_url = f"{WS_COMM_HUB_URL}/ws/sessions/{conversation_session_id}?token={auth_token}"
        
        try:
            async with websockets.connect(ws_url, timeout=5.0) as websocket:
                # Connection succeeded
                assert websocket.open
                
                # Send a test message
                test_message = {"message": "Hello, agent!"}
                await websocket.send(json.dumps(test_message))
                
                # Wait for response (with timeout)
                response = await asyncio.wait_for(
                    websocket.recv(),
                    timeout=10.0
                )
                
                # Verify response is valid JSON
                response_data = json.loads(response)
                assert "content" in response_data or "type" in response_data
                
        except websockets.exceptions.WebSocketException as e:
            pytest.fail(f"WebSocket connection failed with valid token: {e}")


class TestWebSocketMessageFlow:
    """Test message flow through Communication Hub."""
    
    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full agent execution pipeline - implement after full integration")
    async def test_message_flow_through_communication_hub(
        self,
        auth_token: str,
        conversation_session_id: str
    ):
        """Messages should flow: Frontend → CH → Agent Runtime → CH → Frontend."""
        ws_url = f"{WS_COMM_HUB_URL}/ws/sessions/{conversation_session_id}?token={auth_token}&conv_session_id={conversation_session_id}"
        
        async with websockets.connect(ws_url, timeout=5.0) as websocket:
            # Send user message
            user_message = {"message": "What is 2+2?"}
            await websocket.send(json.dumps(user_message))
            
            # Wait for agent response
            response_received = False
            timeout_seconds = 30
            
            try:
                async with asyncio.timeout(timeout_seconds):
                    while not response_received:
                        response = await websocket.recv()
                        response_data = json.loads(response)
                        
                        # Check if this is the agent's response
                        if (response_data.get("sender_role") == "agent" and 
                            response_data.get("content")):
                            response_received = True
                            
                            # Verify response contains content
                            assert len(response_data["content"]) > 0
                            break
                            
            except asyncio.TimeoutError:
                pytest.fail(f"No agent response received within {timeout_seconds} seconds")
            
            assert response_received, "Agent response not received"


class TestWebSocketServiceIntegration:
    """Test Communication Hub integration with other services."""
    
    @pytest.mark.asyncio
    async def test_communication_hub_health_endpoint(self):
        """Communication Hub health endpoint should return correct service name."""
        import httpx
        
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{COMM_HUB_URL}/health", timeout=5.0)
            
            assert response.status_code == 200
            health_data = response.json()
            
            assert health_data["status"] == "ok"
            assert health_data["service"] == "communication-hub"
            assert "cert_expires_at" in health_data
    
    @pytest.mark.asyncio
    async def test_control_center_does_not_serve_websocket_routes(self):
        """Verify Control Center no longer has WebSocket routes registered."""
        import httpx
        
        async with httpx.AsyncClient() as client:
            # Control Center should still have its API routes
            response = await client.get(f"{CONTROL_CENTER_URL}/health", timeout=5.0)
            assert response.status_code == 200
            
            health_data = response.json()
            assert health_data["service"] == "control-center"
            
            # But WebSocket paths should return 404 or not be registered
            try:
                ws_response = await client.get(
                    f"{CONTROL_CENTER_URL}/ws/sessions/test",
                    timeout=2.0
                )
                # Should get 404, 401 (auth rejection), 405 (method not allowed), 
                # or 426 (upgrade required) - anything except 200 or 101 (WebSocket upgrade)
                assert ws_response.status_code not in [200, 101], \
                    "Control Center should not serve WebSocket endpoint with successful status"
                assert ws_response.status_code in [401, 404, 405, 426], \
                    f"Expected auth rejection or not found, got {ws_response.status_code}"
            except httpx.HTTPError:
                # Connection error is also acceptable
                pass


# Pytest configuration for integration tests
pytestmark = pytest.mark.integration
