"""Unit tests for app.services.agents.tool_naming."""
from __future__ import annotations

import pytest

from app.services.agents.tool_naming import (
    TOOL_SEPARATOR,
    RESERVED_SERVER_NAMES,
    build_tool_name,
    get_bare_tool_name,
    get_server_name,
    is_system_tool,
    parse_tool_name,
)


# ── build_tool_name ───────────────────────────────────────────────────────────


class TestBuildToolName:
    def test_system_save_data(self) -> None:
        assert build_tool_name("system", "save_data") == "system____save_data"

    def test_mcp_tool(self) -> None:
        assert build_tool_name("hello-world", "helloWorld") == "hello-world____helloWorld"

    def test_separator_constant(self) -> None:
        result = build_tool_name("a", "b")
        assert TOOL_SEPARATOR in result
        assert result == f"a{TOOL_SEPARATOR}b"

    def test_arbitrary_server_and_tool(self) -> None:
        assert build_tool_name("github", "list_prs") == "github____list_prs"


# ── parse_tool_name ───────────────────────────────────────────────────────────


class TestParseToolName:
    # Canonical format
    def test_canonical_system_save_data(self) -> None:
        assert parse_tool_name("system____save_data") == ("system", "save_data")

    def test_canonical_system_send_notification(self) -> None:
        assert parse_tool_name("system____send_notification") == ("system", "send_notification")

    def test_canonical_system_get_recipient_group(self) -> None:
        assert parse_tool_name("system____get_recipient_group") == ("system", "get_recipient_group")

    def test_canonical_mcp_tool(self) -> None:
        assert parse_tool_name("hello-world____helloWorld") == ("hello-world", "helloWorld")

    def test_round_trip_with_build(self) -> None:
        name = build_tool_name("my-server", "my_tool")
        assert parse_tool_name(name) == ("my-server", "my_tool")

    # Legacy bare-name fallback
    def test_legacy_save_data(self) -> None:
        assert parse_tool_name("save_data") == ("system", "save_data")

    def test_legacy_send_notification(self) -> None:
        assert parse_tool_name("send_notification") == ("system", "send_notification")

    def test_legacy_get_recipient_group(self) -> None:
        assert parse_tool_name("get_recipient_group") == ("system", "get_recipient_group")

    # Error cases
    def test_multiple_separators_raises(self) -> None:
        with pytest.raises(ValueError, match="multiple"):
            parse_tool_name("a____b____c")

    def test_empty_server_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            parse_tool_name("____tool")

    def test_empty_tool_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            parse_tool_name("server____")

    def test_unknown_bare_name_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_tool_name("not_a_system_tool")

    def test_arbitrary_string_without_separator_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_tool_name("justAName")


# ── is_system_tool ────────────────────────────────────────────────────────────


class TestIsSystemTool:
    # Canonical format — all should return True
    @pytest.mark.parametrize(
        "name",
        [
            "system____save_data",
            "system____send_notification",
            "system____get_recipient_group",
        ],
    )
    def test_canonical_system_tools_are_system(self, name: str) -> None:
        assert is_system_tool(name) is True

    # Legacy bare names — all should return True
    @pytest.mark.parametrize(
        "name",
        [
            "save_data",
            "send_notification",
            "get_recipient_group",
        ],
    )
    def test_legacy_bare_names_are_system(self, name: str) -> None:
        assert is_system_tool(name) is True

    # Old display format (system/) — backward compat
    @pytest.mark.parametrize(
        "name",
        [
            "system/save_data",
            "system/send_notification",
            "system/get_recipient_group",
        ],
    )
    def test_old_slash_format_is_system(self, name: str) -> None:
        assert is_system_tool(name) is True

    # Old OpenAI-sanitised format (system_) — backward compat
    @pytest.mark.parametrize(
        "name",
        [
            "system_save_data",
            "system_send_notification",
            "system_get_recipient_group",
        ],
    )
    def test_old_underscore_prefix_is_system(self, name: str) -> None:
        assert is_system_tool(name) is True

    # MCP tools — should return False
    @pytest.mark.parametrize(
        "name",
        [
            "hello-world____helloWorld",
            "github____list_prs",
            "save_results",           # typo — not a system tool
        ],
    )
    def test_mcp_tools_not_system(self, name: str) -> None:
        assert is_system_tool(name) is False


# ── get_server_name ───────────────────────────────────────────────────────────


class TestGetServerName:
    def test_canonical_system_tool(self) -> None:
        assert get_server_name("system____save_data") == "system"

    def test_mcp_tool(self) -> None:
        assert get_server_name("hello-world____helloWorld") == "hello-world"

    def test_legacy_bare_name(self) -> None:
        assert get_server_name("save_data") == "system"

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError):
            get_server_name("not_a_known_tool")


# ── get_bare_tool_name ────────────────────────────────────────────────────────


class TestGetBareToolName:
    def test_canonical_system_tool(self) -> None:
        assert get_bare_tool_name("system____save_data") == "save_data"

    def test_mcp_tool(self) -> None:
        assert get_bare_tool_name("hello-world____helloWorld") == "helloWorld"

    def test_legacy_bare_name(self) -> None:
        assert get_bare_tool_name("save_data") == "save_data"

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError):
            get_bare_tool_name("not_a_known_tool")


# ── RESERVED_SERVER_NAMES ─────────────────────────────────────────────────────


class TestReservedServerNames:
    def test_system_is_reserved(self) -> None:
        assert "system" in RESERVED_SERVER_NAMES

    def test_frozenset(self) -> None:
        assert isinstance(RESERVED_SERVER_NAMES, frozenset)
