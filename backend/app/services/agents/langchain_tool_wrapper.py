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


def _is_save_result_tool(tool_name: str) -> bool:
    """Return True if this tool name is a save_result variant (canonicalized)."""
    bare = tool_name
    for prefix in ("system____", "system/", "system\\"):
        bare = bare.replace(prefix, "")
    return bare == "save_result"


def _extract_delegation_target_slug(tool_name: str) -> str | None:
    """Return the target agent slug if tool_name is an agent delegation tool, else None.

    Handles both canonical ``agent____<slug>`` (4-underscore) and
    sanitized ``agent__<slug>`` (2-underscore) formats produced by tool
    name sanitization.
    """
    if tool_name.startswith("agent____") and len(tool_name) > len("agent____"):
        return tool_name[len("agent____"):]
    if tool_name.startswith("agent__") and len(tool_name) > len("agent__"):
        candidate = tool_name[len("agent__"):]
        # Exclude false positives like "agent__type_id" for system-like names
        # A delegation slug never contains more than two underscores in a row
        if "____" not in candidate:
            return candidate
    return None


def build_langchain_tools_for_ar_path(
    tool_definitions: list[dict[str, Any]],
    comm_hub_client: Any,
    data_client: Any,
    session_id: str,
    agent_type_id: str,
    conv_session_id: str | None = None,
    save_result_output: dict[str, Any] | None = None,
    tool_name_map: dict[str, str] | None = None,
    role_id: str | None = None,
) -> list[Any]:
    """Build LangChain tools for the Agent Runtime path.

    All tools are routed through CommHubToolClient (which handles permission
    checking and routing server-side) with three special cases:

    - ``human_intervene``: Uses LangGraph ``interrupt()`` to pause agent execution.
    - ``save_result`` variants: Captures output data into ``save_result_output``
      *and* submits result to Control Center via ``data_client``.
    - ``agent____<slug>`` delegation tools: Routes via CommHub A2A endpoint
      (``/internal/a2a/request``) instead of the generic tool route.

    Args:
        tool_definitions: OpenAI-format tool definition list from context.
        comm_hub_client: CommHubToolClient instance (mTLS-configured).
        data_client: ControlCenterDataClient for submitting results.
        session_id: Agent session UUID as string.
        role_id: Requester role ID for A2A delegation authorization.
        agent_type_id: Agent type UUID as string.
        conv_session_id: Parent conversation session ID (for HITL context).
        save_result_output: Mutable dict updated when save_result is called.
        tool_name_map: Optional mapping of OpenAI-sanitised (2-underscore) tool
            names to their canonical (4-underscore) equivalents.  CommHub
            expects the canonical format; this map performs the reverse lookup.

    Returns:
        List of LangChain StructuredTool / BaseTool instances.
    """
    from app.services.agents.langchain_system_tools import LangChainHumanInterveneTool

    if save_result_output is None:
        save_result_output = {}

    tools: list[Any] = []

    for tool_def in tool_definitions:
        func_spec = tool_def.get("function") or {}
        original_name: str = func_spec.get("name", "")
        description: str = func_spec.get("description", "")
        parameters: dict[str, Any] = func_spec.get("parameters") or {
            "type": "object",
            "properties": {},
        }

        if not original_name:
            logger.warning("Skipping tool definition with no name: %s", tool_def)
            continue

        # ── human_intervene: special HITL tool with LangGraph interrupt() ────
        if original_name == "human_intervene":
            tool = LangChainHumanInterveneTool(
                comm_hub_client=comm_hub_client,
                session_id=session_id,
                agent_type_id=agent_type_id,
                conv_session_id=conv_session_id,
            )
            tools.append(tool)
            continue

        # ── save_result variants: capture output + submit to CC ────────────────
        if _is_save_result_tool(original_name):
            sanitized_name = _sanitize_tool_name(original_name)
            captured = save_result_output  # closure reference

            def _make_save_result_tool(orig: str, san: str) -> tuple:
                async def _arun(**kwargs: Any) -> str:
                    try:
                        structured_data: dict[str, Any] = kwargs.get("data") or {}
                        output = {
                            "result": kwargs.get("content", ""),
                            "title": kwargs.get("title", ""),
                            **structured_data,
                        }
                        captured.update(output)
                        # Submit to Control Center
                        import uuid as _uuid
                        await data_client.submit_result(
                            _uuid.UUID(session_id) if session_id else None,
                            output,
                        )
                        return json.dumps({"status": "saved"})
                    except Exception as exc:
                        logger.error("save_result tool failed for session %s: %s", session_id, exc)
                        return json.dumps({"error": str(exc)})

                def _run(**kwargs: Any) -> str:
                    import asyncio
                    try:
                        return asyncio.get_event_loop().run_until_complete(_arun(**kwargs))
                    except Exception as exc:
                        return json.dumps({"error": str(exc)})

                return _run, _arun

            sync_fn, async_fn = _make_save_result_tool(original_name, sanitized_name)
            tool = StructuredTool.from_function(
                func=sync_fn,
                coroutine=async_fn,
                name=sanitized_name,
                description=description or "Save the final result of the task.",
                args_schema=_schema_to_pydantic(sanitized_name, parameters),
                return_direct=False,
            )
            tool.metadata = tool.metadata or {}
            tool.metadata["original_name"] = original_name
            tools.append(tool)
            continue

        # ── Agent delegation tools: route via A2A endpoint ─────────────────────
        target_slug = _extract_delegation_target_slug(original_name)
        if target_slug is not None:
            sanitized_name = _sanitize_tool_name(original_name)

            def _make_delegation_tool(slug: str, orig_name: str) -> tuple:
                async def _arun(**kwargs: Any) -> str:
                    import uuid as _uuid
                    try:
                        request_payload: dict[str, Any] = {}
                        rp = kwargs.get("request_payload")
                        if isinstance(rp, dict):
                            request_payload = rp
                        else:
                            request_payload = {
                                k: v for k, v in kwargs.items() if k != "session_link_id"
                            }
                        session_link_id: str | None = kwargs.get("session_link_id")  # type: ignore[assignment]

                        # Log delegation_started
                        try:
                            await data_client.log_execution_event(
                                session_id=_uuid.UUID(session_id),
                                event_type="delegation_started",
                                message=f"Delegating task to agent: {slug}",
                                data={
                                    "delegation_target": slug,
                                    "sub_agent": slug,
                                    "request_payload": request_payload,
                                },
                            )
                        except Exception:
                            pass

                        result = await comm_hub_client.call_a2a_request(
                            target_agent_type_slug=slug,
                            session_id=session_id,
                            requester_role_id=role_id,
                            request_payload=request_payload,
                            session_link_id=session_link_id,
                            wait_for_response=True,
                            wait_timeout_seconds=1800.0,
                            conv_session_id=conv_session_id,
                        )

                        # Log delegation_resumed
                        try:
                            await data_client.log_execution_event(
                                session_id=_uuid.UUID(session_id),
                                event_type="delegation_resumed",
                                message=f"Delegation to {slug} completed",
                                data={
                                    "delegation_target": slug,
                                    "sub_agent": slug,
                                    "state": "completed",
                                },
                            )
                        except Exception:
                            pass

                        if isinstance(result, (dict, list)):
                            return json.dumps(result)
                        return str(result)

                    except Exception as exc:
                        import uuid as _uuid2
                        try:
                            await data_client.log_execution_event(
                                session_id=_uuid2.UUID(session_id),
                                event_type="delegation_failed",
                                message=f"Delegation to {slug} failed: {exc}",
                                data={"delegation_target": slug, "sub_agent": slug, "error": str(exc)},
                            )
                        except Exception:
                            pass
                        logger.error("Delegation to '%s' failed: %s", slug, exc)
                        return json.dumps({"error": str(exc), "tool": orig_name})

                def _run(**kwargs: Any) -> str:
                    import asyncio
                    try:
                        return asyncio.get_event_loop().run_until_complete(_arun(**kwargs))
                    except Exception as exc:
                        return json.dumps({"error": str(exc)})

                return _run, _arun

            sync_fn, async_fn = _make_delegation_tool(target_slug, original_name)
            tool = StructuredTool.from_function(
                func=sync_fn,
                coroutine=async_fn,
                name=sanitized_name,
                description=description or f"Delegate task to the {target_slug} agent.",
                args_schema=_schema_to_pydantic(sanitized_name, parameters),
                return_direct=False,
            )
            tool.metadata = tool.metadata or {}
            tool.metadata["original_name"] = original_name
            tools.append(tool)
            continue

        # ── All other tools: route through CommHub ─────────────────────────────
        sanitized_name = _sanitize_tool_name(original_name)
        # CommHub expects the canonical (4-underscore) name; the tool definitions
        # use the OpenAI-safe (2-underscore) name.  Reverse-map via tool_name_map.
        canonical_comm_name: str = (
            tool_name_map.get(original_name, original_name)
            if tool_name_map
            else original_name
        )

        def _make_commhub_tool(orig_name: str, comm_name: str) -> tuple:
            async def _arun(**kwargs: Any) -> str:
                try:
                    result = await comm_hub_client.call_tool(
                        tool_name=comm_name,
                        tool_args=kwargs,
                        session_id=session_id,
                        agent_type_id=agent_type_id,
                        conv_session_id=conv_session_id,
                    )
                    if isinstance(result, (dict, list)):
                        return json.dumps(result)
                    return str(result)
                except Exception as exc:
                    logger.error("Tool '%s' failed via CommHub: %s", orig_name, exc)
                    return json.dumps({"error": str(exc), "tool": orig_name})

            def _run(**kwargs: Any) -> str:
                import asyncio
                try:
                    return asyncio.get_event_loop().run_until_complete(_arun(**kwargs))
                except Exception as exc:
                    return json.dumps({"error": str(exc)})

            return _run, _arun

        sync_fn, async_fn = _make_commhub_tool(original_name, canonical_comm_name)
        tool = StructuredTool.from_function(
            func=sync_fn,
            coroutine=async_fn,
            name=sanitized_name,
            description=description or f"Call the {original_name} tool.",
            args_schema=_schema_to_pydantic(sanitized_name, parameters),
            return_direct=False,
        )
        tool.metadata = tool.metadata or {}
        tool.metadata["original_name"] = original_name
        tools.append(tool)

    return tools
