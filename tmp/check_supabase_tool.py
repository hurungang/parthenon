"""Check supabase/get_project tool definition in database."""
import asyncio
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.db.models.mcp_hub import McpTool


async def check_tool():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(McpTool).where(McpTool.name == "supabase/get_project")
        )
        tool = result.scalar_one_or_none()
        
        if not tool:
            print("Tool 'supabase/get_project' not found in database")
            return
        
        print(f"Tool: {tool.name}")
        print(f"Description: {tool.description}")
        print(f"Is Active: {tool.is_active}")
        print(f"\nInput Schema:")
        import json
        print(json.dumps(tool.input_schema, indent=2))


if __name__ == "__main__":
    asyncio.run(check_tool())
