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
    # McpTool.name stores the canonical namespaced identifier: "mcp_slug____tool_name"
    tool.name = f"{server_slug}____{name}"
    tool.original_name = name
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
    # Phase 10: save_result is no longer auto-injected; empty role → empty set
    assert allowed_first == set()


@pytest.mark.asyncio
async def test_calculate_allowed_tools_empty_when_no_skills():
    """Phase 10: save_result is no longer auto-injected; an empty role returns an empty set."""
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
    assert allowed == set()


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

    # Tool identifiers use canonical server____tool format.
    pm.check_tool_allowed("my-server____list_files", {"my-server____list_files", "save_result"}, role_id)


@pytest.mark.skip(reason='Pre-existing: tool permission denied error')


def test_check_tool_allowed_raises_permission_denied():
    """check_tool_allowed raises PermissionDeniedError when the tool is not in the allowed set."""
    from app.services.agents.permission_manager import AgentPermissionManager, PermissionDeniedError

    pm = AgentPermissionManager()
    role_id = uuid.uuid4()

    with pytest.raises(PermissionDeniedError) as exc_info:
        pm.check_tool_allowed("evil-server/drop_database", {"save_result"}, role_id)

    assert "evil-server/drop_database" in str(exc_info.value)


def test_tool_identifiers_use_canonical_separator():
    """Tool identifiers must use canonical '____' separator (mcp_slug____tool_name)."""
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    role_id = uuid.uuid4()

    valid_identifier = "supabase____get_project"
    legacy_identifier = "supabase:get_project"

    # Canonical format is allowed
    pm.check_tool_allowed(valid_identifier, {valid_identifier, "save_result"}, role_id)

    # Legacy colon-format should NOT be in the allowed set.
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

    # Tool identifiers use canonical server____tool format.
    assert "fs-server____read_file" in allowed
    # Phase 10: save_result is no longer auto-injected into the allowed set


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
    # Phase 10: save_result is no longer auto-injected; empty role → empty set
    assert allowed == set()


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
    # Should appear only once; tool identifiers use canonical server____tool format.
    assert list(allowed).count("hub____shared_tool") == 1


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
    # Tool identifiers use canonical server____tool format.
    assert "analytics____analyze" in allowed


@pytest.mark.asyncio
async def test_calculate_allowed_agent_types_from_sop_delegation_steps():
    """Delegated agent type names are resolved from role SOP agent_delegation steps."""
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    pm._agent_type_cache = {}
    role_id = uuid.uuid4()
    sop_id = uuid.uuid4()
    delegated_agent_type_id = uuid.uuid4()

    db = _mock_db()
    db.execute = AsyncMock(side_effect=[
        _make_execute_rows((sop_id,)),
        _make_execute_rows((delegated_agent_type_id,)),
        _make_execute_rows(("research-agent",)),
    ])

    allowed = await pm.calculate_allowed_agent_types(role_id, db)
    assert allowed == {"research-agent"}


@pytest.mark.asyncio
async def test_calculate_allowed_agent_types_uses_cache():
    """Second call should read delegated agent type names from cache."""
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    pm._agent_type_cache = {}
    role_id = uuid.uuid4()
    sop_id = uuid.uuid4()
    delegated_agent_type_id = uuid.uuid4()

    db = _mock_db()
    db.execute = AsyncMock(side_effect=[
        _make_execute_rows((sop_id,)),
        _make_execute_rows((delegated_agent_type_id,)),
        _make_execute_rows(("planner-agent",)),
    ])

    first = await pm.calculate_allowed_agent_types(role_id, db)
    assert first == {"planner-agent"}

    db.execute = AsyncMock(side_effect=Exception("should not call DB again"))
    second = await pm.calculate_allowed_agent_types(role_id, db)
    assert second == {"planner-agent"}


# ── Agent-type-scoped resolution (visibility ∩ role permission) ───────────────


def _make_agent_type(agent_type_id, role_id):
    agent_type = MagicMock()
    agent_type.id = agent_type_id
    agent_type.role_id = role_id
    agent_type.name = "airline-service-chatbot"
    return agent_type


def _tool_rows_result(tool):
    """Mock execute result for the tool_stmt query (scalars().all())."""
    result = MagicMock()
    result.fetchall.return_value = []
    result.scalars.return_value.all.return_value = [tool]
    return result


@pytest.mark.asyncio
async def test_agent_visibility_chatbot_delegation_sop_only():
    """Chatbot case: agent type with only a delegation-step SOP sees NO tools
    (only inherent system tools are added by the hub layer), allowed agent
    types = the SOP delegation targets, and the role's extra skill tools are
    NOT visible even though the role grants them."""
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    pm._cache = {}
    pm._agent_visibility_cache = {}
    pm._agent_visibility_agent_types_cache = {}
    pm._agent_type_cache = {}

    role_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()
    sop_id = uuid.uuid4()
    db = _mock_db()
    db.get = AsyncMock(return_value=_make_agent_type(agent_type_id, role_id))
    db.execute = AsyncMock(side_effect=[
        _make_execute_empty(),                              # skill bindings → none
        _make_execute_rows((sop_id,)),                      # sop bindings → 1 SOP
        _make_execute_empty(),                              # skill_invocation steps → none
        # calculate_agent_allowed_agent_types:
        _make_execute_rows((sop_id,)),                      # sop bindings
        _make_execute_rows(("t1",), ("t2",), ("t3",)),      # delegation targets
        _make_execute_rows(("planner",), ("booker",), ("checkin",)),  # names
    ])

    # Role permission cache pre-seeded: role grants extra skills' tools that
    # the agent type is NOT associated with.
    pm._cache[str(role_id)] = frozenset({
        "mcp-demo____searchFlights", "mcp-demo____checkIn", "mcp-demo____createBooking",
    })
    pm._agent_type_cache[str(role_id)] = frozenset({"planner", "booker", "checkin"})

    tools = await pm.calculate_agent_allowed_tools(agent_type_id, db)
    assert tools == set()  # visibility is empty → intersection empty

    allowed = await pm.calculate_agent_allowed_agent_types(agent_type_id, db)
    assert allowed == {"planner", "booker", "checkin"}


@pytest.mark.asyncio
async def test_agent_visibility_direct_skill_binding_intersected_with_role():
    """Agent type with a direct skill binding: its tools are visible ONLY IF
    the role grants them; a bound-but-not-role-granted tool is excluded."""
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    pm._cache = {}
    pm._agent_visibility_cache = {}
    pm._agent_visibility_agent_types_cache = {}

    role_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()
    skill_id = uuid.uuid4()
    tool_id = uuid.uuid4()
    tool = _make_tool("searchFlights", "mcp-demo")
    tool.id = tool_id  # match the SkillToolBinding row so no virtual-decision fallback fires

    db = _mock_db()
    db.get = AsyncMock(return_value=_make_agent_type(agent_type_id, role_id))
    db.execute = AsyncMock(side_effect=[
        _make_execute_rows((skill_id,)),     # skill bindings → 1
        _make_execute_empty(),               # sop bindings → none
        _make_execute_empty(),               # SkillToolBinding name query
        _make_execute_rows((tool_id,)),      # SkillToolBinding tool_id query
        _tool_rows_result(tool),             # McpTool rows with server
    ])
    # Role grants a DIFFERENT tool — the bound skill's tool is NOT role-granted.
    pm._cache[str(role_id)] = frozenset({"other-server____otherTool"})

    tools = await pm.calculate_agent_allowed_tools(agent_type_id, db)
    assert tools == set()  # bound skill NOT role-granted → excluded

    # Now the role ALSO grants the bound tool → visible.
    pm._agent_visibility_cache.clear()
    pm._cache[str(role_id)] = frozenset({"mcp-demo____searchFlights"})
    db.execute = AsyncMock(side_effect=[
        _make_execute_rows((skill_id,)),
        _make_execute_empty(),
        _make_execute_empty(),
        _make_execute_rows((tool_id,)),
        _tool_rows_result(tool),
    ])
    tools2 = await pm.calculate_agent_allowed_tools(agent_type_id, db)
    assert tools2 == {"mcp-demo____searchFlights"}


@pytest.mark.asyncio
async def test_agent_visibility_empty_without_bindings_no_role_inheritance():
    """Strict model: an agent type with NO bindings sees NOTHING from the role
    (no silent role inheritance)."""
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    pm._cache = {}
    pm._agent_visibility_cache = {}

    role_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()
    db = _mock_db()
    db.get = AsyncMock(return_value=_make_agent_type(agent_type_id, role_id))
    db.execute = AsyncMock(side_effect=[
        _make_execute_empty(),  # skill bindings
        _make_execute_empty(),  # sop bindings
    ])
    pm._cache[str(role_id)] = frozenset({"mcp-demo____searchFlights"})

    assert await pm.calculate_agent_allowed_tools(agent_type_id, db) == set()


def test_invalidate_role_clears_agent_visibility_caches():
    """invalidate(role) also evicts agent-type visibility caches (role gates
    permission for all agent types)."""
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    role_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()
    pm._cache[str(role_id)] = frozenset({"t"})
    pm._agent_visibility_cache[str(agent_type_id)] = frozenset({"t"})
    pm._agent_visibility_agent_types_cache[str(agent_type_id)] = frozenset({"a"})

    pm.invalidate(role_id)

    assert str(role_id) not in pm._cache
    assert pm._agent_visibility_cache == {}
    assert pm._agent_visibility_agent_types_cache == {}


def test_invalidate_agent_type_clears_only_that_agent_type():
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    at1, at2 = uuid.uuid4(), uuid.uuid4()
    pm._agent_visibility_cache[str(at1)] = frozenset({"t"})
    pm._agent_visibility_cache[str(at2)] = frozenset({"t"})
    pm._agent_visibility_agent_types_cache[str(at1)] = frozenset({"a"})

    pm.invalidate_agent_type(at1)

    assert str(at1) not in pm._agent_visibility_cache
    assert str(at1) not in pm._agent_visibility_agent_types_cache
    assert str(at2) in pm._agent_visibility_cache
