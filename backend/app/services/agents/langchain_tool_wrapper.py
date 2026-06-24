"""LangChain Tool Wrapper — bridges CommHubToolClient to LangChain BaseTool.

Wraps MCP tool definitions (from ControlCenter context) into LangChain
StructuredTool instances that can be bound to ChatModel.bind_tools() or
passed to a LangGraph agent.

Key design points:
- Tool name sanitization: replaces '/' and ':' with '_' (LangChain requirement)
- Original name stored on instance for call dispatch via CommHubToolClient
- args_schema built dynamically from OpenAI tool definition JSON Schema
- _arun() dispatches via CommHubToolClient (mTLS-authenticated)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import StructuredTool

logger = logging.getLogger(__name__)


def _sanitize_tool_name(name: str) -> str:
    """Sanitize a tool name for LangChain (replace invalid chars with '_')."""
    sanitized = name.replace("/", "_").replace(":", "_").replace("-", "_").replace(".", "_")
    # Must start with alpha or underscore
    if sanitized and sanitized[0].isdigit():
        sanitized = f"tool_{sanitized}"
    return sanitized


def build_langchain_tools_from_definitions(
    tool_definitions: list[dict[str, Any]],
    comm_hub_client: Any,
    session_id: str,
    agent_type_id: str,
) -> list[StructuredTool]:
    """Convert OpenAI-format tool definitions to LangChain StructuredTool list.

    Args:
        tool_definitions: List of OpenAI-format tool defs:
            [{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}]
        comm_hub_client: CommHubToolClient instance for mTLS tool dispatch.
        session_id: Agent session ID (passed through to CommHubToolClient).
        agent_type_id: Agent type identifier (passed through to CommHubToolClient).

    Returns:
        List of LangChain StructuredTool instances ready for bind_tools().
    """
    tools: list[StructuredTool] = []
    for tool_def in tool_definitions:
        func_spec = tool_def.get("function") or {}
        original_name: str = func_spec.get("name", "")
        description: str = func_spec.get("description", "")
        parameters: dict[str, Any] = func_spec.get("parameters") or {"type": "object", "properties": {}}

        if not original_name:
            logger.warning("Skipping tool definition with no name: %s", tool_def)
            continue

        sanitized_name = _sanitize_tool_name(original_name)

        # Build a sync wrapper (LangChain requires _run to be sync)
        def _make_tool_func(orig_name: str, san_name: str) -> Any:
            async def _arun(**kwargs: Any) -> str:
                """Dispatch tool call to CommHub via mTLS-authenticated client."""
                try:
                    result = await comm_hub_client.call_tool(
                        tool_name=orig_name,
                        tool_args=kwargs,
                        session_id=session_id,
                        agent_type_id=agent_type_id,
                    )
                    if isinstance(result, (dict, list)):
                        return json.dumps(result)
                    return str(result)
                except Exception as exc:
                    logger.error(
                        "Tool call failed for '%s' (sanitized: '%s'): %s",
                        orig_name,
                        san_name,
                        exc,
                    )
                    return json.dumps({"error": str(exc), "tool": orig_name})

            def _run(**kwargs: Any) -> str:
                """Sync wrapper — runs async dispatch in event loop."""
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    return loop.run_until_complete(_arun(**kwargs))
                except Exception as exc:
                    return json.dumps({"error": str(exc), "tool": orig_name})

            return _run, _arun

        sync_fn, async_fn = _make_tool_func(original_name, sanitized_name)

        tool = StructuredTool.from_function(
            func=sync_fn,
            coroutine=async_fn,
            name=sanitized_name,
            description=description or f"Call the {original_name} tool.",
            args_schema=_schema_to_pydantic(sanitized_name, parameters),
            return_direct=False,
        )
        # Attach original name for reverse-mapping
        tool.metadata = tool.metadata or {}
        tool.metadata["original_name"] = original_name
        tools.append(tool)

    return tools


def _schema_to_pydantic(tool_name: str, parameters: dict[str, Any]) -> Any:
    """Build a Pydantic v2 model from a JSON Schema parameters dict.

    Falls back to a permissive Any-typed model on schema parse errors.
    """
    try:
        from pydantic import BaseModel, create_model
        from pydantic.fields import FieldInfo

        props: dict[str, Any] = parameters.get("properties") or {}
        required_fields: list[str] = parameters.get("required") or []

        field_definitions: dict[str, Any] = {}
        for field_name, field_schema in props.items():
            py_type = _json_type_to_python(field_schema.get("type", "string"))
            description = field_schema.get("description", "")
            if field_name in required_fields:
                field_definitions[field_name] = (py_type, FieldInfo(description=description))
            else:
                field_definitions[field_name] = (
                    py_type | None,
                    FieldInfo(default=None, description=description),
                )

        if not field_definitions:
            return None  # StructuredTool accepts None → no args schema

        model_class = create_model(
            f"{tool_name}_Args",
            __base__=BaseModel,
            **field_definitions,
        )
        return model_class

    except Exception as exc:
        logger.warning("Failed to build Pydantic schema for tool '%s': %s", tool_name, exc)
        return None


def _json_type_to_python(json_type: str) -> type:
    """Map JSON Schema type to Python type for Pydantic field creation."""
    mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
        "null": type(None),
    }
    return mapping.get(json_type, str)
