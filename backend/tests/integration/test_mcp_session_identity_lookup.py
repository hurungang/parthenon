"""Integration test for MCP session identity lookup fix."""
import pytest
import uuid
from pathlib import Path

pytestmark = pytest.mark.asyncio


async def test_mcp_session_endpoint_with_role(
    db_session,
):
    """Test that MCP session endpoint correctly looks up role-based MCP sessions.
    
    MCP sessions are associated with Agent Roles, not users. This tests that
    the endpoint correctly follows: AgentJob → AgentType → AgentRole → McpSession
    
    Flow:
    1. Create an agent role
    2. Create an agent type linked to that role
    3. Create an agent job (session) for that agent type
    4. Create MCP server and session linked to the role
    5. Call the endpoint and verify it returns the role's MCP credentials
    """
    from app.db.models.agents import AgentJob, AgentJobStatus, AgentType, AgentRole, AgentRoleMcpSession
    from app.db.models.mcp_hub import McpServer, McpSession, McpSessionAuthType
    from app.api.v1.internal.agent_data import get_mcp_session_for_tool_routing
    from app.core.credential_vault import get_vault
    import json
    
    # 1. Create an agent role
    agent_role = AgentRole(
        name="Test Role",
        description="Test role for MCP session lookup",
    )
    db_session.add(agent_role)
    await db_session.flush()
    
    # 2. Create an agent type linked to the role
    agent_type = AgentType(
        name="Test Agent",
        description="Test agent for MCP session lookup",
        system_instruction="Test instruction",
        role_id=agent_role.id,  # Link to role
        is_active=True,
    )
    db_session.add(agent_type)
    await db_session.flush()
    
    db_session.add(agent_type)
    await db_session.flush()
    
    # 3. Create an agent job (session) for this agent type
    session_id = uuid.uuid4()
    agent_job = AgentJob(
        id=session_id,
        agent_type_id=agent_type.id,
        triggered_by_user_id=None,  # Can be null - MCP uses role, not user
        status=AgentJobStatus.queued,
    )
    db_session.add(agent_job)
    await db_session.flush()
    
    # 4. Create MCP server
    server = McpServer(
        name="test-server",
        slug="test-server",
        base_url="http://localhost:9999/mcp",
    )
    db_session.add(server)
    await db_session.flush()
    
    # 5. Create MCP session with credentials
    vault = get_vault()
    test_credentials = {"api_key": "test-api-key-123"}
    encrypted_creds = vault.encrypt(json.dumps(test_credentials))
    
    mcp_session = McpSession(
        server_id=server.id,
        name="test-role-session",
        auth_type=McpSessionAuthType.api_key,
        encrypted_credentials=encrypted_creds,
        is_active=True,
    )
    db_session.add(mcp_session)
    await db_session.flush()
    
    # 6. Link the MCP session to the role
    role_mcp_link = AgentRoleMcpSession(
        role_id=agent_role.id,
        mcp_session_id=mcp_session.id,
        server_id=server.id,
    )
    db_session.add(role_mcp_link)
    await db_session.commit()
    
    # 7. Call the endpoint function directly (as Communication Hub would via API)
    result = await get_mcp_session_for_tool_routing(
        server_slug=server.slug,
        agent_type_id=agent_type.id,
        session_id=session_id,
        db=db_session,
    )
    
    # 8. Verify response
    assert result.session_id == mcp_session.id
    assert result.server_id == server.id
    assert result.server_base_url == server.base_url
    assert "Authorization" in result.auth_headers
    assert result.auth_headers["Authorization"] == "Bearer test-api-key-123"
    assert result.auth_type == "api_key"
    
    print("✅ Test passed: MCP session endpoint correctly uses role-based MCP sessions")


async def test_mcp_session_endpoint_no_role_assignment(
    db_session,
):
    """Test that endpoint returns 404 when agent type has no role or role has no MCP session.
    
    This ensures proper error handling when MCP sessions aren't configured for a role.
    """
    from app.db.models.agents import AgentJob, AgentJobStatus, AgentType, AgentRole, AgentRoleMcpSession
    from app.db.models.mcp_hub import McpServer, McpSession, McpSessionAuthType
    from app.api.v1.internal.agent_data import get_mcp_session_for_tool_routing
    from app.core.credential_vault import get_vault
    from fastapi import HTTPException
    import json
    
    # Create agent roles
    role_with_mcp = AgentRole(
        name="Role With MCP",
        description="Role that has MCP sessions",
    )
    role_without_mcp = AgentRole(
        name="Role Without MCP",
        description="Role without MCP sessions",
    )
    db_session.add_all([role_with_mcp, role_without_mcp])
    await db_session.flush()
    
    # Create agent type linked to role WITHOUT MCP
    agent_type = AgentType(
        name="Test Agent",
        description="Test agent for no MCP session case",
        system_instruction="Test instruction",
        role_id=role_without_mcp.id,
        is_active=True,
    )
    db_session.add(agent_type)
    await db_session.flush()
    
    # Create session for this agent
    session_id = uuid.uuid4()
    agent_job = AgentJob(
        id=session_id,
        agent_type_id=agent_type.id,
        status=AgentJobStatus.queued,
    )
    db_session.add(agent_job)
    await db_session.flush()
    
    # Create MCP server with session ONLY for the other role
    server = McpServer(
        name="test-server-2",
        slug="test-server-2",
        base_url="http://localhost:9999/mcp",
    )
    db_session.add(server)
    await db_session.flush()
    
    vault = get_vault()
    test_credentials = {"api_key": "role-with-mcp-key"}
    encrypted_creds = vault.encrypt(json.dumps(test_credentials))
    
    mcp_session = McpSession(
        server_id=server.id,
        name="role-with-mcp-session",
        auth_type=McpSessionAuthType.api_key,
        encrypted_credentials=encrypted_creds,
        is_active=True,
    )
    db_session.add(mcp_session)
    await db_session.flush()
    
    # Link MCP session to role_with_mcp (NOT role_without_mcp)
    role_mcp_link = AgentRoleMcpSession(
        role_id=role_with_mcp.id,
        mcp_session_id=mcp_session.id,
        server_id=server.id,
    )
    db_session.add(role_mcp_link)
    await db_session.commit()
    
    # Try to access MCP session - should fail because role_without_mcp has no session for this server
    with pytest.raises(HTTPException) as exc_info:
        await get_mcp_session_for_tool_routing(
            server_slug=server.slug,
            agent_type_id=agent_type.id,
            session_id=session_id,
            db=db_session,
        )
    
    # Should return 404 - no MCP session found for this role
    assert exc_info.value.status_code == 404
    assert "No MCP session assigned to role" in exc_info.value.detail
    
    print("✅ Test passed: Endpoint correctly handles missing role MCP session assignments")
