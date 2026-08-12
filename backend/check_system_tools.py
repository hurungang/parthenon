import asyncio
from app.db.session import async_session
from sqlalchemy import select
from app.db.models.mcp_hub import McpTool, McpServer

async def check():
    async with async_session() as db:
        result = await db.execute(
            select(McpTool.name, McpServer.slug)
            .join(McpServer)
            .where(McpServer.slug == 'system')
        )
        rows = result.all()
        print('System tools in DB:')
        for name, slug in rows:
            print(f"  {slug}/{name}")

asyncio.run(check())
