from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


async def register_with_hub(
    hub_base_url: str,
    api_token: str,
    slug: str,
    app_base_url: str,
) -> None:
    """Register this demo app with the Parthenon MCP Hub and trigger a tool sync.

    Steps:
    1. POST /api/v1/mcp/servers — create the server record (slug + base_url).
       On 409, look up the existing record to get the server_id.
    2. POST /api/v1/mcp/servers/{server_id}/sync — trigger tool sync.
    """
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }
    server_payload = {
        "name": "MCP Demo App",
        "slug": slug,
        "base_url": app_base_url,
    }

    async with httpx.AsyncClient(base_url=hub_base_url, timeout=30.0) as client:
        # Step 1 — create or look up the server record
        create_resp = await client.post(
            "/api/v1/mcp/servers",
            json=server_payload,
            headers=headers,
        )

        if create_resp.status_code == 201:
            server_id: str = create_resp.json()["id"]
            logger.info("Hub: registered new server (slug=%s, id=%s)", slug, server_id)

        elif create_resp.status_code == 409:
            logger.info("Hub: server already registered (slug=%s), looking up existing record", slug)
            list_resp = await client.get("/api/v1/mcp/servers", headers=headers)
            list_resp.raise_for_status()
            servers = list_resp.json()
            # Handle both paginated {"items": [...]} and plain list responses
            items = servers if isinstance(servers, list) else servers.get("items", servers)
            match = next((s for s in items if s.get("slug") == slug), None)
            if match is None:
                raise RuntimeError(
                    f"Server slug '{slug}' returned 409 but was not found in server list"
                )
            server_id = match["id"]
            logger.info("Hub: found existing server (slug=%s, id=%s)", slug, server_id)

        else:
            create_resp.raise_for_status()  # unexpected error — bubble up

        # Step 2 — trigger tool sync
        sync_resp = await client.post(
            f"/api/v1/mcp/servers/{server_id}/sync",
            headers=headers,
        )
        sync_resp.raise_for_status()
        logger.info("Hub: tool sync triggered for server_id=%s", server_id)
