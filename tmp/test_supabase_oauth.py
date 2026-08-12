"""Quick test: SSL + OAuth discovery for mcp.supabase.com using truststore."""
import httpx
import ssl
import truststore

ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
client = httpx.Client(verify=ctx, timeout=10.0)

urls = [
    "https://mcp.supabase.com/",
    "https://mcp.supabase.com/.well-known/oauth-authorization-server",
    "https://mcp.supabase.com/oauth/metadata",
    "https://mcp.supabase.com/sse",
]

print("=== Supabase MCP OAuth Discovery Test ===\n")
for url in urls:
    try:
        resp = client.get(url, follow_redirects=True)
        print(f"[{resp.status_code}] {url}")
        ww_auth = resp.headers.get("www-authenticate", "")
        if ww_auth:
            print(f"  WWW-Authenticate: {ww_auth}")
        content_type = resp.headers.get("content-type", "")
        if resp.status_code == 200 and "json" in content_type:
            print(f"  Body (200 JSON): {resp.text[:300]}")
    except Exception as e:
        print(f"[ERROR] {url}: {e}")

client.close()
print("\nDone. No SSL errors = cert fix is working.")
