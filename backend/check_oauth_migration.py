"""Check and apply oauth_config migration."""
import os
import sys
sys.path.insert(0, "C:\\Users\\rhu\\source\\personal\\coding-workspace\\Parthenon\\backend")

# Set required env vars
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import asyncio
from sqlalchemy import text
from app.db.session import async_engine

async def check_migration():
    """Check if oauth_config column exists."""
    async with async_engine.connect() as conn:
        # Check current alembic version
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        current_version = result.scalar()
        print(f"✓ Current migration version: {current_version}")
        
        # Check if oauth_config column exists
        result = await conn.execute(text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'mcp_servers' AND column_name = 'oauth_config'
        """))
        oauth_col = result.fetchone()
        
        if oauth_col:
            print(f"✅ oauth_config column EXISTS: {oauth_col[0]} ({oauth_col[1]})")
        else:
            print("❌ oauth_config column MISSING - migration not applied!")
            print("\nTo apply migration, run:")
            print("  cd backend")
            print("  python -m alembic upgrade head")
        
        # Show all mcp_servers columns
        result = await conn.execute(text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'mcp_servers'
            ORDER BY ordinal_position
        """))
        columns = result.fetchall()
        print(f"\n✓ mcp_servers table columns ({len(columns)}):")
        for col in columns:
            print(f"  - {col[0]}: {col[1]}")

if __name__ == "__main__":
    asyncio.run(check_migration())
