from __future__ import annotations

from unittest.mock import MagicMock

from app.services.agents.langchain_system_tools import (
    LangChainGetDataTool,
    LangChainGetOutputTool,
    LangChainSaveDataTool,
)
from app.services.agents.system_tool_registry import SystemToolRegistry
from app.services.system_tools import is_system_tool


def test_langchain_save_data_tool_definition() -> None:
    tool = LangChainSaveDataTool(
        comm_hub_client=MagicMock(),
        session_id="session-1",
        agent_type_id="agent-type-1",
    )

    schema = tool.args_schema.model_json_schema()

    assert tool.name == "save_data"
    assert "Save named intermediate data" in tool.description
    assert "data_name" in schema["properties"]
    assert "data_value" in schema["properties"]
    assert "data_type" in schema["properties"]


def test_langchain_get_data_tool_definition() -> None:
    tool = LangChainGetDataTool(
        comm_hub_client=MagicMock(),
        session_id="session-1",
        agent_type_id="agent-type-1",
    )

    schema = tool.args_schema.model_json_schema()

    assert tool.name == "get_data"
    assert "data_name" in schema["properties"]
    assert "agent_type_id" in schema["properties"]
    assert "session_id" in schema["properties"]
    assert "limit" in schema["properties"]


def test_langchain_get_output_tool_definition() -> None:
    tool = LangChainGetOutputTool(
        comm_hub_client=MagicMock(),
        session_id="session-1",
        agent_type_id="agent-type-1",
    )

    schema = tool.args_schema.model_json_schema()

    assert tool.name == "get_output"
    assert "agent_type_id" in schema["properties"]
    assert "session_id" in schema["properties"]
    assert "date_from" in schema["properties"]
    assert "date_to" in schema["properties"]
    assert "limit" in schema["properties"]


def test_system_tool_registry_contains_new_tools_and_excludes_save_result() -> None:
    names = SystemToolRegistry.get_names()

    assert "save_data" in names
    assert "get_data" in names
    assert "get_output" in names
    assert "save_result" not in names


def test_system_tools_name_resolution_matches_new_contract() -> None:
    assert is_system_tool("save_data") is True
    assert is_system_tool("save_result") is False
