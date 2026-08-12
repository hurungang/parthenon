"""Check and update Supabase MCP session with project ID parameter."""
import asyncio
import json
from sqlalchemy import select, update
from app.db.session import AsyncSessionLocal
from app.db.models.mcp_hub import McpSession, McpServer


async def update_session_params():
    async with AsyncSessionLocal() as db:
        # Get the Supabase MCP session
        result = await db.execute(
            select(McpSession)
            .join(McpServer)
            .where(McpServer.slug == "supabase")
            .where(McpSession.identity_subject.isnot(None))
        )
        supabase_session = result.scalar_one_or_none()
        
        if not supabase_session:
            print("Supabase MCP session not found or not bound to identity")
            return
        
        print(f"Current Supabase MCP session configuration:")
        print(f"  Name: {supabase_session.name}")
        print(f"  Identity Subject: {supabase_session.identity_subject}")
        print(f"  Credential Config: {json.dumps(supabase_session.credential_config, indent=2) if supabase_session.credential_config else 'None'}")
        print(f"  Identity Binding: {json.dumps(supabase_session.identity_binding, indent=2) if supabase_session.identity_binding else 'None'}")
        
        # Get project ID from user
        print("\nTo use Supabase tools, you need to provide the project ID.")
        print("You can find this in your Supabase dashboard URL:")
        print("  https://supabase.com/dashboard/project/<PROJECT_ID>")
        print("\nEnter the Supabase project ID (or press Enter to skip):")
        project_id = input().strip()
        
        if not project_id:
            print("Skipping project ID configuration")
            return
        
        # Update identity_binding with project ID
        identity_binding = supabase_session.identity_binding or {}
        identity_binding["project_id"] = project_id
        identity_binding["resource_type"] = "supabase_project"
        
        await db.execute(
            update(McpSession)
            .where(McpSession.id == supabase_session.id)
            .values(identity_binding=identity_binding)
        )
        
        await db.commit()
        print(f"\n✅ Updated Supabase MCP session with project ID: {project_id}")
        print("\nThe agent will now know about this project ID when using Supabase tools.")


if __name__ == "__main__":
    asyncio.run(update_session_params())
