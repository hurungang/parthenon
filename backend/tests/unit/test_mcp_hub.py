"""
Test ToolSyncService: idempotent upsert and tool deactivation on removal.
Tests McpProxyEngine session resolution via ToolSyncService.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_toolsyncservice_adds_new_tools():
    """ToolSyncService.sync() adds new tools from the remote server."""
    from app.db.models.mcp_hub import McpServerStatus
    from app.services.mcp.tool_sync import ToolSyncService

    mock_server = MagicMock()
    mock_server.id = uuid.uuid4()
    mock_server.slug = "my-server"
    mock_server.base_url = "http://mcp-server"
    mock_server.status = McpServerStatus.active

    mock_db = AsyncMock()
    # No existing tools found (first sync)
    mock_db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # tool lookup
            MagicMock(
                scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            ),  # deactivation query
        ]
    )

    service = ToolSyncService()

    remote_tools = [{"name": "toolA", "description": "Tool A"}]
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_response = MagicMock()
        mock_response.json.return_value = remote_tools
        mock_response.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await service.sync(mock_server, mock_db)

    assert result["added"] == 1
    assert result["deactivated"] == 0
    mock_db.add.assert_called_once()


@pytest.mark.asyncio
async def test_toolsyncservice_deactivates_removed_tools():
    """ToolSyncService.sync() marks tools inactive when they disappear from remote."""
    from app.db.models.mcp_hub import McpServerStatus, McpTool
    from app.services.mcp.tool_sync import ToolSyncService

    mock_server = MagicMock()
    mock_server.id = uuid.uuid4()
    mock_server.slug = "my-server"
    mock_server.base_url = "http://mcp-server"
    mock_server.status = McpServerStatus.active

    # An existing tool that won't be in the remote response
    stale_tool = MagicMock(spec=McpTool)
    stale_tool.name = "my-server/toolA"
    stale_tool.is_active = True

    mock_db = AsyncMock()
    # Remote returns empty → stale_tool should be deactivated
    mock_db.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[stale_tool])))
        )
    )

    service = ToolSyncService()
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_response = MagicMock()
        mock_response.json.return_value = []  # empty — no tools
        mock_response.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await service.sync(mock_server, mock_db)

    assert stale_tool.is_active is False
    assert result["deactivated"] == 1
