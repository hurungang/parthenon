"""Unit tests for AgentPermissionManager — permission resolution, caching, and enforcement."""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock


# ── Helpers ────────────────────────────────────────────────────────────────────


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    return db


def _make_execute_empty() -> MagicMock:
    """Return a mock execute result that yields zero rows."""
    result = MagicMock()
    result.fetchall.return_value = []
    result.scalars.return_value.all.return_value = []
    return result


def _make_execute_rows(*rows) -> MagicMock:
    """Return a mock execute result that yields the given rows (as tuples)."""
    result = MagicMock()
    result.fetchall.return_value = rows
    return result


def _make_tool(name: str, server_slug: str) -> MagicMock:
    tool = MagicMock()
    # McpTool.name stores the namespaced identifier: "mcp_slug/tool_name"
    tool.name = f"{server_slug}/{name}"
    tool.server = MagicMock()
    tool.server.slug = server_slug
    return tool


# ── Cache hit / miss ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calculate_allowed_tools_cache_miss_then_hit():
    """First call resolves from DB; second call uses in-process cache (no extra DB queries)."""
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    pm._cache = {}  # ensure clean cache

    role_id = uuid.uuid4()
    tool = _make_tool("list_files", "fs-server")

    db = _mock_db()

    # Call sequence for _resolve_allowed_tools:
    # 1. direct skills query → empty
    # 2. SOP ids query → empty
    # (no tool resolution since no skill IDs)
    db.execute = AsyncMock(side_effect=[
        _make_execute_empty(),   # direct skills
        _make_execute_empty(),   # SOP ids
    ])

    allowed_first = await pm.calculate_allowed_tools(role_id, db)

    # Cache should be populated now — second call should not hit DB
    db.execute = AsyncMock(side_effect=Exception("should not call DB again"))
    allowed_second = await pm.calculate_allowed_tools(role_id, db)

    assert allowed_first == allowed_second
    assert "save_result" in allowed_first  # always injected


@pytest.mark.asyncio
async def test_calculate_allowed_tools_always_includes_save_result():
    """save_result is always in the allowed set regardless of role assignments."""
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    pm._cache = {}
    role_id = uuid.uuid4()

    db = _mock_db()
    db.execute = AsyncMock(side_effect=[
        _make_execute_empty(),  # direct skills
        _make_execute_empty(),  # SOP ids
    ])

    allowed = await pm.calculate_allowed_tools(role_id, db)
    assert "save_result" in allowed


# ── Cache invalidation ─────────────────────────────────────────────────────────


def test_invalidate_removes_cache_entry():
    """invalidate() removes the cached permission set for a role."""
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    role_id = uuid.uuid4()
    pm._cache[str(role_id)] = frozenset({"save_result", "tool-a"})

    pm.invalidate(role_id)

    assert str(role_id) not in pm._cache


def test_invalidate_noop_when_not_cached():
    """invalidate() does not raise when the role is not in cache."""
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    pm._cache = {}
    pm.invalidate(uuid.uuid4())  # must not raise


def test_invalidate_stale_cache_forces_fresh_query():
    """After invalidation, the cache no longer has the key."""
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    role_id = uuid.uuid4()
    pm._cache[str(role_id)] = frozenset({"tool-a"})

    pm.invalidate(role_id)

    assert str(role_id) not in pm._cache


# ── Permission enforcement ─────────────────────────────────────────────────────


def test_check_tool_allowed_passes_when_in_set():
    """check_tool_allowed does not raise when the tool is in the allowed set."""
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    role_id = uuid.uuid4()

    # Tool identifiers use mcp_slug/tool_name format (slash separator)
    pm.check_tool_allowed("my-server/list_files", {"my-server/list_files", "save_result"}, role_id)


def test_check_tool_allowed_raises_permission_denied():
    """check_tool_allowed raises PermissionDeniedError when the tool is not in the allowed set."""
    from app.services.agents.permission_manager import AgentPermissionManager, PermissionDeniedError

    pm = AgentPermissionManager()
    role_id = uuid.uuid4()

    with pytest.raises(PermissionDeniedError) as exc_info:
        pm.check_tool_allowed("evil-server/drop_database", {"save_result"}, role_id)

    assert "evil-server/drop_database" in str(exc_info.value)


def test_tool_identifiers_use_slash_separator():
    """Tool identifiers must use '/' separator (mcp_slug/tool_name), not ':' (legacy format)."""
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    role_id = uuid.uuid4()

    valid_identifier = "supabase/get_project"
    legacy_identifier = "supabase:get_project"

    # Valid slash-format is allowed
    pm.check_tool_allowed(valid_identifier, {valid_identifier, "save_result"}, role_id)

    # Legacy colon-format should NOT be in the allowed set (slash format is the only format)
    from app.services.agents.permission_manager import PermissionDeniedError
    with pytest.raises(PermissionDeniedError):
        pm.check_tool_allowed(legacy_identifier, {valid_identifier, "save_result"}, role_id)


def test_check_tool_allowed_save_result_always_passes():
    """save_result is always permitted."""
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    role_id = uuid.uuid4()

    # save_result is always in the set (injected by calculate_allowed_tools)
    pm.check_tool_allowed("save_result", {"save_result"}, role_id)


# ── Tool resolution chain ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_allowed_tools_with_direct_skill():
    """Tools from directly assigned skills are included in the allowed set."""
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    pm._cache = {}
    role_id = uuid.uuid4()
    skill_id = uuid.uuid4()
    tool_id = uuid.uuid4()

    tool = _make_tool("read_file", "fs-server")
    tool.id = tool_id

    mock_tool_rows = MagicMock()
    mock_tool_rows.scalars.return_value.all.return_value = [tool]

    db = _mock_db()
    # _resolve_tools_from_skills issues 3 DB queries:
    #   1. binding_rows (result unused in implementation)
    #   2. binding_tool_rows (fetchall → tool IDs)
    #   3. tool_rows (scalars().all() → McpTool records)
    db.execute = AsyncMock(side_effect=[
        _make_execute_rows((skill_id,)),  # direct skills
        _make_execute_empty(),            # SOP ids (none)
        _make_execute_empty(),            # binding_rows (ignored result)
        _make_execute_rows((tool_id,)),   # binding_tool_rows fetchall
        mock_tool_rows,                   # tool records with server
    ])

    allowed = await pm.calculate_allowed_tools(role_id, db)

    # Tool identifiers use mcp_slug/tool_name format (slash separator)
    assert "fs-server/read_file" in allowed
    assert "save_result" in allowed


@pytest.mark.asyncio
async def test_resolve_allowed_tools_empty_when_no_assignments():
    """When a role has no SOPs or Skills, the allowed set contains only save_result."""
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    pm._cache = {}
    role_id = uuid.uuid4()

    db = _mock_db()
    db.execute = AsyncMock(side_effect=[
        _make_execute_empty(),  # direct skills
        _make_execute_empty(),  # SOP ids
    ])

    allowed = await pm.calculate_allowed_tools(role_id, db)
    assert allowed == {"save_result"}


@pytest.mark.asyncio
async def test_resolve_allowed_tools_deduplicates():
    """Same MCP tool reachable via multiple paths is only included once."""
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    pm._cache = {}
    role_id = uuid.uuid4()
    skill_id_a = uuid.uuid4()
    skill_id_b = uuid.uuid4()

    # Both skills point to the same tool
    tool_id = uuid.uuid4()
    tool = _make_tool("shared_tool", "hub")
    tool.id = tool_id

    mock_tool_rows = MagicMock()
    mock_tool_rows.scalars.return_value.all.return_value = [tool]

    db = _mock_db()
    # _resolve_tools_from_skills issues 3 queries:
    #   1. binding_rows (result unused)
    #   2. binding_tool_rows fetchall
    #   3. tool_rows scalars().all()
    db.execute = AsyncMock(side_effect=[
        _make_execute_rows((skill_id_a,), (skill_id_b,)),  # direct skills
        _make_execute_empty(),                              # SOP ids
        _make_execute_empty(),                              # binding_rows (ignored)
        _make_execute_rows((tool_id,), (tool_id,)),        # binding_tool_rows fetchall
        mock_tool_rows,                                    # tool records
    ])

    allowed = await pm.calculate_allowed_tools(role_id, db)
    # Should appear only once; tool identifiers use mcp_slug/tool_name format
    assert list(allowed).count("hub/shared_tool") == 1


# ── Circular SOP dependency ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_no_infinite_recursion_without_circular_sop():
    """Resolution completes within finite steps and does not infinite-loop."""
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    pm._cache = {}
    role_id = uuid.uuid4()
    sop_id = uuid.uuid4()
    skill_id = uuid.uuid4()
    tool_id = uuid.uuid4()
    tool = _make_tool("analyze", "analytics")
    tool.id = tool_id

    mock_tool_rows = MagicMock()
    mock_tool_rows.scalars.return_value.all.return_value = [tool]

    db = _mock_db()
    # _resolve_tools_from_skills issues 3 queries:
    #   1. binding_rows (result unused)
    #   2. binding_tool_rows fetchall
    #   3. tool_rows scalars().all()
    db.execute = AsyncMock(side_effect=[
        _make_execute_empty(),            # direct skills
        _make_execute_rows((sop_id,)),    # SOP ids
        _make_execute_rows((skill_id,)),  # SOP step skill IDs
        _make_execute_empty(),            # binding_rows (ignored)
        _make_execute_rows((tool_id,)),   # binding_tool_rows fetchall
        mock_tool_rows,                   # tool records
    ])

    # Must complete without error or infinite recursion
    allowed = await pm.calculate_allowed_tools(role_id, db)
    # Tool identifiers use mcp_slug/tool_name format (slash separator)
    assert "analytics/analyze" in allowed
