"""Quick test script for OAuth auto-discovery implementation."""
import asyncio
import sys
sys.path.insert(0, "C:\\Users\\rhu\\source\\personal\\coding-workspace\\Parthenon\\backend")

from app.db.models.mcp_hub import McpServer, McpSessionAuthType
from app.schemas.mcp_hub import McpServerCreate

async def test_oauth_config():
    """Test that oauth_config field exists and works."""
    
    # Test 1: Check model has oauth_config attribute
    print("✓ Test 1: Checking McpServer model...")
    assert hasattr(McpServer, 'oauth_config'), "McpServer should have oauth_config field"
    print("  ✅ oauth_config field exists")
    
    # Test 2: Check oauth2 is in auth type enum
    print("\n✓ Test 2: Checking McpSessionAuthType enum...")
    auth_types = [t.value for t in McpSessionAuthType]
    assert 'oauth2' in auth_types, "oauth2 should be in McpSessionAuthType enum"
    print(f"  ✅ Auth types: {auth_types}")
    
    # Test 3: Check server creation schema
    print("\n✓ Test 3: Checking McpServerCreate schema...")
    server_data = {
        "name": "Test OAuth Server",
        "slug": "test-oauth",
        "base_url": "https://api.example.com",
    }
    server = McpServerCreate(**server_data)
    print(f"  ✅ Can create server: {server.name}")
    
    print("\n" + "="*60)
    print("✅ All basic model tests passed!")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(test_oauth_config())
