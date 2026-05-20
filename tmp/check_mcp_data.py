"""Check MCP servers and sessions in database."""
import asyncio
from app.db.session import get_db_session
from sqlalchemy import select
from app.db.models.mcp_hub import McpServer, McpSession


async def check_mcp_data():
    async with get_db_session() as db:
        # Get all servers
        servers = (await db.execute(select(McpServer))).scalars().all()
        print(f"MCP Servers: {len(servers)}")
        for s in servers:
            print(f"  - {s.slug}: {s.base_url}")
        
        # Get all sessions
        sessions = (await db.execute(select(McpSession))).scalars().all()
        print(f"\nMCP Sessions: {len(sessions)}")
        for sess in sessions:
            print(f"  - Session {sess.id}: Server={sess.server_id}, Active={sess.is_active}")


if __name__ == "__main__":
    asyncio.run(check_mcp_data())
