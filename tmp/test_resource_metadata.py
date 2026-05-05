"""Test Supabase resource metadata."""
import httpx
import json

metadata_url = "https://mcp.supabase.com/.well-known/oauth-protected-resource/mcp"

print(f"Testing: {metadata_url}\n")

try:
    response = httpx.get(metadata_url, timeout=10, verify=False)
    print(f"Status: {response.status_code}")
    print(f"\nHeaders:")
    for key, value in response.headers.items():
        print(f"  {key}: {value}")
    print(f"\nBody:")
    data = response.json()
    print(json.dumps(data, indent=2))
    
    # Check for authorization_servers
    if "authorization_servers" in data:
        print(f"\nAuthorization servers found: {data['authorization_servers']}")
        for as_url in data['authorization_servers']:
            print(f"\nFetching AS metadata from: {as_url}/.well-known/oauth-authorization-server")
            as_response = httpx.get(f"{as_url}/.well-known/oauth-authorization-server", timeout=10, verify=False)
            print(f"Status: {as_response.status_code}")
            if as_response.status_code == 200:
                as_data = as_response.json()
                print(json.dumps(as_data, indent=2))
except Exception as e:
    print(f"Error: {e}")
