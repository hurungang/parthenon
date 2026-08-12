"""
FIX-20260518-140000 — Issue 2: Inconsistent System Tool Naming Conventions

Reproduction tests. Demonstrates that the codebase uses two different naming
conventions for system tools simultaneously:

  - mcp_hub.py        → "system/save_result"  (with server prefix)
  - agent_data.py     → "save_result"          (bare name, no prefix)
  - runtime_executor  → "save_result"          (bare name, no prefix)

These tests do NOT fix anything — they expose the inconsistency so that
FIX-20260518-140000 has a clear test record to validate against.

Expected behaviour AFTER fix:
  All naming references use a single consistent convention (either all with
  prefix or all without). Each test below will pass once that is true.

Current (broken) behaviour:
  Naming differs across modules → tests that check for consistency FAIL.
"""
import pytest
from typing import Any


# ──────────────────────────────────────────────────────────────────────────────
# Helper: collect system tool names from each source of truth
# ──────────────────────────────────────────────────────────────────────────────

def get_mcp_hub_tool_names() -> list[str]:
    """Names returned by the virtual _system_tool_reads() in mcp_hub.py."""
    from app.api.v1.mcp_hub import _system_tool_reads
    return [t.name for t in _system_tool_reads()]


def get_agent_data_system_tools() -> set[str]:
    """_SYSTEM_TOOLS set declared in agent_data.py."""
    from app.api.v1.internal.agent_data import _SYSTEM_TOOLS  # type: ignore[attr-defined]
    return set(_SYSTEM_TOOLS)


def get_runtime_executor_tool_defs() -> dict[str, Any]:
    """Built-in tool schemas declared directly in runtime_executor.py."""
    from app.services.agents.runtime_executor import (  # type: ignore[attr-defined]
        _SAVE_RESULT_TOOL_DEF,
    )
    return {"save_result": _SAVE_RESULT_TOOL_DEF}


# ──────────────────────────────────────────────────────────────────────────────
# Issue 2a: mcp_hub uses "system/" prefix; agent_data uses bare names
# ──────────────────────────────────────────────────────────────────────────────

class TestSystemToolNamingConsistency:
    """
    Verifies that all sources agree on a single naming convention.
    These tests FAIL against the current codebase because the naming is split.
    """

    def test_mcp_hub_uses_system_prefix(self):
        """
        _system_tool_reads() in mcp_hub.py returns names like 'system/save_result'.
        After fix, this must remain true (or be changed consistently everywhere).
        This test documents the current contract.
        """
        names = get_mcp_hub_tool_names()
        assert len(names) == 3, "Expected exactly 3 virtual system tools"
        for name in names:
            assert name.startswith("system/"), (
                f"mcp_hub tool name '{name}' does not start with 'system/' — "
                "naming convention mismatch detected"
            )

    def test_agent_data_does_not_use_system_prefix(self):
        """
        _SYSTEM_TOOLS in agent_data.py uses bare names — NO 'system/' prefix.
        This documents the CURRENT (broken) state that diverges from mcp_hub.
        When the fix is applied, either this test changes or the set does.
        """
        tools = get_agent_data_system_tools()
        assert len(tools) >= 3, "Expected at least 3 entries in _SYSTEM_TOOLS"
        # Documents the bug: bare names are used here, not system-prefixed ones
        for name in tools:
            assert not name.startswith("system/"), (
                f"agent_data _SYSTEM_TOOLS entry '{name}' unexpectedly uses 'system/' prefix. "
                "Has the inconsistency already been fixed?"
            )

    def test_naming_is_consistent_across_modules(self):
        """
        FAILS against the current codebase.

        After fix, both mcp_hub and agent_data must use the SAME convention so
        that tool name lookup (e.g. is_system_tool()) works without split().
        """
        mcp_hub_bare = {n.split("/")[-1] for n in get_mcp_hub_tool_names()}
        agent_data_names = get_agent_data_system_tools()

        # Both sides should name the exact same set of tools
        assert mcp_hub_bare == agent_data_names, (
            f"Tool name mismatch between mcp_hub (bare: {mcp_hub_bare}) "
            f"and agent_data ({agent_data_names}). "
            "Fix required: adopt a single naming convention."
        )

        # Additionally, both should use the SAME format (prefixed or bare) —
        # not one of each. Check that mcp_hub full names match agent_data names.
        mcp_hub_full = set(get_mcp_hub_tool_names())
        assert mcp_hub_full == agent_data_names, (
            f"Naming formats differ: mcp_hub uses '{next(iter(mcp_hub_full))}' "
            f"but agent_data uses '{next(iter(agent_data_names))}'. "
            "One module must be updated to match the other."
        )

    def test_runtime_executor_save_result_def_uses_bare_name(self):
        """
        _SAVE_RESULT_TOOL_DEF in runtime_executor.py defines the tool schema
        with name 'save_result' (no prefix). Documents the inconsistency with
        mcp_hub which uses 'system/save_result'.
        """
        defs = get_runtime_executor_tool_defs()
        save_result_def = defs["save_result"]
        tool_name = save_result_def.get("name") if isinstance(save_result_def, dict) else getattr(save_result_def, "name", None)
        # Documents the current state (bare name, no prefix)
        assert tool_name is not None
        # After fix this assertion changes to match whatever canonical name is chosen
        assert not tool_name.startswith("system/"), (
            f"runtime_executor _SAVE_RESULT_TOOL_DEF name is '{tool_name}' "
            "which does NOT match the 'system/' prefix used in mcp_hub. "
            "Inconsistency confirmed — fix required."
        )

    def test_is_system_tool_must_accept_prefixed_name(self):
        """
        FAILS against the current codebase (or reveals fragile workaround).

        runtime_executor.is_system_tool() currently uses split('/') as a hack
        to handle both naming forms. After a proper fix, it should accept the
        canonical prefixed name 'system/save_result' without needing split().

        This test documents the requirement that the function works correctly
        with the fully-qualified name without relying on substring splitting.
        """
        from app.services.agents.runtime_executor import is_system_tool  # type: ignore[attr-defined]

        # Canonical prefixed name (as returned by mcp_hub)
        assert is_system_tool("system/save_result"), (
            "is_system_tool('system/save_result') must return True. "
            "Currently this only works via the split('/') workaround."
        )
        assert is_system_tool("system/send_notification"), (
            "is_system_tool('system/send_notification') must return True."
        )
        assert is_system_tool("system/get_recipient_group"), (
            "is_system_tool('system/get_recipient_group') must return True."
        )

        # Bare names must also continue to work (backwards compat until cleaned up)
        assert is_system_tool("save_result"), (
            "is_system_tool('save_result') must return True."
        )


# ──────────────────────────────────────────────────────────────────────────────
# Issue 2b: "system" slug not reserved in create_mcp_server
# ──────────────────────────────────────────────────────────────────────────────

class TestSystemSlugReservation:
    """
    The slug "system" is used by the virtual system server defined in mcp_hub.py.
    create_mcp_server() should reject a user-created server with slug "system",
    but currently it does NOT — any slug is accepted as long as it's not in the DB.
    These tests FAIL until the reservation check is added.
    """

    @pytest.mark.asyncio
    async def test_create_server_rejects_reserved_slug_system(self, async_client):
        """
        POST /mcp/servers with slug="system" should return 409 Conflict because
        "system" is a reserved slug used by built-in system tools.
        Currently returns 201 — test FAILS, demonstrating the gap.
        """
        payload = {
            "name": "Attacker Server",
            "slug": "system",
            "description": "Attempt to hijack the reserved system slug",
            "base_url": "http://evil.example.com",
        }
        response = await async_client.post("/api/v1/mcp/servers", json=payload)
        # EXPECTED (after fix): 409 Conflict — "system" slug is reserved
        # ACTUAL (broken): 201 Created — no reservation check exists
        assert response.status_code == 409, (
            f"Expected 409 (reserved slug), got {response.status_code}. "
            "create_mcp_server does not block the reserved 'system' slug."
        )
        detail = response.json().get("detail", "")
        assert "reserved" in detail.lower() or "system" in detail.lower(), (
            f"Error detail '{detail}' should mention that 'system' is a reserved slug."
        )

    @pytest.mark.asyncio
    async def test_create_server_allows_non_reserved_slugs(self, async_client):
        """Sanity check: non-reserved slugs must still be accepted."""
        payload = {
            "name": "Custom Server",
            "slug": "my-custom-server",
            "description": "A legitimate server",
            "base_url": "http://example.com",
        }
        response = await async_client.post("/api/v1/mcp/servers", json=payload)
        assert response.status_code in (201, 401, 403), (
            f"Expected 201 (or auth error), got {response.status_code}. "
            "Non-reserved slugs should be allowed."
        )
