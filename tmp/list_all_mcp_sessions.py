"""List all MCP sessions in the system."""
import asyncio
import json
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.db.session import AsyncSessionLocal
from app.db.models.mcp_hub import McpSession


async def list_sessions():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(McpSession).options(selectinload(McpSession.server))
        )
        sessions = list(result.scalars().all())
        
        if not sessions:
            print("No MCP sessions found in the system")
            return
        
        print(f"Found {len(sessions)} MCP sessions:\n")
        for session in sessions:
            print(f"Session ID: {session.id}")
            print(f"  Name: {session.name}")
            print(f"  Server: {session.server.name} ({session.server.slug})")
            print(f"  Auth Type: {session.auth_type.value}")
            print(f"  Identity Subject: {session.identity_subject}")
            print(f"  Is Active: {session.is_active}")
            if session.credential_config:
                print(f"  Credential Config: {json.dumps(session.credential_config, indent=4)}")
            if session.identity_binding:
                print(f"  Identity Binding: {json.dumps(session.identity_binding, indent=4)}")
            print()


if __name__ == "__main__":
    asyncio.run(list_sessions())
