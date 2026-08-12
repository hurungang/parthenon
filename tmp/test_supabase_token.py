import asyncio
import sys
import json
sys.path.insert(0, "C:/Users/rhu/source/personal/coding-workspace/Parthenon/backend")
import httpx
from app.db.session import get_db
from app.db.models.mcp_hub import McpSession
from app.core.credential_vault import get_vault
from sqlalchemy import select


async def main():
    async for session in get_db():
        # Get Supabase MCP session
        result = await session.execute(
            select(McpSession).where(McpSession.id == "5fa4bc8b-3cfa-40a6-9e83-f3c21671afd8")
        )
        mcp_session = result.scalar_one_or_none()
        
        if mcp_session and mcp_session.encrypted_credentials:
            vault = get_vault()
            decrypted = vault.decrypt(mcp_session.encrypted_credentials)
            creds = json.loads(decrypted)
            access_token = creds.get("access_token")
            
            print(f"Testing Supabase MCP with token: {access_token[:30]}...")
            
            # Test the token directly
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "get_project",
                    "arguments": {},
                },
            }
            
            async with httpx.AsyncClient(verify=False) as client:
                try:
                    print("\nSending request to https://mcp.supabase.com/mcp (SSL verify=False)")
                    print(f"Headers: Authorization header present")
                    response = await client.post(
                        "https://mcp.supabase.com/mcp",
                        json=payload,
                        headers=headers,
                        timeout=10.0,
                    )
                    print(f"\nResponse Status: {response.status_code}")
                    print(f"Response Body: {response.text}")
                except Exception as exc:
                    print(f"Error: {exc}")
        
        break

if __name__ == "__main__":
    asyncio.run(main())
