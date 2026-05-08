"""Check MCP sessions for an agent identity."""
import asyncio
import json
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.db.session import AsyncSessionLocal
from app.db.models.mcp_hub import McpSession
from app.db.models.agents import AgentIdentity


async def check_sessions():
    async with AsyncSessionLocal() as db:
        # List all agent identities
        result = await db.execute(select(AgentIdentity))
        identities = list(result.scalars().all())
        
        if not identities:
            print("No agent identities found")
            return
        
        print(f"Found {len(identities)} agent identities:\n")
        for identity in identities:
            print(f"Identity: {identity.id}")
            print(f"  Realm Username: {identity.realm_username}")
            print(f"  Identity Type: {identity.identity_type}")
            
            # Find MCP sessions for this identity
            session_result = await db.execute(
                select(McpSession)
                .options(selectinload(McpSession.server))
                .where(McpSession.identity_subject == identity.realm_username)
            )
            sessions = list(session_result.scalars().all())
            
            if sessions:
                print(f"  MCP Sessions ({len(sessions)}):")
                for session in sessions:
                    print(f"    - Session: {session.name}")
                    print(f"      Server: {session.server.name} ({session.server.slug})")
                    print(f"      Auth Type: {session.auth_type.value}")
                    print(f"      Is Active: {session.is_active}")
                    if session.credential_config:
                        print(f"      Credential Config: {json.dumps(session.credential_config, indent=8)}")
                    if session.identity_binding:
                        print(f"      Identity Binding: {json.dumps(session.identity_binding, indent=8)}")
                    print()
            else:
                print(f"  No MCP sessions found\n")


if __name__ == "__main__":
    asyncio.run(check_sessions())
