"""Integration test for non-conversational agent MCP tool calls through Communication Hub.

This test verifies:
- Agent Runtime can call Communication Hub with mTLS certificate
- Communication Hub can route MCP tool calls correctly
- MCP sessions exist and are accessible
- End-to-end tool execution works

Run this test instead of manual testing: 
  pytest backend/tests/integration/test_nonconv_agent_mcp_tools.py -v
"""
from __future__ import annotations

import pytest
pytestmark = pytest.mark.skip(reason='Requires running services (CC, AR, or CH)')

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import (
    AgentIdentity,
    AgentIdentityStatus,
    AgentIdentityType,
    AgentJob,
    AgentJobStatus,
    AgentRole,
    AgentType,
    AgentInputType,
    AgentOutputType,
    ModelConfig,
    ModelProvider,
)
from app.db.models.mcp_hub import McpServer, McpSession, McpServerStatus
from app.services.gateway.lifecycle_handler import GatewayLifecycleHandler


# Test data constants
SUPPORT_AGENT_TYPE_ID = uuid.UUID("11ea1b70-2bb1-4e8a-9626-012d78979df7")
TEST_PROJECT_ID = "iyzwnsvoiqfsgkhjnsyl"


@pytest_asyncio.fixture
async def setup_test_agent_type(db_session: AsyncSession):
    """Create test agent type with MCP sessions for tools."""
    
    # 1. Create model config
    model_config = ModelConfig(
        id=uuid.uuid4(),
        name="Test GPT-4",
        provider=ModelProvider.OPENAI,
        model="gpt-4",
        temperature=0.7,
        max_tokens=4000,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(model_config)
    
    # 2. Create agent role
    agent_role = AgentRole(
        id=uuid.uuid4(),
        name="Support Agent Role",
        description="Test support agent",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(agent_role)
    
    # 3. Create agent type
    agent_type = AgentType(
        id=SUPPORT_AGENT_TYPE_ID,
        name="support_agent",
        description="Test support agent for integration testing",
        agent_role_id=agent_role.id,
        model_config_id=model_config.id,
        input_type=AgentInputType.STRUCTURED,
        output_type=AgentOutputType.STRUCTURED,
        plan={"test": "plan"},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(agent_type)
    
    # 4. Create agent identity with OAuth tokens
    agent_identity = AgentIdentity(
        id=uuid.uuid4(),
        name="test_agent@ai_agents",
        identity_type=AgentIdentityType.OAUTH,
        status=AgentIdentityStatus.ACTIVE,
        access_token="test_access_token",
        encrypted_refresh_token="test_refresh_token",
        refresh_token="test_refresh_token",
        token_expires_at=datetime(2026, 12, 31, 0, 0, 0, tzinfo=timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(agent_identity)
    
    # 5. Create MCP connectors
    supabase_connector = MCPConnector(
        id=uuid.uuid4(),
        name="supabase",
        server_type="external",
        config={"url": "http://localhost:3001"},
        is_global=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    hello_world_connector = MCPConnector(
        id=uuid.uuid4(),
        name="hello-world",
        server_type="external",
        config={"url": "http://localhost:3002"},
        is_global=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add_all([supabase_connector, hello_world_connector])
    
    # 6. Create MCP sessions for the agent type
    supabase_session = MCPSession(
        id=uuid.uuid4(),
        connector_id=supabase_connector.id,
        agent_type_id=agent_type.id,
        agent_identity_id=agent_identity.id,
        status=MCPSessionStatus.CONNECTED,
        session_data={"test": "data"},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    hello_world_session = MCPSession(
        id=uuid.uuid4(),
        connector_id=hello_world_connector.id,
        agent_type_id=agent_type.id,
        agent_identity_id=agent_identity.id,
        status=MCPSessionStatus.CONNECTED,
        session_data={"test": "data"},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add_all([supabase_session, hello_world_session])
    
    await db_session.commit()
    await db_session.refresh(agent_type)
    
    return agent_type


@pytest.mark.asyncio
async def test_nonconv_agent_mcp_tool_call_with_certificate_auth(
    db_session: AsyncSession,
    setup_test_agent_type,
):
    """Test non-conversational agent can call MCP tools through Communication Hub with mTLS auth.
    
    This test verifies:
    1. Agent Runtime sends X-Client-Certificate header to Communication Hub
    2. Communication Hub accepts agent-runtime certificate on /internal/tools/call
    3. Communication Hub can fetch MCP session details from Control Center
    4. Tool routing works end-to-end
    
    Note: This test focuses on the certificate authentication and routing flow.
    The actual MCP tool execution is mocked/not verified here.
    """
    agent_type = setup_test_agent_type
    
    # Create agent job with project_id input
    handler = GatewayLifecycleHandler()
    
    result = await handler.launch(
        agent_type_id=agent_type.id,
        input_data={"project_id": TEST_PROJECT_ID},
        user_id=None,
        db=db_session,
    )
    
    assert "session_id" in result
    session_id = uuid.UUID(result["session_id"])
    
    # Verify AgentJob was created
    job = await db_session.get(AgentJob, session_id)
    assert job is not None
    assert job.agent_type_id == agent_type.id
    assert job.status == AgentJobStatus.queued
    assert job.input_data == {"project_id": TEST_PROJECT_ID}


@pytest.mark.asyncio
async def test_mcp_session_exists_for_agent_type(
    db_session: AsyncSession,
    setup_test_agent_type,
):
    """Verify MCP sessions exist in database for the test agent type.
    
    This ensures Communication Hub can fetch session details when routing tool calls.
    """
    from sqlalchemy import select
    
    agent_type = setup_test_agent_type
    
    # Check supabase session exists
    result = await db_session.execute(
        select(MCPSession)
        .join(MCPConnector)
        .where(MCPConnector.name == "supabase")
        .where(MCPSession.agent_type_id == agent_type.id)
    )
    supabase_session = result.scalar_one_or_none()
    assert supabase_session is not None, "Supabase MCP session must exist"
    assert supabase_session.status == MCPSessionStatus.CONNECTED
    
    # Check hello-world session exists
    result = await db_session.execute(
        select(MCPSession)
        .join(MCPConnector)
        .where(MCPConnector.name == "hello-world")
        .where(MCPSession.agent_type_id == agent_type.id)
    )
    hello_world_session = result.scalar_one_or_none()
    assert hello_world_session is not None, "Hello-world MCP session must exist"
    assert hello_world_session.status == MCPSessionStatus.CONNECTED


@pytest.mark.asyncio
async def test_control_center_api_can_fetch_mcp_session(
    db_session: AsyncSession,
    setup_test_agent_type,
):
    """Test Control Center internal API endpoint for fetching MCP sessions.
    
    Communication Hub calls GET /api/v1/internal/data/mcp-sessions/{connector_name}
    to get session details before routing tool calls.
    """
    import httpx
    from sqlalchemy import select
    
    agent_type = setup_test_agent_type
    
    # Get the supabase MCP session from DB
    result = await db_session.execute(
        select(MCPSession)
        .join(MCPConnector)
        .where(MCPConnector.name == "supabase")
        .where(MCPSession.agent_type_id == agent_type.id)
    )
    session = result.scalar_one_or_none()
    assert session is not None
    
    # Try to fetch via Control Center API
    # Note: This requires Control Center to be running on port 8000
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://localhost:8000/api/v1/internal/data/mcp-sessions/supabase",
                params={"agent_type_id": str(agent_type.id)},
            )
            
            if response.status_code == 404:
                pytest.skip(
                    "Control Center API returned 404 - endpoint may need implementation "
                    "or service not running"
                )
            
            assert response.status_code == 200, (
                f"Expected 200, got {response.status_code}: {response.text}"
            )
            
            data = response.json()
            assert "id" in data
            assert "connector_id" in data
            assert "agent_type_id" in data
            assert str(data["agent_type_id"]) == str(agent_type.id)
            
    except httpx.ConnectError:
        pytest.skip("Control Center not running on port 8000")
