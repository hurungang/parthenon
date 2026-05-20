import asyncio
import sys
import json
sys.path.insert(0, "C:/Users/rhu/source/personal/coding-workspace/Parthenon/backend")
import httpx
from pathlib import Path


async def main():
    # Read service cert (use control-center cert for testing)
    cert_path = Path("C:/Users/rhu/source/personal/coding-workspace/Parthenon/backend/certs/control-center/service-cert.pem")
    cert_content = cert_path.read_text()
    cert_header_value = cert_content.replace("\n", "\\n")
    
    headers = {
        "X-Client-Certificate": cert_header_value
    }
    
    # Test both servers
    for server_slug in ["supabase", "hello-world"]:
        print(f"\n{'='*60}")
        print(f"Testing {server_slug}")
        print('='*60)
        
        url = f"http://localhost:8000/api/v1/internal/data/mcp-sessions/{server_slug}"
        params = {
            "agent_type_id": "11ea1b70-2bb1-4e8a-9626-012d78979df7",
            "session_id": "00000000-0000-0000-0000-000000000001",  # Dummy session ID
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                print(f"Status: {response.status_code}")
                print(f"Auth Type: {data.get('auth_type')}")
                print(f"Server URL: {data.get('server_base_url')}")
                print(f"Auth Headers: {data.get('auth_headers')}")
                
                # Check if Authorization header exists
                auth_headers = data.get('auth_headers', {})
                if 'Authorization' in auth_headers:
                    auth_value = auth_headers['Authorization']
                    # Mask the token for security
                    if ' ' in auth_value:
                        auth_type, token = auth_value.split(' ', 1)
                        print(f"  Authorization: {auth_type} {token[:20]}...{token[-10:]}")
                    else:
                        print(f"  Authorization: {auth_value[:30]}...")
                else:
                    print("  NO AUTHORIZATION HEADER!")
                    
            except Exception as exc:
                print(f"Error: {exc}")

if __name__ == "__main__":
    asyncio.run(main())
