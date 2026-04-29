"""Tool Sync Service — fetches tool list from MCP server and upserts records."""
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.mcp_hub import McpServer, McpServerStatus, McpTool

logger = logging.getLogger(__name__)


class ToolSyncService:
    """
    Fetches the tool list from a registered MCP server's HTTP endpoint
    and upserts tools namespaced under the server slug.
    """

    async def sync(self, server: McpServer, db: AsyncSession) -> dict[str, int]:
        """
        Sync tools from the MCP server. Returns counts of added/updated/deactivated tools.

        Tool endpoint convention: GET {base_url}/tools
        """
        tools_url = f"{server.base_url.rstrip('/')}/tools"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(tools_url)
                response.raise_for_status()
                remote_data: list[dict[str, Any]] = response.json()
        except httpx.HTTPError as exc:
            logger.error("Failed to fetch tools from %s: %s", tools_url, exc)
            server.status = McpServerStatus.error
            await db.flush()
            raise RuntimeError(f"Failed to fetch tools: {exc}") from exc

        remote_names: set[str] = set()
        added = 0
        updated = 0

        for tool_data in remote_data:
            original_name = tool_data.get("name", "")
            if not original_name:
                continue
            namespaced_name = f"{server.slug}/{original_name}"
            remote_names.add(namespaced_name)

            # Look for existing tool record
            result = await db.execute(
                select(McpTool).where(
                    McpTool.server_id == server.id,
                    McpTool.name == namespaced_name,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.description = tool_data.get("description")
                existing.input_schema = tool_data.get("inputSchema") or tool_data.get("input_schema")
                existing.is_active = True
                updated += 1
            else:
                new_tool = McpTool(
                    server_id=server.id,
                    name=namespaced_name,
                    original_name=original_name,
                    description=tool_data.get("description"),
                    input_schema=tool_data.get("inputSchema") or tool_data.get("input_schema"),
                    is_active=True,
                )
                db.add(new_tool)
                added += 1

        # Deactivate tools that are no longer present on the server
        existing_tools_result = await db.execute(
            select(McpTool).where(
                McpTool.server_id == server.id,
                McpTool.is_active == True,  # noqa: E712
            )
        )
        existing_tools = existing_tools_result.scalars().all()
        deactivated = 0
        for tool in existing_tools:
            if tool.name not in remote_names:
                tool.is_active = False
                deactivated += 1

        # Update server sync timestamp
        server.last_synced_at = datetime.now(timezone.utc)
        server.status = McpServerStatus.active
        await db.flush()

        logger.info(
            "Synced tools for server %s: +%d updated=%d deactivated=%d",
            server.slug, added, updated, deactivated,
        )
        return {"added": added, "updated": updated, "deactivated": deactivated}
