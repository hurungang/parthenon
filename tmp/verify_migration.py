import asyncio
from sqlalchemy import text
import sys
sys.path.insert(0, 'backend')
from app.db.session import async_engine

async def check_column():
    async with async_engine.begin() as conn:
        result = await conn.execute(text(
            "SELECT column_name, data_type, column_default "
            "FROM information_schema.columns "
            "WHERE table_name='agent_roles' AND column_name='allowed_identity_types'"
        ))
        row = result.fetchone()
        if row:
            print(f"✓ Column '{row[0]}' exists")
            print(f"  Type: {row[1]}")
            print(f"  Default: {row[2]}")
        else:
            print("✗ Column 'allowed_identity_types' not found!")

asyncio.run(check_column())
