"""Test MCP tool calls via the three-service architecture.

Tests:
1. Hello-world MCP call with passthrough auth (agent identity JWT)
2. Logs to verify auth headers are sent correctly
"""
import asyncio
import httpx
import sys
sys.path.insert(0, "C:/Users/rhu/source/personal/coding-workspace/Parthenon/backend")
from pathlib import Path


async def trigger_agent_and_check_logs():
    # Read agent-runtime service cert for authentication
    cert_path = Path("C:/Users/rhu/source/personal/coding-workspace/Parthenon/backend/certs/communication-hub/service-cert.pem")
    if not cert_path.exists():
        # Try control-center cert
        cert_path = Path("C:/Users/rhu/source/personal/coding-workspace/Parthenon/backend/certs/control-center/service-cert.pem")
    
    cert_content = cert_path.read_text()
    cert_header_value = cert_content.replace("\n", "\\n")
    
    headers = {
        "X-Client-Certificate": cert_header_value,
        "Content-Type": "application/json",
    }
    
    # Create a test agent session
    payload = {
        "agent_type_id": "11ea1b70-2bb1-4e8a-9626-012d78979df7",  # support_agent
        "session_id": "da2b7dce-e376-49dc-8a15-3efc5eb12401",  # real session from logs
    }
    
    print("Testing MCP session endpoints...")
    print("=" * 60)
    
    # Test hello-world (passthrough)
    print("\n1. Testing hello-world (passthrough) session:")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                "http://localhost:8000/api/v1/internal/data/mcp-sessions/hello-world",
                params=payload,
                headers=headers,
            )
            print(f"   Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"   Auth type: {data.get('auth_type')}")
                print(f"   Has auth header: {'Authorization' in data.get('auth_headers', {})}")
                if 'Authorization' in data.get('auth_headers', {}):
                    auth_value = data['auth_headers']['Authorization']
                    preview = f"{auth_value[:30]}...{auth_value[-10:]}" if len(auth_value) > 50 else f"{auth_value[:40]}..."
                    print(f"   Auth preview: {preview}")
                    print("   ✅ Passthrough session has agent identity JWT!")
                else:
                    print("   ❌ Passthrough session missing auth header")
            else:
                print(f"   Error: {response.text}")
        except Exception as exc:
            print(f"   Error: {exc}")
    
    # Test supabase (oauth2)
    print("\n2. Testing supabase (oauth2) session:")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                "http://localhost:8000/api/v1/internal/data/mcp-sessions/supabase",
                params=payload,
                headers=headers,
            )
            print(f"   Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"   Auth type: {data.get('auth_type')}")
                print(f"   Has auth header: {'Authorization' in data.get('auth_headers', {})}")
                if 'Authorization' in data.get('auth_headers', {}):
                    auth_value = data['auth_headers']['Authorization']
                    preview = f"{auth_value[:30]}...{auth_value[-10:]}" if len(auth_value) > 50 else f"{auth_value[:40]}..."
                    print(f"   Auth preview: {preview}")
                    if auth_value.startswith("Bearer sbp_oauth"):
                        print("   ⚠️  OAuth2 token present (but may be expired)")
                    else:
                        print("   ✅ OAuth2 token present")
                else:
                    print("   ❌ OAuth2 session missing auth header")
            else:
                print(f"   Error: {response.text}")
        except Exception as exc:
            print(f"   Error: {exc}")
    
    print("\n" + "=" * 60)
    print("Test complete! Check logs for actual MCP server responses.")


if __name__ == "__main__":
    asyncio.run(trigger_agent_and_check_logs())
