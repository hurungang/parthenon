"""GET /mcp/tools?server_id=... — server-side filter on the tool listing.

Coverage:
- filtering by ``server_id`` returns ONLY that server's tools;
- ``X-Total-Count`` reflects the filtered total, not the unfiltered one;
- unfiltered behaviour is unchanged (all servers' tools, stable order).

The handlers are called directly with a real (unscoped, SQLite) session and a
bare ASGI ``Request``; ``_cc_visible`` is patched to model the caller's
permission without a full auth stack — mirroring
``test_fix_20261102_062047_mcp_tool_listing.py``.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Response

from app.api.v1.mcp_hub import list_all_tools
from app.db.models.mcp_hub import McpServer, McpTool


def _request(path: str = "/api/v1/mcp/tools") -> "object":
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("test", 1234),
            "server": ("test", 80),
        }
    )


def _cc_gate(visible: bool):
    return patch("app.api.v1.mcp_hub._cc_visible", new=AsyncMock(return_value=visible))


async def _seed_server(db, slug: str, n_tools: int) -> McpServer:
    server = McpServer(
        tenant_id=None,
        name=f"{slug}-server",
        slug=slug,
        description="d",
        base_url="http://example.test",
        status="active",
    )
    db.add(server)
    await db.flush()
    for index in range(n_tools):
        bare = f"tool_{index:03d}"
        db.add(
            McpTool(
                tenant_id=None,
                server_id=server.id,
                name=f"{slug}____{bare}",
                original_name=bare,
                description="d",
                input_schema={"type": "object", "properties": {}},
                is_active=True,
            )
        )
    await db.flush()
    return server


async def _call(db, **params) -> tuple[list, int]:
    response = Response()
    with _cc_gate(True):
        page = await list_all_tools(_request(), db, response, {}, **params)
    return page, int(response.headers["X-Total-Count"])


@pytest.mark.asyncio
async def test_server_id_filter_returns_only_that_servers_tools(db_session) -> None:
    marker = uuid.uuid4().hex[:8]
    alpha = await _seed_server(db_session, f"alpha-{marker}", 5)
    await _seed_server(db_session, f"beta-{marker}", 7)

    page, total = await _call(db_session, limit=200, offset=0, server_id=alpha.id)

    assert total == 5
    assert len(page) == 5
    assert {tool.server_slug for tool in page} == {f"alpha-{marker}"}
    assert {tool.server_id for tool in page} == {alpha.id}


@pytest.mark.asyncio
async def test_server_id_filter_pagination_is_accurate(db_session) -> None:
    """Filter composes with limit/offset and the header matches the filtered total."""
    marker = uuid.uuid4().hex[:8]
    alpha = await _seed_server(db_session, f"alpha-{marker}", 5)
    await _seed_server(db_session, f"beta-{marker}", 7)

    page, total = await _call(db_session, limit=3, offset=2, server_id=alpha.id)

    assert total == 5
    assert len(page) == 3
    assert all(tool.server_id == alpha.id for tool in page)
    # Offset respects the stable (server_slug, name, id) ordering.
    full, _ = await _call(db_session, limit=200, offset=0, server_id=alpha.id)
    assert [t.id for t in page] == [t.id for t in full[2:5]]


@pytest.mark.asyncio
async def test_unfiltered_listing_is_unchanged(db_session) -> None:
    """Omitting server_id keeps the full cross-server behaviour."""
    marker = uuid.uuid4().hex[:8]
    alpha = await _seed_server(db_session, f"alpha-{marker}", 5)
    beta = await _seed_server(db_session, f"beta-{marker}", 7)

    page, total = await _call(db_session, limit=200, offset=0)

    # The full set also includes virtual system/decision tools; the key
    # guarantee is that BOTH freshly seeded servers appear unfiltered.
    slugs = {tool.server_slug for tool in page}
    assert total >= 12
    assert {f"alpha-{marker}", f"beta-{marker}"} <= slugs
    assert {tool.server_id for tool in page if tool.server_slug in {f"alpha-{marker}", f"beta-{marker}"}} == {
        alpha.id,
        beta.id,
    }


@pytest.mark.asyncio
async def test_server_id_filter_for_unknown_server_returns_empty(db_session) -> None:
    marker = uuid.uuid4().hex[:8]
    await _seed_server(db_session, f"alpha-{marker}", 5)

    page, total = await _call(db_session, limit=200, offset=0, server_id=uuid.uuid4())

    assert total == 0
    assert page == []
