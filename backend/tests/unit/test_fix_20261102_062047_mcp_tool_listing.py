"""FIX-20261102-062047 — complete, deterministic, permission-correct tool listing.

Failing-first coverage for the MCP picker truncation + cc visibility defects:

- ``GET /mcp/tools`` must page over the FULL set with stable ordering and no
  loss/duplication; the default window must not silently hide servers
  (``supabase`` / ``decision`` / ``map-demo``) once the tenant exceeds 50 tools;
- the ``X-Total-Count`` header must equal the true deduped total;
- cc tools are hidden from general browsing without
  ``integration::control_center:read`` but stay individually resolvable when a
  skill already references them;
- ``GET /mcp/servers`` must apply the cc filter BEFORE offset/limit (correct
  pagination) with a deterministic order.

The handlers are called directly with a real (unscoped, SQLite) session and a
bare ASGI ``Request``; ``_cc_visible`` is patched to model the caller's
permission without a full auth stack.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import select
from starlette.requests import Request

from app.api.v1.mcp_hub import (
    SYSTEM_SERVER_ID,
    DECISION_SERVER_ID,
    get_mcp_tool,
    list_all_tools,
    list_mcp_servers,
)
from app.db.models.mcp_hub import McpServer, McpTool
from app.db.models.skills import Skill, SkillToolBinding


def _request(path: str = "/api/v1/mcp/tools") -> Request:
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


def _declared_default(fn, name: str) -> int:
    """The numeric default declared on a FastAPI handler parameter."""
    import inspect

    default = inspect.signature(fn).parameters[name].default
    return int(getattr(default, "default", default))


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


async def _tools_of(db, server: McpServer) -> list[McpTool]:
    result = await db.execute(
        select(McpTool).where(McpTool.server_id == server.id).order_by(McpTool.name)
    )
    return list(result.scalars().all())


def _key(tool) -> tuple[str, str, str]:
    return (tool.server_slug or "", tool.name, str(tool.id))


async def _walk_tools(db, visible: bool, page_size: int) -> tuple[list, int]:
    """Page through the tool endpoint; return concatenated rows + declared total."""
    collected: list = []
    total: int | None = None
    offset = 0
    guard = 0
    while True:
        guard += 1
        assert guard < 100, "pagination did not terminate"
        response = Response()
        with _cc_gate(visible):
            page = await list_all_tools(
                _request(), db, response, {}, limit=page_size, offset=offset
            )
        if total is None:
            total = int(response.headers["X-Total-Count"])
        collected.extend(page)
        if len(page) < page_size:
            break
        offset += len(page)
    return collected, int(total or 0)


# ── /mcp/tools: complete + deterministic + deduped ────────────────────────────


@pytest.mark.asyncio
async def test_tools_default_window_is_not_truncated_at_50(db_session) -> None:
    """FAILING-FIRST: the old default ``limit=50`` hid supabase/decision tools."""
    marker = uuid.uuid4().hex[:8]
    await _seed_server(db_session, f"supabase-{marker}", 60)
    await _seed_server(db_session, f"mapdemo-{marker}", 3)

    response = Response()
    with _cc_gate(True):
        page = await list_all_tools(
            _request(),
            db_session,
            response,
            {},
            limit=_declared_default(list_all_tools, "limit"),
            offset=0,
        )

    assert _declared_default(list_all_tools, "limit") >= 200
    assert len(page) > 50, f"default window returned only {len(page)} tools"
    assert len(page) == int(response.headers["X-Total-Count"])
    slugs = {tool.server_slug for tool in page}
    assert f"supabase-{marker}" in slugs
    assert f"mapdemo-{marker}" in slugs
    assert int(response.headers["X-Total-Count"]) >= len(page)


@pytest.mark.asyncio
async def test_tools_pagination_has_no_loss_or_duplication(db_session) -> None:
    """Every tool appears exactly once across pages; ordering is deterministic."""
    marker = uuid.uuid4().hex[:8]
    await _seed_server(db_session, f"supabase-{marker}", 30)
    await _seed_server(db_session, f"mapdemo-{marker}", 3)

    first, total = await _walk_tools(db_session, True, page_size=20)
    second, total_again = await _walk_tools(db_session, True, page_size=20)

    ids = [str(tool.id) for tool in first]
    assert len(ids) == len(set(ids)), "tool duplicated across pages"
    assert total == total_again == len(first), "X-Total-Count is not the true total"
    assert [_key(t) for t in first] == sorted(_key(t) for t in first)
    assert [_key(t) for t in first] == [_key(t) for t in second]

    seeded = {f"supabase-{marker}", f"mapdemo-{marker}"}
    assert seeded <= {tool.server_slug for tool in first}


@pytest.mark.asyncio
async def test_tools_ordering_is_stable_across_requests(db_session) -> None:
    marker = uuid.uuid4().hex[:8]
    await _seed_server(db_session, f"supabase-{marker}", 5)
    await _seed_server(db_session, f"mapdemo-{marker}", 5)

    with _cc_gate(True):
        a = await list_all_tools(_request(), db_session, Response(), {}, limit=200, offset=0)
        b = await list_all_tools(_request(), db_session, Response(), {}, limit=200, offset=0)
    assert [_key(t) for t in a] == [_key(t) for t in b]


# ── /mcp/tools: cc visibility rule ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cc_tools_hidden_without_control_center_read(db_session) -> None:
    """FAILING-FIRST: cc tools used to leak into general browsing."""
    marker = uuid.uuid4().hex[:8]
    await _seed_server(db_session, "cc", 4)
    await _seed_server(db_session, f"supabase-{marker}", 3)

    response = Response()
    with _cc_gate(False):
        page = await list_all_tools(_request(), db_session, response, {}, limit=200, offset=0)

    assert all(tool.server_slug != "cc" for tool in page)
    assert int(response.headers["X-Total-Count"]) == len(page)


@pytest.mark.asyncio
async def test_cc_tools_listed_with_control_center_read(db_session) -> None:
    marker = uuid.uuid4().hex[:8]
    await _seed_server(db_session, "cc", 4)
    await _seed_server(db_session, f"supabase-{marker}", 3)

    with _cc_gate(True):
        page = await list_all_tools(_request(), db_session, Response(), {}, limit=200, offset=0)
    assert sum(1 for tool in page if tool.server_slug == "cc") == 4


# ── Individual tool resolution (referenced cc tools stay visible) ─────────────


@pytest.mark.asyncio
async def test_referenced_cc_tool_is_individually_resolvable(db_session) -> None:
    marker = uuid.uuid4().hex[:8]
    server = await _seed_server(db_session, "cc", 2)
    tool = (await _tools_of(db_session, server))[0]
    skill = Skill(tenant_id=None, name=f"cc-consumer-{marker}", description="d")
    db_session.add(skill)
    await db_session.flush()
    db_session.add(SkillToolBinding(skill_id=skill.id, tool_id=tool.id, order=0))
    await db_session.flush()

    with _cc_gate(False):
        read = await get_mcp_tool(
            tool.id, _request(f"/api/v1/mcp/tools/{tool.id}"), db_session, {}
        )
    assert read.id == tool.id
    assert read.server_slug == "cc"


@pytest.mark.asyncio
async def test_unreferenced_cc_tool_is_not_resolvable_without_read(db_session) -> None:
    server = await _seed_server(db_session, "cc", 3)
    unbound = (await _tools_of(db_session, server))[-1]

    with _cc_gate(False):
        with pytest.raises(HTTPException) as exc:
            await get_mcp_tool(
                unbound.id, _request(f"/api/v1/mcp/tools/{unbound.id}"), db_session, {}
            )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_non_cc_tool_is_resolvable(db_session) -> None:
    marker = uuid.uuid4().hex[:8]
    server = await _seed_server(db_session, f"supabase-{marker}", 1)
    tool = (await _tools_of(db_session, server))[0]

    with _cc_gate(False):
        read = await get_mcp_tool(
            tool.id, _request(f"/api/v1/mcp/tools/{tool.id}"), db_session, {}
        )
    assert read.id == tool.id


@pytest.mark.asyncio
async def test_decision_tools_appear_in_the_complete_listing(db_session) -> None:
    """Virtual ``decision`` tools are part of the full (non-truncated) listing."""
    from app.db.models.decision_tools import DecisionTool

    name = f"dec-{uuid.uuid4().hex[:8]}"
    db_session.add(DecisionTool(tenant_id=None, name=name, description="d", enabled=True))
    await db_session.flush()

    with _cc_gate(False):
        page = await list_all_tools(_request(), db_session, Response(), {}, limit=200, offset=0)
    decision = [tool for tool in page if tool.server_slug == "decision"]
    assert any(tool.name == f"decision____{name}" for tool in decision)


# ── /mcp/servers: filter BEFORE paginate ──────────────────────────────────────


async def _walk_servers(db, visible: bool, page_size: int):
    collected: list = []
    header_total: int | None = None
    offset = 0
    guard = 0
    while True:
        guard += 1
        assert guard < 100
        response = Response()
        with _cc_gate(visible):
            page = await list_mcp_servers(
                _request("/api/v1/mcp/servers"), db, response, limit=page_size, offset=offset
            )
        if header_total is None:
            header_total = int(response.headers["X-Total-Count"])
        collected.extend(page)
        if len(page) < page_size:
            break
        offset += len(page)
    return collected, int(header_total or 0)


@pytest.mark.asyncio
async def test_server_pagination_filters_cc_before_slicing(db_session) -> None:
    marker = uuid.uuid4().hex[:8]
    for index in range(7):
        await _seed_server(db_session, f"sv-{marker}-{index:02d}", 0)
    await _seed_server(db_session, "cc", 0)

    pages, total = await _walk_servers(db_session, visible=False, page_size=3)
    slugs = [server.slug for server in pages]
    assert "cc" not in slugs
    assert len(slugs) == len(set(slugs)), "server duplicated across pages"
    seeded = {f"sv-{marker}-{index:02d}" for index in range(7)}
    assert seeded <= set(slugs)
    assert total == len(pages)
    # Every DB page except the last must be FULL (filter applied before slice).
    db_only = [
        s for s in pages if s.id not in (SYSTEM_SERVER_ID, DECISION_SERVER_ID)
    ]
    assert len(db_only) == len({s.id for s in db_only})


@pytest.mark.asyncio
async def test_server_pagination_includes_cc_once_with_read(db_session) -> None:
    marker = uuid.uuid4().hex[:8]
    for index in range(4):
        await _seed_server(db_session, f"sv-{marker}-{index:02d}", 0)
    await _seed_server(db_session, "cc", 0)

    pages, total = await _walk_servers(db_session, visible=True, page_size=3)
    slugs = [server.slug for server in pages]
    assert slugs.count("cc") == 1
    assert len(slugs) == len(set(slugs))
    assert total == len(pages)
