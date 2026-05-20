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
        result2 = await conn.execute(text("SELECT unnest(enum_range(NULL::source_type_enum))::text"))
        print('source_type_enum values:', [r[0] for r in result2.fetchall()])
        result3 = await conn.execute(text("SELECT unnest(enum_range(NULL::channel_type_enum))::text"))
        print('channel_type_enum values:', [r[0] for r in result3.fetchall()])

asyncio.run(check())
