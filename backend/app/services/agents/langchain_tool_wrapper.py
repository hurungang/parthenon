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

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from langchain_core.tools import StructuredTool

logger = logging.getLogger(__name__)

# Per-session delegation lock — ensures delegation tool calls execute one-at-a-time
# regardless of LLM provider.  OpenAI supports parallel_tool_calls=False natively,
# but other models (e.g. Gemini) ignore that flag and may issue multiple delegation
# tool calls in a single response.  This lock serialises them at the execution layer.
_delegation_locks: dict[str, asyncio.Lock] = {}


def _get_delegation_lock(sid: str) -> asyncio.Lock:
    """Return (creating if needed) the delegation serialisation lock for *sid*."""
    if sid not in _delegation_locks:
        _delegation_locks[sid] = asyncio.Lock()
    return _delegation_locks[sid]


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
        args_schema = _schema_to_pydantic(sanitized_name, parameters)

        def _make_tool_func(orig_name: str, san_name: str, schema: Any) -> Any:
            async def _arun(**kwargs: Any) -> str:
                """Dispatch tool call to CommHub via mTLS-authenticated client."""
                try:
                    result = await comm_hub_client.call_tool(
                        tool_name=orig_name,
                        tool_args=_restore_schema_keys(schema, kwargs),
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

        sync_fn, async_fn = _make_tool_func(original_name, sanitized_name, args_schema)

        tool = StructuredTool.from_function(
            func=sync_fn,
            coroutine=async_fn,
            name=sanitized_name,
            description=description or f"Call the {original_name} tool.",
            args_schema=args_schema,
            return_direct=False,
        )
        # Attach original name for reverse-mapping
        tool.metadata = tool.metadata or {}
        tool.metadata["original_name"] = original_name
        tools.append(tool)

    return tools


def _safe_field_name(name: str) -> str:
    """Return a Python-identifier-safe version of a JSON-schema property name.

    LLMs frequently normalise hyphenated keys (e.g. ``project-id``) to
    snake_case (``project_id``), so generated fields use the safe name while
    the original name is preserved as a validation alias — both forms are
    accepted (see ``_schema_to_pydantic``).
    """
    import re

    safe = re.sub(r"\W", "_", name)
    if not safe or not safe[0].isalpha():
        safe = f"f_{safe}" if safe else "field"
    return safe


def _schema_to_pydantic(tool_name: str, parameters: dict[str, Any]) -> Any:
    """Build a Pydantic v2 model from a JSON Schema parameters dict.

    Falls back to a permissive Any-typed model on schema parse errors.

    Deliberately tolerant by design:

    - Fields are generated with Python-safe names (hyphens → underscores) so
      LangChain's derived ``tool_call_schema`` behaves predictably; the safe →
      original mapping is attached as ``__schema_alias_map__`` and dispatch
      sites restore the original keys via ``_restore_schema_keys``.
    - Every field is OPTIONAL and the model allows extra keys.  LangChain's
      tool-call validation must never reject or silently drop arguments: LLMs
      frequently normalise hyphenated keys (``project-id`` → ``project_id``) or
      echo the original spelling, and a strict schema either blocks the call or
      loses fields.  Required-field enforcement stays the responsibility of the
      downstream receiver (A2A enqueue / MCP tool), whose precise validation
      errors are surfaced back to the LLM as tool results.
    """
    try:
        from pydantic import BaseModel, ConfigDict, create_model
        from pydantic.fields import FieldInfo

        props: dict[str, Any] = parameters.get("properties") or {}
        required_fields: list[str] = parameters.get("required") or []

        class _TolerantBase(BaseModel):
            model_config = ConfigDict(populate_by_name=True, extra="allow")

        field_definitions: dict[str, Any] = {}
        alias_map: dict[str, str] = {}
        for field_name, field_schema in props.items():
            py_type = _json_type_to_python(field_schema.get("type", "string"))
            description = field_schema.get("description", "")
            if field_name in required_fields:
                description = f"(required) {description}".strip()
            safe_name = _safe_field_name(field_name)
            if safe_name != field_name:
                alias_map[safe_name] = field_name
            # NOTE: `FieldInfo(alias=...)` alone does not populate
            # `validation_alias` in pydantic 2.13 — validation aliases must be
            # set explicitly so either spelling validates when possible.
            field_definitions[safe_name] = (
                py_type | None,
                FieldInfo(
                    default=None,
                    validation_alias=field_name,
                    serialization_alias=field_name,
                    description=description,
                ),
            )

        if not field_definitions:
            return None  # StructuredTool accepts None → no args schema

        model_class = create_model(
            f"{tool_name}_Args",
            __base__=_TolerantBase,
            **field_definitions,
        )
        if alias_map:
            setattr(model_class, "__schema_alias_map__", alias_map)
        return model_class

    except Exception as exc:
        logger.warning("Failed to build Pydantic schema for tool '%s': %s", tool_name, exc)
        return None


def _restore_schema_keys(args_schema: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Map normalised (safe) argument keys back to the schema's original keys.

    LangChain hands tools the validated ``model_dump()`` which uses field names
    (safe identifiers).  Downstream consumers — A2A request payloads, MCP tool
    args — expect the exact keys from the tool's JSON schema (e.g. ``project-id``).
    """
    alias_map = getattr(args_schema, "__schema_alias_map__", None)
    if not alias_map:
        return kwargs
    return {alias_map.get(key, key): value for key, value in kwargs.items()}


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
    tool_name_map: dict[str, str] | None = None,
    role_id: str | None = None,
    guardrail_state: Any | None = None,
    status_event_callback: Callable[..., Awaitable[None]] | None = None,
    tool_call_recorder: Callable[..., Awaitable[None]] | None = None,
) -> list[Any]:
    """Build LangChain tools for the Agent Runtime path.

    All tools are routed through CommHubToolClient, which handles permission
    checking and routing server-side.  Two special cases exist:

    - ``human_intervene``: Uses LangGraph ``interrupt()`` to pause execution.
    - ``agent____<slug>`` delegation tools: Routes via CommHub A2A endpoint.

    Every other tool — including all system tools (``save_data``, ``get_data``,
    ``get_output``, etc.) — falls through to the generic CommHub route.
    No hardcoded handling per tool name is needed or wanted.

    Args:
        tool_definitions: OpenAI-format tool definition list from context.
        comm_hub_client: CommHubToolClient instance (mTLS-configured).
        data_client: ControlCenterDataClient (kept for call-site compat).
        session_id: Agent session UUID as string.
        role_id: Requester role ID for A2A delegation authorization.
        agent_type_id: Agent type UUID as string.
        conv_session_id: Parent conversation session ID (for HITL context).
        tool_name_map: Optional mapping of OpenAI-sanitised (2-underscore) tool
            names to their canonical (4-underscore) equivalents.
        tool_call_recorder: Optional async callback invoked after every tool
            execution with keyword args ``tool_name``, ``route_type``,
            ``status``, ``duration_ms``, ``mcp_slug``, ``error`` — used to
            persist tool-call history for the runtime monitor.  The callback
            is best-effort and must never raise into the tool path.

    Returns:
        List of LangChain StructuredTool / BaseTool instances.
    """

    async def _record(
        *,
        tool_name: str,
        route_type: str,
        status: str,
        duration_ms: int | None = None,
        mcp_slug: str | None = None,
        error: str | None = None,
    ) -> None:
        if tool_call_recorder is None:
            return
        try:
            await tool_call_recorder(
                tool_name=tool_name,
                route_type=route_type,
                status=status,
                duration_ms=duration_ms,
                mcp_slug=mcp_slug,
                error=error,
            )
        except Exception as exc:  # recording must never break execution
            logger.warning("Tool-call recording failed for %s: %s", tool_name, exc)

    def _mcp_slug_of(name: str) -> str | None:
        try:
            from app.services.agents.tool_naming import parse_tool_name

            return parse_tool_name(name)[0]
        except Exception:
            return None

    from app.services.agents.langchain_system_tools import LangChainHumanInterveneTool

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

        # ── human_intervene: must use LangGraph interrupt() to suspend execution
        if original_name == "human_intervene":
            tool = LangChainHumanInterveneTool(
                comm_hub_client=comm_hub_client,
                session_id=session_id,
                agent_type_id=agent_type_id,
                conv_session_id=conv_session_id,
                tool_call_recorder=(
                    (lambda **kw: _record(**kw)) if tool_call_recorder is not None else None
                ),
            )
            tools.append(tool)
            continue

        # ── Agent delegation tools: route via A2A endpoint ─────────────────────
        target_slug = _extract_delegation_target_slug(original_name)
        if target_slug is not None:
            sanitized_name = _sanitize_tool_name(original_name)

            def _make_delegation_tool(slug: str, orig_name: str, schema: Any) -> tuple:
                async def _arun(**kwargs: Any) -> str:
                    import uuid as _uuid
                    import time as _time
                    kwargs = _restore_schema_keys(schema, kwargs)
                    _started = _time.monotonic()
                    _call_status = "success"
                    _call_error: str | None = None
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

                        # Emit status events for WebSocket consumers
                        try:
                            if status_event_callback is not None:
                                await status_event_callback({"status": "using_tool", "tool_name": slug})
                                await status_event_callback({"status": "delegating", "agent_type": slug})
                        except Exception:
                            pass

                        # Emit initial waiting event (before dispatch — no receiver_session_id yet)
                        # so the frontend knows delegation is starting.
                        try:
                            if status_event_callback is not None:
                                await status_event_callback({"status": "waiting", "agent_type": slug})
                        except Exception:
                            pass

                        # Non-blocking dispatch: get receiver_session_id immediately so
                        # the frontend can start SSE streaming while the sub-agent runs.
                        _dispatch = await comm_hub_client.call_a2a_request(
                            target_agent_type_slug=slug,
                            session_id=session_id,
                            requester_role_id=role_id,
                            request_payload=request_payload,
                            session_link_id=session_link_id,
                            wait_for_response=False,
                            conv_session_id=conv_session_id,
                        )
                        _receiver_session_id = _dispatch.get("receiver_session_id") if isinstance(_dispatch, dict) else None

                        # Emit second waiting event WITH receiver_session_id for SSE log streaming.
                        # Frontend uses this receiver_session_id to start polling execution logs.
                        if _receiver_session_id:
                            try:
                                if status_event_callback is not None:
                                    await status_event_callback({"status": "waiting", "agent_type": slug, "receiver_session_id": _receiver_session_id})
                            except Exception:
                                pass

                        # Log delegation_waiting WITH receiver_session_id — enables SSE streaming
                        try:
                            await data_client.log_execution_event(
                                session_id=_uuid.UUID(session_id),
                                event_type="delegation_waiting",
                                message=f"Waiting for agent: {slug}",
                                data={
                                    "delegation_target": slug,
                                    "sub_agent": slug,
                                    "receiver_session_id": _receiver_session_id,
                                },
                            )
                        except Exception:
                            pass

                        # Increment delegated_steps counter and track delegation depth
                        # before the sub-agent call so guardrail checks stay current.
                        if guardrail_state is not None:
                            guardrail_state.delegated_steps += 1
                            _next_depth = getattr(guardrail_state, "tree_depth", 0) + 1
                            guardrail_state.delegation_depth = max(
                                getattr(guardrail_state, "delegation_depth", 0),
                                _next_depth,
                            )

                        # Poll for sub-agent completion.
                        # CH wait endpoint caps at 120 s per call; loop until done.
                        _wait_result: dict[str, Any] = {"status": "error", "error": "No receiver session ID"}
                        if _receiver_session_id:
                            _total_timeout = 1800.0
                            _poll_interval = 90.0
                            _deadline = _time.monotonic() + _total_timeout
                            while _time.monotonic() < _deadline:
                                _remaining = _deadline - _time.monotonic()
                                _per_call = min(_poll_interval, max(_remaining, 1.0))
                                _wait_result = await comm_hub_client.wait_for_a2a_response(
                                    receiver_session_id=_receiver_session_id, timeout_seconds=_per_call
                                )
                                if _wait_result.get("status") in ("completed", "failed", "expired"):
                                    break
                                # status == "timeout" means sub-agent still running; loop again
                            else:
                                _wait_result = {"status": "timeout", "error": "Total delegation timeout exceeded"}

                        # Log delegation_resumed WITH receiver_session_id
                        try:
                            _resumed_data: dict[str, Any] = {
                                "delegation_target": slug,
                                "sub_agent": slug,
                                "state": _wait_result.get("status", "completed"),
                            }
                            if _receiver_session_id:
                                _resumed_data["receiver_session_id"] = _receiver_session_id
                            await data_client.log_execution_event(
                                session_id=_uuid.UUID(session_id),
                                event_type="delegation_resumed",
                                message=f"Delegation to {slug} completed",
                                data=_resumed_data,
                            )
                        except Exception:
                            pass

                        # Emit delegation_resumed status event for WebSocket consumers
                        try:
                            if status_event_callback is not None:
                                await status_event_callback({"status": "delegation_resumed", "agent_type": slug})
                        except Exception:
                            pass

                        # Accumulate child token usage into parent guardrail state.
                        if guardrail_state is not None and _wait_result.get("status") == "completed":
                            _child_usage = (
                                _wait_result
                                .get("output_data", {})
                                .get("guardrail_usage", {})
                                .get("token_usage_current_session", 0)
                            )
                            if isinstance(_child_usage, (int, float)) and _child_usage > 0:
                                guardrail_state.token_usage_current_session += int(_child_usage)

                        # Return only the sub-agent's clean output_data to the LLM
                        _final_status = _wait_result.get("status", "")
                        _output = _wait_result.get("output_data") or {}
                        if _final_status == "completed":
                            _tool_response = json.dumps(_output) if isinstance(_output, (dict, list)) else str(_output)
                        else:
                            _tool_response = json.dumps({"error": _wait_result.get("error", f"Delegation {_final_status}"), "status": _final_status})

                        # Log the exact string being returned to the parent LLM so we can
                        # distinguish LLM re-delegation decisions from response delivery failures.
                        logger.info(
                            "Delegation '%s' -> tool_response to parent (session=%s): status=%s response=%s",
                            slug, session_id, _final_status, _tool_response[:500],
                        )
                        try:
                            await data_client.log_execution_event(
                                session_id=_uuid.UUID(session_id),
                                event_type="tool_response",
                                message=f"Delegation '{slug}' response to parent LLM: status={_final_status}",
                                data={
                                    "delegation_target": slug,
                                    "status": _final_status,
                                    "response_preview": _tool_response[:1000],
                                },
                            )
                        except Exception:
                            pass

                        return _tool_response

                    except Exception as exc:
                        import uuid as _uuid2
                        _call_status = "error"
                        _call_error = str(exc)
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
                    finally:
                        # Record the canonical delegation tool name (the def
                        # name may be the sanitised ``agent__<slug>`` form).
                        await _record(
                            tool_name=f"agent____{slug}",
                            route_type="a2a",
                            status=_call_status,
                            duration_ms=int((_time.monotonic() - _started) * 1000),
                            mcp_slug=None,
                            error=_call_error,
                        )

                def _run(**kwargs: Any) -> str:
                    import asyncio
                    try:
                        return asyncio.get_event_loop().run_until_complete(_arun(**kwargs))
                    except Exception as exc:
                        return json.dumps({"error": str(exc)})

                return _run, _arun

            delegation_schema = _schema_to_pydantic(sanitized_name, parameters)
            sync_fn, async_fn = _make_delegation_tool(target_slug, original_name, delegation_schema)
            tool = StructuredTool.from_function(
                func=sync_fn,
                coroutine=async_fn,
                name=sanitized_name,
                description=description or f"Delegate task to the {target_slug} agent.",
                args_schema=delegation_schema,
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

        def _make_commhub_tool(orig_name: str, comm_name: str, schema: Any) -> tuple:
            async def _arun(**kwargs: Any) -> str:
                import time as _time
                kwargs = _restore_schema_keys(schema, kwargs)
                _started = _time.monotonic()
                _call_status = "success"
                _call_error: str | None = None
                try:
                    # Emit using_tool status event for WebSocket consumers
                    try:
                        if status_event_callback is not None:
                            _bare = orig_name.split("/")[-1] if "/" in orig_name else orig_name
                            await status_event_callback({"status": "using_tool", "tool_name": _bare})
                    except Exception:
                        pass
                    result = await comm_hub_client.call_tool(
                        tool_name=comm_name,
                        tool_args=kwargs,
                        session_id=session_id,
                        agent_type_id=agent_type_id,
                        conv_session_id=conv_session_id,
                    )
                    if isinstance(result, dict) and result.get("error"):
                        _call_status = "error"
                        _call_error = str(result.get("error"))
                    if isinstance(result, (dict, list)):
                        return json.dumps(result)
                    return str(result)
                except Exception as exc:
                    _call_status = "error"
                    _call_error = str(exc)
                    logger.error("Tool '%s' failed via CommHub: %s", orig_name, exc)
                    return json.dumps({"error": str(exc), "tool": orig_name})
                finally:
                    try:
                        from app.services.agents.tool_naming import is_system_tool

                        _route = "system" if is_system_tool(comm_name) else "mcp"
                    except Exception:
                        _route = "mcp"
                    # Record the CANONICAL (4-underscore) name, restored via
                    # tool_name_map — the tool definitions carry OpenAI-
                    # sanitised (2-underscore) names, and the runtime monitor
                    # resolves MCP slugs from the canonical form.
                    await _record(
                        tool_name=comm_name,
                        route_type=_route,
                        status=_call_status,
                        duration_ms=int((_time.monotonic() - _started) * 1000),
                        mcp_slug=_mcp_slug_of(comm_name),
                        error=_call_error,
                    )

            def _run(**kwargs: Any) -> str:
                import asyncio
                try:
                    return asyncio.get_event_loop().run_until_complete(_arun(**kwargs))
                except Exception as exc:
                    return json.dumps({"error": str(exc)})

            return _run, _arun

        commhub_schema = _schema_to_pydantic(sanitized_name, parameters)
        sync_fn, async_fn = _make_commhub_tool(original_name, canonical_comm_name, commhub_schema)
        tool = StructuredTool.from_function(
            func=sync_fn,
            coroutine=async_fn,
            name=sanitized_name,
            description=description or f"Call the {original_name} tool.",
            args_schema=commhub_schema,
            return_direct=False,
        )
        tool.metadata = tool.metadata or {}
        tool.metadata["original_name"] = original_name
        tools.append(tool)

    return tools
