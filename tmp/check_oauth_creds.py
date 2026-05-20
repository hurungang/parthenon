import asyncio
import sys
sys.path.insert(0, "C:/Users/rhu/source/personal/coding-workspace/Parthenon/backend")
import json
from sqlalchemy import select
from app.db.session import get_db
from app.db.models.mcp_hub import McpSession
from app.core.credential_vault import get_vault


async def main():
    async for session in get_db():
        # Get the Supabase MCP session with credentials
        result = await session.execute(
            select(McpSession).where(McpSession.id == "5fa4bc8b-3cfa-40a6-9e83-f3c21671afd8")
        )
        mcp_session = result.scalar_one_or_none()
        
        if mcp_session and mcp_session.encrypted_credentials:
            vault = get_vault()
            decrypted = vault.decrypt(mcp_session.encrypted_credentials)
            creds = json.loads(decrypted)
            print("Supabase OAuth2 Credentials Structure:")
            print(json.dumps(creds, indent=2))
        else:
            print("No credentials found")
        
        break

if __name__ == "__main__":
    asyncio.run(main())
