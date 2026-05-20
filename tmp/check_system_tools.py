"""Check for system tool duplicates in database."""
import asyncio
import sys
sys.path.insert(0, 'C:\\Users\\rhu\\source\\personal\\coding-workspace\\Parthenon\\backend')

from app.db.session import AsyncSession
from sqlalchemy import select
from app.models import McpTool, McpServer
from app.core.config import get_settings


async def check_tools():
    """Check for system tools in MCP tools table."""
    settings = get_settings()
    from sqlalchemy.ext.asyncio import create_async_engine
    
    engine = create_async_engine(settings.database_url, echo=False)
    
    async with AsyncSession(bind=engine) as db:
        # Check for tools with save_result or send_notification in name
        result = await db.execute(
            select(McpTool).where(
                (McpTool.name.like('%save_result%')) | 
                (McpTool.name.like('%send_notification%'))
            )
        )
        tools = result.scalars().all()
        print(f'\n=== Found {len(tools)} matching MCP tools ===')
        for t in tools:
            print(f'  {t.name} (server_id: {t.server_id}, active: {t.is_active})')
        
        # Check for System MCP server
        server_result = await db.execute(
            select(McpServer).where(McpServer.name.like('%ystem%'))
        )
        servers = server_result.scalars().all()
        print(f'\n=== Found {len(servers)} System-related servers ===')
        for s in servers:
            print(f'  {s.name} (id: {s.id}, active: {s.is_active})')
        
        # Get all tools for these servers
        if servers:
            server_ids = [s.id for s in servers]
            tools_result = await db.execute(
                select(McpTool).where(McpTool.server_id.in_(server_ids))
            )
            system_tools = tools_result.scalars().all()
            print(f'\n=== All tools for System servers ===')
            for t in system_tools:
                print(f'  {t.name}')
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check_tools())
