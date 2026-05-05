"""Simulate backend truststore behavior to verify corporate cert fix works."""
import ssl
import os
import asyncio

try:
    import truststore
    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    print("truststore: OK, SSLContext created")
except ImportError:
    ctx = None
    print("truststore: NOT installed")

import httpx

ssl_verify = ctx if ctx is not None else True
print(f"ssl_verify type: {type(ssl_verify).__name__}")


async def test():
    async with httpx.AsyncClient(timeout=10.0, verify=ssl_verify) as client:
        resp = await client.get("https://mcp.supabase.com/mcp")
        print(f"Status: {resp.status_code}")
        ww = resp.headers.get("www-authenticate", "")
        if ww:
            print(f"WWW-Authenticate: {ww[:120]}")
        else:
            print("WWW-Authenticate: (none)")
        return resp.status_code


status = asyncio.run(test())
if status == 401:
    print("\nRESULT: PASS - truststore works in backend! Got 401 (auth required, not SSL error)")
else:
    print(f"\nRESULT: Got {status} (unexpected but no SSL error)")
