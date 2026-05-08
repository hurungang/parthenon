"""Bind Supabase MCP session to an agent identity."""
import asyncio
from sqlalchemy import select, update
from app.db.session import AsyncSessionLocal
from app.db.models.mcp_hub import McpSession, McpServer
from app.db.models.agents import AgentIdentity


async def bind_session():
    async with AsyncSessionLocal() as db:
        # Get the Supabase MCP session
        result = await db.execute(
            select(McpSession)
            .join(McpServer)
            .where(McpServer.slug == "supabase")
        )
        supabase_session = result.scalar_one_or_none()
        
        if not supabase_session:
            print("Supabase MCP session not found")
            return
        
        # Get an agent identity (use the first one)
        identity_result = await db.execute(select(AgentIdentity))
        identity = identity_result.scalars().first()
        
        if not identity:
            print("No agent identities found")
            return
        
        print(f"Binding Supabase MCP session to agent identity:")
        print(f"  Session: {supabase_session.name}")
        print(f"  Identity: {identity.realm_username} ({identity.id})")
        
        # Update the session to bind it to the identity
        await db.execute(
            update(McpSession)
            .where(McpSession.id == supabase_session.id)
            .values(identity_subject=identity.realm_username)
        )
        
        await db.commit()
        print("\n✅ Supabase MCP session bound to agent identity successfully")
        print(f"\nThe agent '{identity.realm_username}' can now use Supabase tools.")


if __name__ == "__main__":
    asyncio.run(bind_session())
