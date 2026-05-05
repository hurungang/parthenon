"""Test Supabase MCP server responses."""
import httpx

url = "https://mcp.supabase.com/mcp"

print(f"Testing: {url}\n")

# Test base URL
print("=" * 60)
print("Testing base URL")
print("=" * 60)
try:
    response = httpx.get(url, timeout=10, verify=False)
    print(f"Status: {response.status_code}")
    print(f"\nHeaders:")
    for key, value in response.headers.items():
        print(f"  {key}: {value}")
    print(f"\nBody (first 500 chars):")
    print(response.text[:500])
except Exception as e:
    print(f"Error: {e}")

# Test well-known endpoint
print("\n" + "=" * 60)
print("Testing /.well-known/oauth-authorization-server")
print("=" * 60)
try:
    response = httpx.get(f"{url}/.well-known/oauth-authorization-server", timeout=10, verify=False)
    print(f"Status: {response.status_code}")
    print(f"\nBody:")
    print(response.text[:1000])
except Exception as e:
    print(f"Error: {e}")

# Test /oauth/metadata
print("\n" + "=" * 60)
print("Testing /oauth/metadata")
print("=" * 60)
try:
    response = httpx.get(f"{url}/oauth/metadata", timeout=10, verify=False)
    print(f"Status: {response.status_code}")
    print(f"\nBody:")
    print(response.text[:1000])
except Exception as e:
    print(f"Error: {e}")
