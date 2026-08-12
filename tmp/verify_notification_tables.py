import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def check():
    db_url = os.environ.get('DATABASE_URL', 'postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon')
    engine = create_async_engine(db_url)
    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name IN "
            "('channel_properties', 'recipient_groups', 'group_channel_mappings', 'notification_logs')"
        ))
        rows = result.fetchall()
        print('Tables found:', sorted([r[0] for r in rows]))

asyncio.run(check())
