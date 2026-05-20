import asyncio
import sys
sys.path.insert(0, "C:/Users/rhu/source/personal/coding-workspace/Parthenon/backend")
from sqlalchemy import select
from app.db.session import get_db
from app.db.models.mcp_hub import McpSession, McpServer
from app.db.models.agents import AgentRoleMcpSession, AgentRole


async def main():
    async for session in get_db():
        # Check MCP servers
        result = await session.execute(select(McpServer))
        servers = result.scalars().all()
        print("MCP Servers:")
        for s in servers:
            print(f"  ID: {s.id} | slug: {s.slug} | base_url: {s.base_url}")
        
        print("\nMCP Sessions:")
        result = await session.execute(select(McpSession))
        sessions = result.scalars().all()
        for s in sessions:
            has_creds = bool(s.encrypted_credentials)
            print(f"  ID: {s.id} | server_id: {s.server_id} | auth_type: {s.auth_type} | has_creds: {has_creds}")
        
        print("\nAgent Role MCP Session Assignments:")
        result = await session.execute(select(AgentRoleMcpSession))
        assignments = result.scalars().all()
        for a in assignments:
            print(f"  role_id: {a.role_id} | mcp_session_id: {a.mcp_session_id}")
        
        break

if __name__ == "__main__":
    asyncio.run(main())
