"""AgentRuntimeExecutor — orchestrates agent execution using the LangChain deep agent framework.

Observe-Reason-Act loop:
1. **Observe**  — load session context, resolve the allowed tool set, authenticate using
   AgentIdentity credentials, and prepare the full prompt (system instruction + user input).
2. **Reason**   — call the LLM (via ModelBindingLayer) with the accumulated message history
   and decide the next action (tool call or final answer).
3. **Act**      — dispatch allowed tool calls via MCP, enforce permission boundary on every
   call, and append results to the context; mark ``is_complete = True`` when the agent
   signals it is done or when max iterations is exceeded.

Before the first Reason step, an ``AgentPromptLog`` record is written capturing the
fully-rendered system instruction and user prompt for complete traceability.

LangChain is an optional runtime dependency.  When unavailable the executor falls back
to a lightweight stub so that the session service and dispatcher still function.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from copy import deepcopy
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.agent_runtime.comm_hub_client import CommHubToolClient
    from app.agent_runtime.data_client import ControlCenterDataClient

from app.db.models.agents import AgentJob, AgentJobStatus, AgentInputType
from app.services.agents.agent_loop import TaskAgentLoop, ConversationalAgentLoop
from app.services.agents.permission_manager import AgentPermissionManager, PermissionDeniedError
from app.services.agents.guardrails import (
    GuardrailInfoReason,
    GuardrailStop,
    GuardrailStopReason,
    ModelAvailabilityBlockedError,
    RuntimeGuardrailState,
    detect_cycle_path,
    extract_total_tokens_from_usage,
)
from app.services.agents.runtime_loader import AgentRuntimeLoader
from app.services.agents.session_service import AgentSessionService
from app.services.agents.tool_naming import build_tool_name, parse_tool_name, is_system_tool, _LEGACY_SYSTEM_TOOL_NAMES
from app.services.agents.system_tool_registry import SystemToolRegistry

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class HumanInterveneRequired(Exception):
    """Raised from the task loop when the agent calls human_intervene,
    signalling that execution should be paused rather than completed."""

try:
    import langchain  # noqa: F401
    _LANGCHAIN_AVAILABLE = True
except ImportError:
    _LANGCHAIN_AVAILABLE = False
    logger.warning("LangChain not installed — runtime executor will use stub execution mode")


def _sanitize_tool_name_for_openai(tool_name: str) -> str:
    """Sanitize MCP tool name for OpenAI API (replace / with _).
    
    OpenAI requires tool names to match ^[a-zA-Z0-9_-]+$.
    MCP tool names use format mcp_slug/tool_name which contains invalid /.
    """
    return tool_name.replace("/", "_")


def _restore_tool_name_from_openai(sanitized_name: str, tool_map: dict[str, str]) -> str:
    """Restore original MCP tool name from OpenAI sanitized name.
    
    Uses tool_map to reverse the sanitization: {sanitized_name: original_name}.
    Returns the sanitized name unchanged if not found in map (e.g., system tools).
    """
    return tool_map.get(sanitized_name, sanitized_name)


def _extract_agent_delegation_target(tool_name: str) -> str | None:
    """Return delegated target slug when tool_name is ``agent____<slug>``."""
    try:
        server_slug, bare_tool = parse_tool_name(tool_name)
        if server_slug == "agent":
            return bare_tool
    except ValueError:
        pass

    # Backward-compatible fallback for sanitized names if no tool_name_map entry exists.
    if tool_name.startswith("agent__") and len(tool_name) > len("agent__"):
        return tool_name[len("agent__"):]

    return None


def _tool_route_type(tool_name: str) -> str:
    """Classify a tool into system/agent/mcp for diagnostics."""
    if is_system_tool(tool_name):
        return "system"
    if _extract_agent_delegation_target(tool_name) is not None:
        return "agent"
    return "mcp"


def _tool_names_from_definitions(tool_definitions: list[dict[str, Any]]) -> list[str]:
    """Extract tool function names from OpenAI function definitions."""
    names: list[str] = []
    for tool_def in tool_definitions:
        fn = tool_def.get("function") if isinstance(tool_def, dict) else None
        name = fn.get("name") if isinstance(fn, dict) else None
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _canonicalize_tool_name_for_log(
    tool_name: str,
    tool_name_map: dict[str, str] | None = None,
) -> str:
    """Normalize tool names into canonical ``server____tool`` format for logs."""
    if not tool_name:
        return tool_name

    if tool_name_map and tool_name in tool_name_map:
        return tool_name_map[tool_name]

    if "____" in tool_name:
        return tool_name

    if tool_name in SystemToolRegistry.get_names():
        return build_tool_name("system", tool_name)

    if tool_name.startswith("system__"):
        bare = tool_name[len("system__"):]
        if bare:
            return build_tool_name("system", bare)

    if tool_name.startswith("system_"):
        bare = tool_name[len("system_"):]
        if bare:
            return build_tool_name("system", bare)

    # OpenAI-sanitized canonical names are represented as ``server__tool``.
    if "__" in tool_name and "____" not in tool_name:
        server, bare = tool_name.split("__", 1)
        if server and bare:
            return build_tool_name(server, bare)

    return tool_name


def _canonicalize_tool_list_for_log(
    tool_names: list[str] | set[str] | tuple[str, ...],
    tool_name_map: dict[str, str] | None = None,
) -> list[str]:
    """Return sorted distinct canonical tool names for clean diagnostics."""
    canonical = {
        _canonicalize_tool_name_for_log(name, tool_name_map)
        for name in tool_names
        if isinstance(name, str) and name
    }
    return sorted(canonical)


def _build_delegation_request_payload(tool_args: dict[str, Any]) -> dict[str, Any]:
    """Build A2A request payload from dynamic agent tool args."""
    request_payload = tool_args.get("request_payload")
    if isinstance(request_payload, dict):
        return request_payload

    return {
        key: value
        for key, value in tool_args.items()
        if key != "session_link_id"
    }


def _int_or_default(value: Any, default: int) -> int:
    """Convert value to int with a safe default for malformed inputs."""
    try:
        return int(value)
    except Exception:
        return default


def _extract_sop_name_from_fallback_content(sop_content: str | None) -> str | None:
    """Extract SOP name from fallback content header if present."""
    if not sop_content:
        return None

    first_line = sop_content.strip().splitlines()[0].strip()
    match = re.match(r"^Follow this SOP to complete the task:\s*(.+?)\s*$", first_line)
    if not match:
        return None

    sop_name = match.group(1).strip()
    return sop_name or None


def _extract_ai_message_response(
    response: Any,
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
    """Extract text, tool calls, and usage from a LangChain AIMessage.

    Returns a 3-tuple ``(response_text, raw_tool_calls, usage)``:

    * ``response_text`` — plain text content (empty string if absent).
    * ``raw_tool_calls`` — list of OpenAI-shaped dicts:
      ``{"id": ..., "type": "function", "function": {"name": ..., "arguments": ...}}``.
    * ``usage`` — token dict with ``prompt_tokens``, ``completion_tokens``, ``total_tokens``
      (``None`` when unavailable).
    """
    # ── Response text ─────────────────────────────────────────────────────
    response_text = ""
    if hasattr(response, "content"):
        content = response.content
        if isinstance(content, str):
            response_text = content
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    response_text = block.get("text", "")
                    break
                if isinstance(block, str):
                    response_text = block
                    break

    # ── Tool calls ────────────────────────────────────────────────────────
    raw_tool_calls: list[dict[str, Any]] = []
    if hasattr(response, "tool_calls") and response.tool_calls:
        for tc in response.tool_calls:
            if not isinstance(tc, dict):
                continue
            raw_tool_calls.append({
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": json.dumps(tc.get("args", {})),
                },
            })
    if not raw_tool_calls and hasattr(response, "additional_kwargs"):
        # Fallback: some providers emit tool_calls via additional_kwargs
        raw_tool_calls = list(response.additional_kwargs.get("tool_calls") or [])

    # ── Token usage ───────────────────────────────────────────────────────
    usage: dict[str, Any] | None = None
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        meta = response.usage_metadata
        if isinstance(meta, dict):
            input_tok = max(0, int(meta.get("input_tokens") or 0))
            output_tok = max(0, int(meta.get("output_tokens") or 0))
            total_tok = max(0, int(meta.get("total_tokens") or (input_tok + output_tok)))
            usage = {
                "prompt_tokens": input_tok,
                "completion_tokens": output_tok,
                "total_tokens": total_tok,
            }

    return response_text, raw_tool_calls, usage


def _extract_structured_output(
    raw_response: Any,
) -> dict[str, Any] | None:
    """Extract structured output (Pydantic model or dict) from LangChain response.
    
    When using with_structured_output(), LangChain may return the parsed data
    in various forms:
    * AIMessage.content as dict/model (Anthropic or other formats)
    * AIMessage as Pydantic model directly
    * Direct dict response
    
    Returns the dict if found, None if response appears to be text-only or AIMessage without structure.
    """
    if raw_response is None:
        return None
    
    # Check if response has content attribute (AIMessage-like) FIRST
    # This must come before isinstance(dict) check because AIMessage might have dict-like behavior
    if hasattr(raw_response, "content") and hasattr(raw_response, "tool_calls"):
        # This is an AIMessage - extract from its content field only
        content = raw_response.content
        
        # Check if content is a dict (structured output parsed by LangChain)
        if isinstance(content, dict):
            # If it has multiple keys or at least one non-"result" key, it's structured output
            if len(content) > 1 or (
                len(content) == 1 and "result" not in content
            ):
                logger.info(
                    "Extracted structured output from AIMessage.content: keys=%s",
                    list(content.keys()),
                )
                return content
        
        # Check if content is a Pydantic model instance
        if hasattr(content, "model_dump") and callable(content.model_dump):
            try:
                model_dict = content.model_dump()
                if model_dict:  # Only return if not empty
                    logger.info(
                        "Extracted structured output from AIMessage.content (Pydantic): keys=%s",
                        list(model_dict.keys()),
                    )
                    return model_dict
            except Exception as exc:
                logger.debug("Failed to dump Pydantic model from content: %s", exc)
        
        # Check if content is a string - try to parse as JSON (for raw model responses without with_structured_output)
        if isinstance(content, str):
            try:
                import json
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    # If it has multiple keys or at least one non-"result" key, it's structured output
                    if len(parsed) > 1 or (
                        len(parsed) == 1 and "result" not in parsed
                    ):
                        logger.info(
                            "Extracted structured output from JSON string in AIMessage.content: keys=%s",
                            list(parsed.keys()),
                        )
                        return parsed
            except (json.JSONDecodeError, ValueError):
                # Not valid JSON, skip
                pass
        
        # AIMessage but no structured output found in content
        return None
    
    # NEVER treat AIMessage or other objects as dicts directly
    # Only process if explicitly isinstance(dict)
    if isinstance(raw_response, dict):
        # Direct dict responses (multiple keys or single non-"result" key)
        if len(raw_response) > 1 or (
            len(raw_response) == 1 and "result" not in raw_response
        ):
            return raw_response
        return None
    
    # Check if response itself is a Pydantic model (not an AIMessage)
    if hasattr(raw_response, "model_dump") and callable(raw_response.model_dump):
        # But NOT if it has tool_calls (that would be AIMessage)
        if not hasattr(raw_response, "tool_calls"):
            try:
                model_dict = raw_response.model_dump()
                if model_dict:  # Only return if not empty
                    logger.info(
                        "Extracted structured output from Pydantic model response: keys=%s",
                        list(model_dict.keys()),
                    )
                    return model_dict
            except Exception as exc:
                logger.debug("Failed to dump Pydantic model response: %s", exc)
    
    # Check additional_kwargs for parsed response (some providers put it there)
    if hasattr(raw_response, "additional_kwargs"):
        kwargs = raw_response.additional_kwargs
        if isinstance(kwargs, dict):
            # Look for any structured result
            for key in ["result", "output", "data", "parsed"]:
                if key in kwargs and isinstance(kwargs[key], dict):
                    result_dict = kwargs[key]
                    if len(result_dict) > 1 or (
                        len(result_dict) == 1 and "result" not in result_dict
                    ):
                        logger.info(
                            "Extracted structured output from additional_kwargs[%s]: keys=%s",
                            key,
                            list(result_dict.keys()),
                        )
                        return result_dict
    
    return None


def _messages_to_dicts(messages: list[Any]) -> list[dict[str, Any]]:
    """Convert LangChain BaseMessage objects to serialisable dicts for CC DB storage.

    Delegates to langchain_core.messages.messages_to_dict (native LangChain).
    """
    from langchain_core.messages import messages_to_dict
    return messages_to_dict(messages)


def _build_dynamic_agent_tool_definition(
    target_agent_type_slug: str,
    target_description: str | None,
    target_input_type: str,
    target_input_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build dynamic delegation tool schema for ``agent____<slug>``."""
    canonical_name = build_tool_name("agent", target_agent_type_slug)

    description_parts = [f"Delegate work to agent type '{target_agent_type_slug}'."]
    if target_description:
        description_parts.append(target_description.strip())
    description_parts.append(f"Target input type: {target_input_type}.")

    session_link_property = {
        "session_link_id": {
            "type": "string",
            "description": "Optional existing A2A session link for continuation",
        }
    }

    if target_input_type == "typed":
        if (
            isinstance(target_input_schema, dict)
            and target_input_schema.get("type") == "object"
        ):
            parameters = deepcopy(target_input_schema)
            properties = parameters.setdefault("properties", {})
            if isinstance(properties, dict):
                properties.update(session_link_property)
            else:
                parameters["properties"] = session_link_property
        elif isinstance(target_input_schema, dict) and target_input_schema:
            parameters = {
                "type": "object",
                "properties": {
                    "request_payload": target_input_schema,
                    **session_link_property,
                },
                "required": ["request_payload"],
            }
        else:
            parameters = {
                "type": "object",
                "properties": {
                    "request_payload": {
                        "type": "object",
                        "description": "Payload expected by the delegated typed agent",
                    },
                    **session_link_property,
                },
                "required": ["request_payload"],
            }
    elif target_input_type == "conversation":
        parameters = {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Conversation message to send to the delegated agent",
                },
                **session_link_property,
            },
            "required": ["message"],
        }
    else:
        parameters = {
            "type": "object",
            "properties": {**session_link_property},
        }

    return {
        "type": "function",
        "function": {
            "name": canonical_name,
            "description": " ".join(description_parts),
            "parameters": parameters,
        },
    }


# send_notification system tool definition
_SEND_NOTIFICATION_TOOL_DEF: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "send_notification",
        "description": (
            "Send a notification to a named recipient group. "
            "The group must be configured in the Parthenon notification admin. "
            "Returns a delivery summary for each channel in the group."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "group_slug": {
                    "type": "string",
                    "description": "Slug of the recipient group to send the notification to.",
                },
                "channel": {
                    "type": "string",
                    "description": "Optional channel selector within the recipient group (channel name, channel type, or channel ID).",
                },
                "subject": {
                    "type": "string",
                    "description": "Optional subject line for email-type channels.",
                },
                "body": {
                    "type": "string",
                    "description": "Notification body text.",
                },
            },
            "required": ["group_slug", "body"],
        },
    },
}

# human_intervene system tool definition
_HUMAN_INTERVENE_TOOL_DEF: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "human_intervene",
        "description": (
            "Request human intervention during agent execution. "
            "Call this when you need approval, a choice between options, or text input from a human operator. "
            "Execution will suspend until the human responds."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Explanation of why human input is needed",
                },
                "intervention_type": {
                    "type": "string",
                    "enum": ["approval", "choice", "text"],
                    "description": "Type of intervention needed",
                },
                "choices": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Available options when intervention_type is 'choice'",
                },
                "prompt": {
                    "type": "string",
                    "description": "Descriptive prompt when intervention_type is 'text'",
                },
            },
            "required": ["reason", "intervention_type"],
        },
    },
    }


# System tool schemas — all tool definitions are now centralised in
# ``SystemToolRegistry``.  Use ``SystemToolRegistry.get_all_schemas()``
# or ``SystemToolRegistry.get_schema(name)`` wherever needed.



class AgentRuntimeExecutor:
    """
    Executes an AgentJob using the LangChain deep agent observe-reason-act loop.

    For task agents: iterates until the agent signals completion or max iterations.
    For conversational agents: the loop is driven externally via WebSocket messages.
    """

    def __init__(self, data_client: Any = None) -> None:
        """Initialize executor with optional data client.
        
        Args:
            data_client: ControlCenterDataClient instance with properly configured certificate.
                        If None, will attempt to use app.state.data_client in runtime.
        """
        self._permission_manager = AgentPermissionManager()
        self._session_service = AgentSessionService()
        self._runtime_loader = AgentRuntimeLoader()
        self._data_client = data_client

    def _build_guardrail_state(
        self,
        context: dict[str, Any],
        job_data: dict[str, Any],
    ) -> RuntimeGuardrailState:
        """Construct runtime guardrail state from resolved context policy snapshot."""
        policy = context.get("guardrail_policy") or {}
        input_data = job_data.get("input_data") if isinstance(job_data, dict) else {}
        current_depth = 0
        if isinstance(input_data, dict):
            current_depth = _int_or_default(input_data.get("__delegation_depth"), 0)

        guardrail = RuntimeGuardrailState(
            max_iterations=_int_or_default(policy.get("max_iterations"), 10),
            max_delegation_depth=_int_or_default(policy.get("max_delegation_depth"), 3),
            max_delegated_steps=_int_or_default(policy.get("max_delegated_steps"), 20),
            execution_timeout_seconds=_int_or_default(
                policy.get("execution_timeout_seconds"),
                300,
            ),
            token_budget=(
                _int_or_default(policy.get("token_budget"), 0)
                if policy.get("token_budget") is not None
                else None
            ),
            token_enforcement_mode=str(policy.get("token_enforcement_mode") or "observe"),
            token_fallback_mode=str(policy.get("token_fallback_mode") or "observe_and_log"),
            conversational_token_visibility_mode=str(
                policy.get("conversational_token_visibility_mode") or "enabled"
            ),
            conversational_continuation_policy=str(
                policy.get("conversational_continuation_policy") or "allow"
            ),
            policy_snapshot_id=str(policy.get("policy_snapshot_id") or "unknown"),
            delegation_depth=0,
            tree_depth=max(0, current_depth),
        )

        # Phase 1.1: Override max_delegation_depth to 1 for non-conversational agents.
        # Non-conversational (task) agents are limited to 1 level of delegation so
        # that automated workflows cannot create unbounded delegation chains.
        input_type = context.get("input_type")
        if input_type is not None:
            input_type_value = (
                input_type.value if hasattr(input_type, "value") else str(input_type)
            )
            if input_type_value != "conversation":
                guardrail.max_delegation_depth = 1

        return guardrail

    async def _precheck_delegation_graph(
        self,
        *,
        session_id: uuid.UUID,
        agent_type_slug: str,
        context: dict[str, Any],
        data_client: "ControlCenterDataClient",
        guardrail_state: RuntimeGuardrailState,
    ) -> None:
        """Run pre-execution graph cycle guardrail checks before first model/tool action."""
        adjacency: dict[str, list[str]] = {}
        provided_graph = context.get("delegation_graph")
        provided_cycle_path = context.get("delegation_cycle_path")

        if isinstance(provided_graph, dict):
            adjacency = {
                str(node): [str(target) for target in (targets or [])]
                for node, targets in provided_graph.items()
            }
        elif isinstance(context.get("allowed_agent_types"), list):
            adjacency = {
                str(agent_type_slug): [
                    str(target) for target in (context.get("allowed_agent_types") or [])
                    if str(target) != str(agent_type_slug)
                ]
            }

        cycle_path: list[str] | None = None
        if isinstance(provided_cycle_path, list) and provided_cycle_path:
            cycle_path = [str(node) for node in provided_cycle_path]
        elif adjacency:
            cycle_path = detect_cycle_path(adjacency, str(agent_type_slug))

        if cycle_path:
            await data_client.log_execution_event(
                session_id=session_id,
                event_type="guardrail.precheck.blocked_cycle",
                log_level="WARN",
                message="Delegation cycle detected before execution start",
                data={
                    "guardrail_reason": GuardrailStopReason.CYCLE_DETECTED,
                    "cycle_path": cycle_path,
                    "root_agent": str(agent_type_slug),
                    "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                },
            )
            raise GuardrailStop(
                reason=GuardrailStopReason.CYCLE_DETECTED,
                message="Delegation cycle detected in pre-execution graph validation",
                details={
                    "cycle_path": cycle_path,
                    "root_agent": str(agent_type_slug),
                    "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                },
            )

        graph_errors = context.get("delegation_graph_errors") or []
        if isinstance(graph_errors, list) and graph_errors:
            await data_client.log_execution_event(
                session_id=session_id,
                event_type="guardrail.precheck.blocked_cycle",
                log_level="WARN",
                message="Delegation graph validation failed before execution start",
                data={
                    "guardrail_reason": GuardrailStopReason.CYCLE_DETECTED,
                    "validation_errors": [str(err) for err in graph_errors],
                    "root_agent": str(agent_type_slug),
                    "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                },
            )
            raise GuardrailStop(
                reason=GuardrailStopReason.CYCLE_DETECTED,
                message="Delegation graph validation failed before execution start",
                details={
                    "validation_errors": [str(err) for err in graph_errors],
                    "root_agent": str(agent_type_slug),
                    "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                },
            )

        await data_client.log_execution_event(
            session_id=session_id,
            event_type="guardrail.precheck.allowed",
            message="Pre-execution delegation graph validation passed",
            data={
                "guardrail_reason": "precheck_allowed",
                "root_agent": str(agent_type_slug),
                "node_count": len(adjacency),
                "policy_snapshot_id": guardrail_state.policy_snapshot_id,
            },
        )

    async def _preflight_model_availability(
        self,
        *,
        session_id: uuid.UUID,
        context: dict[str, Any],
        data_client: "ControlCenterDataClient",
    ) -> None:
        """Consult Control Center preflight before dispatch.

        Phase 3.10: any agent execution that would use a disabled model
        or a model under a disabled vendor is blocked here.  On deny
        we raise :class:`ModelAvailabilityBlockedError` so the calling
        ``run`` loop can record the policy outcome in execution logs and
        attribute the stop to ``model_disabled`` or ``vendor_disabled``
        on the ``AgentJob``.

        Failures of the preflight call itself (network / 5xx) DO NOT
        block execution — runtime stays available, and the missing check
        is logged at WARN so the operator can spot degraded mode.
        """
        model_id = context.get("model_id")
        if not model_id:
            # No model bound — nothing to check.  Most commonly hit during
            # the cold-start context build.
            return
        vendor_model_config_id: uuid.UUID | None = None
        raw = context.get("model_config_id")
        if raw:
            try:
                vendor_model_config_id = uuid.UUID(str(raw))
            except (TypeError, ValueError):
                vendor_model_config_id = None

        try:
            outcome = await data_client.preflight_availability(
                model_name=str(model_id),
                vendor_model_config_id=vendor_model_config_id,
            )
        except Exception as exc:  # noqa: BLE001 — fail-open
            logger.warning(
                "Preflight availability check failed for session %s model %s: %s; "
                "continuing execution in degraded mode",
                session_id,
                model_id,
                exc,
            )
            return

        if outcome.get("allowed"):
            return

        blocked_by = str(outcome.get("blocked_by") or "model_disabled")
        disabled_reason = outcome.get("disabled_reason")
        reason = str(outcome.get("reason") or "Model is not available")
        raise ModelAvailabilityBlockedError(
            message=reason,
            blocked_by=blocked_by,
            disabled_reason=disabled_reason,
            details={
                "model_id": str(model_id),
                "vendor_model_config_id": (
                    str(vendor_model_config_id)
                    if vendor_model_config_id
                    else None
                ),
                "blocked_by": blocked_by,
                "disabled_reason": disabled_reason,
            },
        )

    def _check_runtime_limits_or_raise(
        self,
        state: RuntimeGuardrailState,
    ) -> None:
        """Apply hard iteration/depth/delegation/timeout constraints."""
        if state.cumulative_iterations > state.max_iterations:
            raise GuardrailStop(
                reason=GuardrailStopReason.ITERATION_LIMIT_EXCEEDED,
                message="Cumulative iteration limit exceeded",
                details={
                    "current_value": state.cumulative_iterations,
                    "threshold_value": state.max_iterations,
                },
            )

        if state.tree_depth > state.max_delegation_depth:
            raise GuardrailStop(
                reason=GuardrailStopReason.DELEGATION_DEPTH_EXCEEDED,
                message="Delegation depth limit exceeded",
                details={
                    "current_value": state.delegation_depth,
                    "threshold_value": state.max_delegation_depth,
                },
            )

        if state.delegated_steps > state.max_delegated_steps:
            raise GuardrailStop(
                reason=GuardrailStopReason.DELEGATED_STEPS_EXCEEDED,
                message="Delegated-step budget exceeded",
                details={
                    "current_value": state.delegated_steps,
                    "threshold_value": state.max_delegated_steps,
                },
            )

        elapsed_seconds = state.elapsed_seconds()
        if elapsed_seconds > state.execution_timeout_seconds:
            raise GuardrailStop(
                reason=GuardrailStopReason.EXECUTION_TIMEOUT_EXCEEDED,
                message="Execution timeout exceeded",
                details={
                    "current_value": elapsed_seconds,
                    "threshold_value": state.execution_timeout_seconds,
                },
            )

    # ── Execution Log Helper ───────────────────────────────────────────────────

    async def _log_execution_event(
        self,
        session_id: uuid.UUID,
        event_type: str,
        message: str,
        data: dict[str, Any],
        log_level: str = "INFO",
        event_category: str = "functional",
        data_client: Any | None = None,
    ) -> None:
        """Persist a structured execution event via Control Center data API and emit to logger."""
        logger.info("[%s] %s: %s", session_id, event_type, message, extra={"data": data})

        target_data_client = data_client or self._data_client

        if target_data_client is None:
            logger.warning(
                "[%s] No data_client configured - execution logs will not persist. "
                "Ensure AgentRuntimeExecutor is instantiated with app.state.data_client.",
                session_id
            )
            return

        try:
            await target_data_client.log_execution_event(
                session_id=session_id,
                event_type=event_type,
                message=message,
                data=data or {},
                log_level=log_level,
                event_category=event_category,
            )
        except Exception as exc:
            logger.error(
                "[%s] Failed to persist execution log to Control Center: %s (event_type=%s)",
                session_id,
                exc,
                event_type,
                exc_info=True
            )

    async def _capture_prompt_log(
        self,
        session_id: uuid.UUID,
        system_instruction: str | None,
        user_prompt: str | None,
        db: AsyncSession,
    ) -> None:
        """Write an AgentPromptLog record before the first LLM call.

        This captures the full system instruction and user prompt for auditability.
        Also emits a prompt_captured ExecutionLogEntry so the full trace is visible
        from a single endpoint (GAP-3 fix).
        Failures are swallowed — prompt logging must never abort execution.
        """
        from app.db.models.agents import AgentPromptLog

        try:
            entry = AgentPromptLog(
                session_id=session_id,
                system_instruction=system_instruction,
                user_prompt=user_prompt,
            )
            db.add(entry)
            await db.flush()
            logger.debug("Prompt log captured for session %s", session_id)
        except Exception as exc:
            logger.warning(
                "Failed to capture prompt log for session %s: %s", session_id, exc
            )

        # GAP-3: also emit an ExecutionLogEntry so both prompt and events are in one table
        await self._log_execution_event(
            session_id=session_id,
            event_type="prompt_captured",
            message="Prompt captured before first LLM call",
            data={
                "system_instruction": system_instruction,
                "user_prompt": user_prompt,
                "system_instruction_length": len(system_instruction or ""),
                "user_prompt_length": len(user_prompt or ""),
            },
        )

    # ── SOPs / Skills loader (GAP-1) ─────────────────────────────────────────

    async def _log_sops_skills(
        self,
        session_id: uuid.UUID,
        role_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        """Query the role's assigned SOPs and Skills and emit a sops_skills_loaded event."""
        from sqlalchemy import select
        from app.db.models.agents import AgentRoleSOP, AgentRoleSkill
        from app.db.models.skills import Sop, Skill

        try:
            sop_rows = await db.execute(
                select(AgentRoleSOP.sop_id, Sop.name)
                .join(Sop, AgentRoleSOP.sop_id == Sop.id)
                .where(AgentRoleSOP.role_id == role_id)
            )
            sops = [{"id": str(row.sop_id), "name": row.name} for row in sop_rows]

            skill_rows = await db.execute(
                select(AgentRoleSkill.skill_id, Skill.name)
                .join(Skill, AgentRoleSkill.skill_id == Skill.id)
                .where(AgentRoleSkill.role_id == role_id)
            )
            skills = [{"id": str(row.skill_id), "name": row.name} for row in skill_rows]

            await self._log_execution_event(
                session_id=session_id,
                event_type="sops_skills_loaded",
                message=f"Loaded {len(sops)} SOP(s) and {len(skills)} Skill(s) for role",
                data={
                    "role_id": str(role_id),
                    "sops": sops,
                    "skills": skills,
                },
            )
        except Exception as exc:
            logger.warning(
                "Failed to log SOPs/Skills for session %s role %s: %s",
                session_id,
                role_id,
                exc,
            )

    async def _load_binding_content(
        self, agent_type: Any, db: AsyncSession
    ) -> str | None:
        """Load bound SOPs and skills for the agent type and format as ordered instruction text.

        Merges SOP and skill bindings sorted by ``order``, then formats each as
        context for the system instruction. Returns None when no bindings exist.
        """
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.db.models.agents import AgentTypeSopBinding, AgentTypeSkillBinding
        from app.db.models.skills import Sop, Skill

        try:
            # Load SOP bindings with their SOP relationships
            sop_result = await db.execute(
                select(AgentTypeSopBinding)
                .where(AgentTypeSopBinding.agent_type_id == agent_type.id)
                .options(selectinload(AgentTypeSopBinding.sop))
                .order_by(AgentTypeSopBinding.order)
            )
            sop_bindings = list(sop_result.scalars().all())

            # Load Skill bindings with their Skill relationships
            skill_result = await db.execute(
                select(AgentTypeSkillBinding)
                .where(AgentTypeSkillBinding.agent_type_id == agent_type.id)
                .options(selectinload(AgentTypeSkillBinding.skill))
                .order_by(AgentTypeSkillBinding.order)
            )
            skill_bindings = list(skill_result.scalars().all())

            if not sop_bindings and not skill_bindings:
                return None

            # Build ordered entries: (order, type_prefix, formatted_text)
            entries: list[tuple[int, str, str]] = []

            for binding in sop_bindings:
                sop = binding.sop
                if not sop:
                    continue
                lines: list[str] = [f"Follow this SOP to complete the task: {sop.name}"]
                if sop.description:
                    lines.append(f"Description: {sop.description}")
                if sop.instructions:
                    lines.append(f"Instructions: {sop.instructions}")
                # Load steps
                sop_full_result = await db.execute(
                    select(Sop)
                    .where(Sop.id == sop.id)
                    .options(selectinload(Sop.steps))
                )
                sop_full = sop_full_result.scalar_one_or_none()
                if sop_full and sop_full.steps:
                    lines.append("Steps:")
                    for step in sorted(sop_full.steps, key=lambda s: s.order):
                        step_text = f"  {step.order + 1}."
                        if step.name:
                            step_text += f" {step.name}"
                        if step.description:
                            step_text += f": {step.description}"
                        lines.append(step_text)
                entries.append((binding.order, "sop", "\n".join(lines)))

            for binding in skill_bindings:
                skill = binding.skill
                if not skill:
                    continue
                lines = [f"Use this skill when needed: {skill.name}"]
                if skill.description:
                    lines.append(f"Description: {skill.description}")
                if skill.instructions:
                    lines.append(f"Instructions: {skill.instructions}")
                entries.append((binding.order, "skill", "\n".join(lines)))

            # Sort by order, then by type
            entries.sort(key=lambda e: (e[0], e[1]))

            # Merge into single content block
            content_parts: list[str] = []
            for order, typ, text in entries:
                content_parts.append(f"[Step {order}] ({typ.upper()})\n{text}")

            return "\n\n---\n\n".join(content_parts)

        except Exception as exc:
            logger.warning(
                "Failed to load binding content for agent_type=%s: %s",
                agent_type.id,
                exc,
            )
            return None

    async def _load_mcp_session_context(
        self, role_id: uuid.UUID, db: AsyncSession
    ) -> str | None:
        """Load MCP sessions assigned to the agent role and format as context.

        Returns formatted text describing available MCP connectors, their parameters,
        and available resources. Returns None if no sessions found or on error.
        """
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.db.models.mcp_hub import McpSession, McpServer
        from app.db.models.agents import AgentRoleMcpSession

        try:
            # Query MCP sessions assigned to this role via agent_role_mcp_sessions
            result = await db.execute(
                select(McpSession, McpServer)
                .join(AgentRoleMcpSession, AgentRoleMcpSession.mcp_session_id == McpSession.id)
                .join(McpServer, McpServer.id == McpSession.server_id)
                .where(AgentRoleMcpSession.role_id == role_id)
                .where(McpSession.is_active.is_(True))
                .order_by(McpServer.name, McpSession.name)
            )
            session_pairs = list(result.all())

            if not session_pairs:
                logger.debug("No MCP sessions found for role %s", role_id)
                return None

            lines: list[str] = [
                "## Available MCP Resources",
                "",
                "You have access to the following MCP connectors with pre-configured sessions:",
                ""
            ]

            for session, server in session_pairs:
                lines.append(f"### {server.name} ({server.slug})")
                if session.description:
                    lines.append(f"Description: {session.description}")

                # Parse credential_config to show available parameters
                if session.credential_config:
                    try:
                        config = session.credential_config
                        if isinstance(config, dict) and config.get("parameters"):
                            lines.append("Pre-configured parameters:")
                            for param_name, param_value in config["parameters"].items():
                                lines.append(f"  - {param_name}: {param_value}")
                    except Exception:
                        pass

                # Parse identity_binding to show resource context
                if session.identity_binding:
                    try:
                        binding = session.identity_binding
                        if isinstance(binding, dict):
                            if binding.get("project_id"):
                                lines.append(f"Project ID: {binding['project_id']}")
                            if binding.get("region"):
                                lines.append(f"Region: {binding['region']}")
                            if binding.get("environment"):
                                lines.append(f"Environment: {binding['environment']}")
                    except Exception:
                        pass

                lines.append(f"Authentication: {session.auth_type.value}")
                lines.append(f"Status: Active")
                lines.append("")

            lines.append("**Note:** You have valid authentication for these connectors. Use the associated tools directly - credentials are handled automatically.")

            return "\n".join(lines)
        except Exception as exc:
            logger.warning("Failed to load MCP session context for role %s: %s", role_id, exc)
            return None

    async def _load_tool_definitions(
        self,
        allowed_tools: set[str],
        db: AsyncSession,
        include_all_system_tools: bool = True,
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """Load MCP tool schemas for all allowed tools and return as OpenAI tool definitions.

        System tools are included based on ``include_all_system_tools``:
        - ``True``: include all built-in system tools.
        - ``False``: include only system tools explicitly present in ``allowed_tools``.
        All other active MCP tools whose name appears in allowed_tools are fetched
        and wrapped in the OpenAI function-calling schema.
        
        Returns:
            Tuple of (tool_definitions, tool_name_map) where tool_name_map maps
            sanitized names back to original names for MCP tool lookup.
        """
        from sqlalchemy import select
        from app.db.models.mcp_hub import McpTool

        system_tool_defs: dict[str, dict[str, Any]] = {
            name: SystemToolRegistry.get_schema(name)
            for name in SystemToolRegistry.get_names()
        }

        explicit_system_tools: set[str] = set()
        for t in allowed_tools:
            if SystemToolRegistry.is_system_tool(t):
                parsed = SystemToolRegistry.parse_name(t)
                if parsed is not None:
                    explicit_system_tools.add(parsed[1])
                else:
                    for prefix in ("system/", "system__", "system_"):
                        if t.startswith(prefix):
                            explicit_system_tools.add(t[len(prefix):])
                            break
                    else:
                        explicit_system_tools.add(t)

        if include_all_system_tools:
            selected_system_tools = tuple(system_tool_defs.keys())
        else:
            selected_system_tools = tuple(
                name for name in system_tool_defs.keys() if name in explicit_system_tools
            )

        defs: list[dict[str, Any]] = [
            system_tool_defs[name] for name in selected_system_tools
        ]
        tool_name_map: dict[str, str] = {}  # Maps sanitized_name -> original_name

        # Filter out system/agent tools from MCP query.
        tool_names = []
        agent_target_slugs: list[str] = []
        for t in allowed_tools:
            if is_system_tool(t):
                continue
            try:
                server_slug, bare_tool = parse_tool_name(t)
                if server_slug == "system":
                    continue
                if server_slug == "agent":
                    agent_target_slugs.append(bare_tool)
                    sanitized_name = t.replace("____", "__")
                    tool_name_map[sanitized_name] = t
                    continue
            except ValueError:
                pass
            tool_names.append(t)

        if agent_target_slugs:
            from sqlalchemy import select as _select
            from app.db.models.agents import AgentType

            delegated_rows = await db.execute(
                _select(
                    AgentType.name,
                    AgentType.description,
                    AgentType.input_type,
                    AgentType.input_schema,
                ).where(
                    AgentType.name.in_(agent_target_slugs),
                    AgentType.is_active.is_(True),
                )
            )

            for name, description, input_type, input_schema in delegated_rows.fetchall():
                defs.append(
                    _build_dynamic_agent_tool_definition(
                        target_agent_type_slug=name,
                        target_description=description,
                        target_input_type=(input_type.value if hasattr(input_type, "value") else str(input_type)),
                        target_input_schema=input_schema,
                    )
                )
        
        if not tool_names:
            logger.debug("No MCP tools to load (only system/agent tools)")
            return defs, tool_name_map

        try:
            result = await db.execute(
                select(McpTool)
                .where(McpTool.name.in_(tool_names))
                .where(McpTool.is_active.is_(True))
            )
            mcp_tools = list(result.scalars().all())
            
            logger.info(
                "Loaded %d MCP tool definition(s) from %d allowed tools",
                len(mcp_tools),
                len(tool_names),
            )
            
            if len(mcp_tools) < len(tool_names):
                found_names = {t.name for t in mcp_tools}
                missing = set(tool_names) - found_names
                logger.warning(
                    "Some tools not found in mcp_tools table: %s",
                    ", ".join(missing),
                )
            
            for tool in mcp_tools:
                sanitized_name = _sanitize_tool_name_for_openai(tool.name)
                tool_name_map[sanitized_name] = tool.name
                
                defs.append(
                    {
                        "type": "function",
                        "function": {
                            "name": sanitized_name,
                            "description": tool.description or f"Tool: {tool.name}",
                            "parameters": tool.input_schema
                            or {"type": "object", "properties": {}},
                        },
                    }
                )
                logger.debug("Tool definition loaded: %s (sanitized as %s)", tool.name, sanitized_name)
        except Exception as exc:
            logger.error("Failed to load tool definitions: %s", exc, exc_info=True)

        return defs, tool_name_map

    # ── Public Entry Point ─────────────────────────────────────────────────────

    async def run(
        self,
        session_id: uuid.UUID,
        data_client: "ControlCenterDataClient",
        response_value: dict | None = None,
    ) -> None:
        """Entry point called by the /execute or /internal/resume endpoint.

        The session is already in ``running`` state when this is called — the
        caller transitions it before launching this coroutine.  When
        ``response_value`` is set (resume after human intervention), the executor
        injects it as follow-up context so the LLM can continue without re-requesting
        human input.

        All session state, agent context, and logging flow through the Control Center
        data API via ``data_client``.  No direct database access.
        """
        with tracer.start_as_current_span(
            "runtime_executor.run",
            attributes={"session_id": str(session_id)},
        ) as span:
            job_data = await data_client.get_session(session_id)
            if not job_data:
                logger.error("AgentJob %s not found during executor run", session_id)
                return

            try:
                context = await data_client.get_agent_context(job_data["agent_type_id"])
                guardrail_state = self._build_guardrail_state(context, job_data)
                await self._precheck_delegation_graph(
                    session_id=session_id,
                    agent_type_slug=str(context.get("agent_type_slug") or context.get("agent_type_id") or job_data["agent_type_id"]),
                    context=context,
                    data_client=data_client,
                    guardrail_state=guardrail_state,
                )
                await self._preflight_model_availability(
                    session_id=session_id,
                    context=context,
                    data_client=data_client,
                )
                output_data = await self._run_task_loop_ar(
                    job_data, context, data_client, response_value=response_value,
                )

                # Phase 4: Typed output persistence — if the agent type has an
                # assigned output_data_type_id, validate and persist the output
                # via Control Center internal endpoints before marking the session
                # as completed.
                output_data_type_id = context.get("output_data_type_id") if isinstance(context, dict) else None
                typed_output_id: str | None = None
                if output_data_type_id and isinstance(output_data, dict):
                    try:
                        data_type_id = uuid.UUID(output_data_type_id)
                        # Extract payload from output_data.
                        # Priority: explicit field_values dict > structured output dict (excluding
                        # runtime-only keys) > JSON-parse the plain-text result string.
                        raw_result = output_data.get("result")
                        if output_data.get("field_values") and isinstance(output_data["field_values"], dict):
                            payload: Any = output_data["field_values"]
                        elif raw_result is None and len(output_data) > 1:
                            # output_data itself is the structured output (from _extract_structured_output)
                            # Strip runtime-injected keys before validation
                            payload = {k: v for k, v in output_data.items() if k not in ("model_id", "output_id")}
                        elif isinstance(raw_result, str):
                            # Agent returned plain text — try to parse as JSON first
                            import json as _json
                            try:
                                parsed = _json.loads(raw_result)
                                payload = parsed if isinstance(parsed, dict) else {"value": raw_result}
                            except (_json.JSONDecodeError, ValueError):
                                payload = {"value": raw_result}
                        elif isinstance(raw_result, dict):
                            payload = raw_result
                        else:
                            payload = output_data

                        # Step 1: Validate the output against the data type schema
                        validation_result = await data_client.validate_typed_output(
                            data_type_id=data_type_id,
                            payload=payload if isinstance(payload, dict) else {"value": payload},
                        )

                        is_valid = validation_result.get("valid", False)
                        validation_errors = validation_result.get("errors", [])

                        # Step 2: Persist the typed output (even if validation failed)
                        raw_output = (
                            str(payload) if not is_valid else None
                        )
                        typed_response = await data_client.persist_typed_output(
                            data_type_id=data_type_id,
                            agent_type_id=uuid.UUID(job_data["agent_type_id"]),
                            session_id=session_id,
                            field_values=payload if is_valid and isinstance(payload, dict) else None,
                            validation_status="valid" if is_valid else "validation_error",
                            raw_output=raw_output,
                        )
                        typed_output_id = typed_response.get("id")

                        if typed_output_id:
                            # Include output_id in output_data so it flows to
                            # mark_session_completed and persists to AgentJob
                            output_data["output_id"] = typed_output_id

                        # Enrich output_data with typed metadata so the frontend
                        # can detect and render typed outputs properly.
                        data_type_name = context.get("output_data_type_name") if isinstance(context, dict) else None
                        output_data["__output_type"] = "typed"
                        output_data["__data_type_id"] = str(data_type_id)
                        if data_type_name:
                            output_data["__data_type_name"] = data_type_name
                        output_data["validation_status"] = "valid" if is_valid else "validation_error"
                        if not is_valid and raw_output:
                            output_data["raw_output"] = raw_output
                        # Merge actual field values into output_data at top level
                        if isinstance(payload, dict) and is_valid:
                            for key, val in payload.items():
                                if not key.startswith("__") and key not in output_data:
                                    output_data[key] = val

                        logger.info(
                            "Typed output for session %s: valid=%s output_id=%s",
                            session_id, is_valid, typed_output_id,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Typed output persistence failed for session %s: %s — "
                            "continuing with untyped completion",
                            session_id, exc,
                        )

                await data_client.mark_session_completed(session_id, output_data)
                span.set_attribute("status", "completed")

                _out_type_name = (
                    output_data.get("__data_type_name")
                    or (context.get("output_data_type_name") if isinstance(context, dict) else None)
                ) if output_data else None
                _result_text = (
                    output_data.get("result") or output_data.get("content") or output_data.get("output")
                ) if output_data else None
                _result_preview = (
                    str(_result_text)[:200].strip() + ("\u2026" if len(str(_result_text)) > 200 else "")
                ) if isinstance(_result_text, str) and _result_text.strip() else None
                _completion_msg = "Session completed successfully"
                if _out_type_name:
                    _completion_msg = f"Session completed \u2014 output type: {_out_type_name}"
                await data_client.log_execution_event(
                    session_id=session_id,
                    event_type="session_completed",
                    message=_completion_msg,
                    data={
                        "output_keys": list(output_data.keys()) if output_data else [],
                        **({
                            "output_type": _out_type_name,
                            **({
                                "result_preview": _result_preview,
                            } if _result_preview else {}),
                        } if _out_type_name else {}),
                    },
                )
            except HumanInterveneRequired:
                logger.info("Session %s paused for human intervention", session_id)
                span.set_attribute("status", "waiting_for_human")
            except GuardrailStop as exc:
                logger.warning("Session %s guardrail stop: %s", session_id, exc.reason)
                await data_client.log_execution_event(
                    session_id=session_id,
                    event_type="guardrail.session.terminal",
                    log_level="INFO",
                    message=exc.message,
                    data={
                        "guardrail_reason": exc.reason,
                        "stop_category": "guardrail_stop",
                        **(exc.details or {}),
                    },
                )
                await data_client.mark_session_failed(
                    session_id,
                    exc.message,
                    stop_category="guardrail_stop",
                    stop_reason=exc.reason,
                    stop_details=exc.details,
                )
                span.set_attribute("status", "guardrail_stop")
            except ModelAvailabilityBlockedError as exc:
                logger.warning(
                    "Session %s blocked by availability preflight: %s",
                    session_id,
                    exc.blocked_by,
                )
                # Map blocked_by to event_category / termination_category
                # vocabulary from the data model:
                #   "vendor_disabled"     -> vendor_disabled
                #   "model_disabled"      -> model_disabled
                #   "model_not_found"     -> model_disabled (closest sibling)
                #   "guardrail_breached"  -> guardrail_breached
                #   anything else         -> model_disabled (conservative)
                if exc.blocked_by == "vendor_disabled":
                    event_category = "vendor_disabled"
                    termination_category = "vendor_disabled"
                    stop_reason = "vendor_disabled"
                    stop_category = "guardrail_stop"
                elif exc.blocked_by == "guardrail_breached":
                    event_category = "guardrail_breached"
                    termination_category = "guardrail_breached"
                    stop_reason = "guardrail_breached"
                    stop_category = "guardrail_stop"
                else:
                    event_category = "model_disabled"
                    termination_category = "model_disabled"
                    stop_reason = "model_disabled"
                    stop_category = "guardrail_stop"
                await data_client.log_execution_event(
                    session_id=session_id,
                    event_type="model_availability.blocked",
                    log_level="WARN",
                    message=exc.message,
                    event_category=event_category,
                    data={
                        "blocked_by": exc.blocked_by,
                        "disabled_reason": exc.disabled_reason,
                        **(exc.details or {}),
                    },
                )
                await data_client.mark_session_failed(
                    session_id,
                    exc.message,
                    stop_category=stop_category,
                    stop_reason=stop_reason,
                    stop_details={
                        "termination_category": termination_category,
                        "blocked_by": exc.blocked_by,
                        "disabled_reason": exc.disabled_reason,
                        **(exc.details or {}),
                    },
                )
                span.set_attribute("status", "availability_blocked")
                span.set_attribute("blocked_by", exc.blocked_by)
            except PermissionDeniedError as exc:
                error_msg = f"Permission denied: {exc}"
                logger.warning("Session %s permission denied: %s", session_id, exc)
                await data_client.log_execution_event(
                    session_id=session_id,
                    event_type="error",
                    message=error_msg,
                    data={"exception_type": type(exc).__name__},
                    log_level="ERROR",
                )
                await data_client.mark_session_failed(
                    session_id,
                    error_msg,
                    stop_category="functional_failure",
                )
                span.set_attribute("status", "permission_denied")
            except Exception as exc:
                exc_type = type(exc).__name__
                exc_str = str(exc).strip()
                error_msg = f"{exc_type}: {exc_str}" if exc_str else exc_type
                logger.exception("Session %s execution error: %s", session_id, exc)
                await data_client.log_execution_event(
                    session_id=session_id,
                    event_type="error",
                    message=error_msg,
                    data={"exception_type": exc_type},
                    log_level="ERROR",
                )
                await data_client.mark_session_failed(
                    session_id,
                    error_msg,
                    stop_category="functional_failure",
                )
                span.set_attribute("status", "failed")
                span.set_attribute("error", error_msg)

    async def _run_task_loop_ar(
        self,
        job_data: dict[str, Any],
        context: dict[str, Any],
        data_client: "ControlCenterDataClient",
        response_value: dict | None = None,
    ) -> dict[str, Any]:
        """Execute a task agent using pre-fetched context from Control Center.

        When ``response_value`` is set (resume after human intervention), the
        human's response is injected as a follow-up message so the LLM can
        continue without re-requesting input.

        No database access — all data comes from ``context`` (the CC agent context API
        response) and all logging flows through ``data_client``.
        """
        from app.services.agents.agent_loop import TaskAgentLoop, ConversationalAgentLoop

        session_id = uuid.UUID(job_data["id"])
        agent_type_id = job_data["agent_type_id"]
        input_data = job_data.get("input_data") or {}

        # Extract conversation session ID for delegation context
        self._conv_session_id: str | None = input_data.get("__conv_session_id")

        logger.info("Session %s: agent initializing (model=%s%s)",
            session_id,
            context.get("model_id", "unknown"),
            " [resume]" if response_value else "",
        )

        # ── Log session_started ───────────────────────────────────────────────
        await data_client.log_execution_event(
            session_id=session_id,
            event_type="session_started",
            message="Session execution started",
            data={
                "agent_type_id": agent_type_id,
                "model_id": context.get("model_id"),
                "input_type": context.get("input_type"),
                "system_instruction_length": len(context.get("system_instruction") or ""),
                "identity_name": context.get("identity_name"),
                "role_name": context.get("role_name"),
            },
        )

        # ── Resolve allowed tools from context ────────────────────────────────
        allowed_tools = self._permission_manager.get_allowed_tools_from_context(
            context.get("allowed_tools") or []
        )
        allowed_tool_names = _canonicalize_tool_list_for_log(allowed_tools)

        await data_client.log_execution_event(
            session_id=session_id,
            event_type="tools_resolved",
            message=f"Resolved {len(allowed_tools)} allowed tool(s)",
            data={
                "allowed_tools": allowed_tool_names,
                "role_name": context.get("role_name"),
            },
        )

        # ── Log SOPs / Skills ─────────────────────────────────────────────────
        sops = context.get("sops") or []
        skills = context.get("skills") or []
        await data_client.log_execution_event(
            session_id=session_id,
            event_type="sops_skills_loaded",
            message=f"Loaded {len(sops)} SOP(s) and {len(skills)} Skill(s) for role",
            data={
                "role_id": context.get("role_id"),
                "sops": sops,
                "skills": skills,
            },
        )

        # ── Build system instruction with binding + MCP context ──────────────
        system_instruction: str | None = context.get("system_instruction")
        binding_content: str | None = context.get("sop_content")
        if binding_content:
            base = system_instruction or ""
            system_instruction = f"{base}\n\n{binding_content}".strip()
            await data_client.log_execution_event(
                session_id=session_id,
                event_type="binding_content_loaded",
                message="Binding content loaded into system instruction",
                data={
                    "agent_type_id": context.get("agent_type_id"),
                    "binding_content_preview": binding_content[:300],
                    "total_instruction_length": len(system_instruction),
                },
                )

        mcp_context: str | None = context.get("mcp_session_context")
        if mcp_context:
            base = system_instruction or ""
            system_instruction = f"{base}\n\n{mcp_context}".strip()
            await data_client.log_execution_event(
                session_id=session_id,
                event_type="mcp_context_loaded",
                message="MCP session context loaded into system instruction",
                data={
                    "role_id": context.get("role_id"),
                    "mcp_context_preview": mcp_context[:300],
                    "total_instruction_length": len(system_instruction),
                },
            )

        # ── Inject plan ───────────────────────────────────────────────────────
        plan_data = await data_client.get_agent_plan(uuid.UUID(agent_type_id))
        if plan_data:
            plan_text = self._runtime_loader.format_plan_for_injection(plan_data)
            if plan_text.strip():
                base = system_instruction or ""
                system_instruction = f"{base}{plan_text}".strip()
                await data_client.log_execution_event(
                    session_id=session_id,
                    event_type="plan_injected",
                    message="Pre-approved plan injected into system instruction",
                    data={
                        "agent_type_id": agent_type_id,
                        "total_instruction_length": len(system_instruction),
                    },
                )

        # ── Build tool definitions from context ───────────────────────────────
        tool_definitions: list[dict[str, Any]] = context.get("tool_definitions") or list(SystemToolRegistry.get_all_schemas())
        tool_name_map: dict[str, str] = context.get("tool_name_map") or {}
        role_mcp_sessions: dict[str, dict[str, str]] = context.get("role_mcp_sessions") or {}
        allowed_agent_types: set[str] = set(context.get("allowed_agent_types") or [])

        # ── Initialize Communication Hub tool client ──────────────────────────
        from app.agent_runtime.comm_hub_client import CommHubToolClient

        comm_hub_client = CommHubToolClient()
        
        # Configure mTLS certificate for authentication with Communication Hub
        # Get certificate paths from the CertificateManager via data_client
        cert_manager = getattr(data_client, "_cert_manager", None)
        logger.debug(
            "Session %s: Configuring CommHubToolClient - cert_manager=%s",
            session_id,
            "available" if cert_manager else "None",
        )
        
        if cert_manager:
            cert_path = cert_manager.cert_path
            key_path = cert_manager.key_path
            logger.debug(
                "Session %s: Certificate paths - cert_path=%s, key_path=%s",
                session_id,
                cert_path,
                key_path,
            )
            
            if cert_path and key_path:
                cert_path_str = str(cert_path)
                key_path_str = str(key_path)
                comm_hub_client.set_certificate(cert_path_str, key_path_str)
                logger.debug(
                    "Session %s: CommHubToolClient configured with mTLS certificate from CertificateManager",
                    session_id,
                )
            else:
                logger.warning(
                    "Session %s: CertificateManager cert_path or key_path is None - "
                    "Communication Hub tool calls will fail authentication",
                    session_id,
                )
        else:
            logger.warning(
                "Session %s: CertificateManager not available - "
                "Communication Hub tool calls will fail authentication",
                session_id,
            )

        # ── Format user prompt ────────────────────────────────────────────────
        user_prompt: str | None = None
        if isinstance(input_data, dict):
            user_prompt = input_data.get("message") or input_data.get("prompt")
            if not user_prompt and input_data:
                user_prompt = json.dumps(input_data)
        elif input_data:
            user_prompt = str(input_data)

        # Snapshot tool and instruction state before first LLM call so we can
        # diagnose why a system tool was not selected.
        tool_def_names = _canonicalize_tool_list_for_log(
            _tool_names_from_definitions(tool_definitions),
            tool_name_map,
        )
        allowed_tool_names = _canonicalize_tool_list_for_log(allowed_tools)
        route_summary = {
            "system": sorted([t for t in tool_def_names if _tool_route_type(t) == "system"]),
            "agent": sorted([t for t in tool_def_names if _tool_route_type(t) == "agent"]),
            "mcp": sorted([t for t in tool_def_names if _tool_route_type(t) == "mcp"]),
        }
        await self._log_execution_event(
            session_id=session_id,
            event_type="agent_initialized",
            message="Agent initialized and ready for execution",
            data={
                "tools": tool_def_names,
                "tool_count": len(tool_def_names),
                "allowed_tools": allowed_tool_names,
                "tool_definitions": sorted(tool_def_names),
                "tool_routes": route_summary,
                "has_send_notification_tool": build_tool_name("system", "send_notification") in tool_def_names,
                "model_id": context.get("model_id"),
                "sops": [s.get("name") for s in (context.get("sops") or []) if isinstance(s, dict)],
                "skills": [s.get("name") for s in (context.get("skills") or []) if isinstance(s, dict)],
                "has_plan": bool(plan_data),
                "has_output_schema": bool(context.get("output_json_schema") if isinstance(context, dict) else None),
                "output_data_type_name": context.get("output_data_type_name"),
                "is_resume": bool(response_value),
                "system_instruction": system_instruction,
                "system_instruction_length": len(system_instruction or ""),
                "user_prompt": user_prompt,
                "user_prompt_length": len(user_prompt or ""),
            },
            data_client=data_client,
        )

        # ── Fetch model config ────────────────────────────────────────────────
        model_config_id = context.get("model_config_id")
        model_config_dict: dict[str, Any] = {}
        if model_config_id:
            try:
                model_config_dict = await data_client.get_model_config(uuid.UUID(model_config_id))
            except Exception as exc:
                logger.warning("Failed to fetch model config %s: %s", model_config_id, exc)

        model_id: str = context.get("model_id") or ""
        guardrail_state = self._build_guardrail_state(context, job_data)
        execution_mode = "non_conversational"

        # ── Build conversation history using native LangChain message types ───
        from langchain_core.messages import (
            AIMessage, HumanMessage, ToolMessage,
            messages_from_dict, convert_to_messages,
        )

        messages: list[Any] = []

        saved_history = job_data.get("conversation_history")
        if saved_history and isinstance(saved_history, list) and len(saved_history) > 0:
            # Restore saved state as proper LangChain message objects.
            # conversation_history is stored by _messages_to_dicts() which uses
            # messages_to_dict() → {"type": "human", "data": {...}} format.
            # Use messages_from_dict() to deserialize, not convert_to_messages()
            # which only handles OpenAI {"role": "...", "content": "..."} format.
            first = saved_history[0]
            if isinstance(first, dict) and "data" in first and "type" in first:
                messages = list(messages_from_dict(saved_history))
            else:
                # Fallback: OpenAI-format or already coercible by LangChain
                messages = convert_to_messages(saved_history)
            if response_value:
                # Find the last human_intervene tool call id in the saved history
                call_id: str | None = None
                for msg in reversed(messages):
                    if isinstance(msg, AIMessage) and msg.tool_calls:
                        for tc in msg.tool_calls:
                            name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                            if name == "human_intervene":
                                call_id = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")
                                break
                    if call_id:
                        break
                if call_id:
                    messages.append(ToolMessage(
                        content=json.dumps(response_value),
                        tool_call_id=call_id,
                    ))
                messages.append(HumanMessage(
                    content=(
                        "Human intervention has been resolved. "
                        "Your plan's human_intervene step is now COMPLETE. "
                        "Move to the NEXT step in your plan immediately. "
                        "Do NOT call human_intervene again."
                    )
                ))
                await data_client.log_execution_event(
                    session_id=session_id,
                    event_type="human_response_injected",
                    message="Human intervention response injected for resumed session",
                    data={"response_value": response_value},
                )
        elif response_value:
            # Legacy path: no saved history — build synthetic tool-call context
            formatted = json.dumps(response_value)
            messages.append(AIMessage(
                content="",
                tool_calls=[{
                    "id": "call_resume_context",
                    "name": "human_intervene",
                    "args": {"intervention_type": "approval", "reason": "Requested human input"},
                }],
            ))
            messages.append(ToolMessage(
                content=formatted,
                tool_call_id="call_resume_context",
            ))
            messages.append(HumanMessage(
                content=(
                    "Human intervention has been resolved. "
                    "Your plan's human_intervene step is now COMPLETE. "
                    "Move to the NEXT step in your plan immediately. "
                    "Do NOT call human_intervene again."
                )
            ))
            await data_client.log_execution_event(
                session_id=session_id,
                event_type="human_response_injected",
                message="Human intervention response injected for resumed session (legacy)",
                data={"response_value": response_value},
            )
        else:
            if user_prompt:
                messages.append(HumanMessage(content=user_prompt))

        # ── Build LangChain callbacks ─────────────────────────────────────────
        from app.services.agents.guardrail_callback import GuardrailCallback
        from app.services.agents.execution_logging_callback import ExecutionLoggingCallback

        iteration_ref = [0]
        lc_callbacks: list[Any] = [
            GuardrailCallback(
                guardrail_state=guardrail_state,
                session_id=str(session_id),
                data_client=data_client,
                execution_mode=execution_mode,
            ),
            ExecutionLoggingCallback(
                session_id=str(session_id),
                data_client=data_client,
                iteration_ref=iteration_ref,
            ),
        ]

        # ── Build structured output schema (task 9.8) ─────────────────────────
        output_json_schema: dict[str, Any] | None = None
        if isinstance(context, dict):
            schema = context.get("output_json_schema")
            if isinstance(schema, dict):
                output_json_schema = schema

        # ── Stub mode (LangChain unavailable) ─────────────────────────────────
        if not _LANGCHAIN_AVAILABLE or not model_config_dict:
            await data_client.log_execution_event(
                session_id=session_id,
                event_type="llm_response",
                message="LLM response (stub) — LangChain not available",
                log_level="WARN",
                data={"stub": True, "langchain_available": _LANGCHAIN_AVAILABLE},
            )
            return {
                "result": "Task completed (stub executor — LangChain unavailable)",
                "session_id": str(session_id),
                "guardrail_usage": {
                    "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                    "cumulative_iterations": 0,
                    "token_usage_current_session": 0,
                },
            }

        # ── Build LangChain model ─────────────────────────────────────────────
        from app.services.agents.langchain_model_factory import LangChainModelFactory

        try:
            _factory = LangChainModelFactory()
            _llm = _factory.get_model_from_config_dict(
                model_id=model_id,
                model_config_dict=model_config_dict,
            )
        except Exception as _model_exc:
            logger.error(
                "Failed to create LangChain model for AR session %s: %s", session_id, _model_exc
            )
            return {
                "result": f"Failed to initialise model: {_model_exc}",
                "session_id": str(session_id),
                "error": str(_model_exc),
            }

        # ── Build response_format for structured output ────────────────────────
        # ToolStrategy uses tool calling — works on any model that supports tools.
        # LangChain auto-promotes to ProviderStrategy when the model capability
        # profile reports native structured-output support.
        from langchain.agents.structured_output import ToolStrategy

        response_format: Any = ToolStrategy(schema=output_json_schema) if output_json_schema else None

        # ── Capture prompt log (after final system instruction is known) ──────
        await data_client.log_prompt(
            session_id=session_id,
            system_instruction=system_instruction,
            user_prompt=user_prompt,
        )

        # ── Build LangChain tools (task 9.7) ─────────────────────────────────
        from app.services.agents.langchain_tool_wrapper import build_langchain_tools_for_ar_path

        lc_tools = build_langchain_tools_for_ar_path(
            tool_definitions=tool_definitions,
            comm_hub_client=comm_hub_client,
            data_client=data_client,
            session_id=str(session_id),
            agent_type_id=agent_type_id or "",
            conv_session_id=getattr(self, "_conv_session_id", None),
            tool_name_map=tool_name_map,
            role_id=str(context.get("role_id") or ""),
            guardrail_state=guardrail_state,
        )

        # ── Create agent (task 9.6/9.7) ───────────────────────────────────────
        from langchain.agents import create_agent
        from langgraph.checkpoint.memory import MemorySaver

        _checkpointer = MemorySaver()
        _recursion_limit = max(1, guardrail_state.max_iterations) * 3 + 1

        # Disable parallel tool calls when delegation tools are present so the LLM
        # executes agent delegation tools one at a time (sequential, as SOPs require).
        # NOTE: _llm.bind(parallel_tool_calls=False) does NOT work here — create_agent()
        # internally calls model.bind_tools() which creates a new _ChatModelBinding that
        # REPLACES the .bind() wrapper, losing the setting. The correct approach is to bake
        # parallel_tool_calls=False into the model's model_kwargs via model_copy() so it
        # survives any subsequent bind_tools() call.
        # Note: sanitized tool names replace '-' with '_' but preserve the 4-underscore
        # agent____ prefix, so startswith("agent____") correctly identifies delegation tools.
        _has_delegation_tools = any(t.name.startswith("agent____") for t in lc_tools)
        if _has_delegation_tools:
            try:
                _existing_mk = dict(getattr(_llm, 'model_kwargs', None) or {})
                _existing_mk['parallel_tool_calls'] = False
                _llm = _llm.model_copy(update={'model_kwargs': _existing_mk})
                logger.info(
                    "Session %s: parallel_tool_calls=False set via model_kwargs (delegation tools present)",
                    session_id,
                )
            except Exception as _bind_exc:
                logger.warning(
                    "Session %s: could not set parallel_tool_calls=False: %s",
                    session_id, _bind_exc,
                )

        _agent = create_agent(
            model=_llm,
            tools=lc_tools,
            system_prompt=system_instruction or None,
            response_format=response_format,
            checkpointer=_checkpointer,
        )
        _config: dict[str, Any] = {
            "configurable": {"thread_id": str(session_id)},
            "callbacks": lc_callbacks,
            "recursion_limit": _recursion_limit,
        }

        # ── Invoke agent ──────────────────────────────────────────────────────
        # LangGraph 1.1.10 behaviour: when interrupt() is called inside a tool,
        # ainvoke() does NOT raise GraphInterrupt — it returns the state dict
        # with a "__interrupt__" key containing a list of Interrupt objects.
        # We keep the except GraphInterrupt clause as a legacy fallback, but
        # the primary HITL detection is a post-return check on _result.
        from langgraph.errors import GraphInterrupt

        try:
            _result = await _agent.ainvoke(
                {"messages": messages},
                config=_config,
            )
        except GraphInterrupt as _gi:
            # Fallback: older LangGraph versions that raise instead of returning
            _pending_interrupts: list[Any] = getattr(_gi, "interrupts", [])
            _interrupt_payload: dict[str, Any] = (
                _pending_interrupts[0].value if _pending_interrupts else {}
            )
            _request_id = _interrupt_payload.get("request_id") or None

            try:
                _agent_state = await _agent.aget_state(_config)
                _conv_history = _messages_to_dicts(
                    _agent_state.values.get("messages", [])
                )
            except Exception as _state_exc:
                logger.warning(
                    "Could not extract agent state after interrupt for session %s: %s",
                    session_id, _state_exc,
                )
                _conv_history = messages

            await data_client.mark_session_waiting_for_human(
                session_id,
                _request_id,
                conversation_history=_conv_history,
            )
            await data_client.log_execution_event(
                session_id=session_id,
                event_type="human_intervene_requested",
                message="Human intervention requested — session paused",
                data={"request_id": _request_id, "payload": _interrupt_payload},
            )
            raise HumanInterveneRequired()

        except GuardrailStop:
            raise

        # ── LangGraph 1.1.10: detect interrupt from return value ─────────────
        # ainvoke() returns {"__interrupt__": [Interrupt(...)], "messages": [...]}
        # when interrupt() was called inside a tool node.
        _pending_interrupts_in_result: list[Any] = (
            _result.get("__interrupt__", []) if isinstance(_result, dict) else []
        )
        if _pending_interrupts_in_result:
            _intr_obj = _pending_interrupts_in_result[0]
            _interrupt_payload = (
                _intr_obj.value if hasattr(_intr_obj, "value") else {}
            )
            _request_id = (
                _interrupt_payload.get("request_id", "")
                if isinstance(_interrupt_payload, dict) else ""
            ) or None  # send None rather than "" to avoid UUID parse errors in CC
            logger.info(
                "Session %s interrupted (LangGraph return-based): request_id=%s",
                session_id, _request_id,
            )

            try:
                _agent_state = await _agent.aget_state(_config)
                _conv_history = _messages_to_dicts(
                    _agent_state.values.get("messages", [])
                )
            except Exception as _state_exc:
                logger.warning(
                    "Could not extract agent state after interrupt for session %s: %s",
                    session_id, _state_exc,
                )
                _conv_history = messages

            await data_client.mark_session_waiting_for_human(
                session_id,
                _request_id,
                conversation_history=_conv_history,
            )
            await data_client.log_execution_event(
                session_id=session_id,
                event_type="human_intervene_requested",
                message="Human intervention requested — session paused",
                data={"request_id": _request_id, "payload": _interrupt_payload},
            )
            raise HumanInterveneRequired()

        # ── Extract output_data ───────────────────────────────────────────────
        _structured_response = _result.get("structured_response")
        _final_messages: list[Any] = _result.get("messages", [])

        if _structured_response is not None:
            # Typed structured output from response_format (task 9.8)
            if hasattr(_structured_response, "model_dump"):
                output_data = _structured_response.model_dump()
            elif isinstance(_structured_response, dict):
                output_data = _structured_response
            else:
                output_data = {"result": str(_structured_response)}
        else:
            # Extract text from final message
            _last_msg = _final_messages[-1] if _final_messages else None
            _content: Any = (
                getattr(_last_msg, "content", "") if _last_msg else ""
            ) or ""
            # Normalize to a plain string: Anthropic and some other providers return
            # content as a list of content blocks ([{"type":"text","text":"..."},...])
            # rather than a plain string. Extract text blocks and join them.
            if isinstance(_content, list):
                _text_parts = [
                    block.get("text", "")
                    for block in _content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                _content = "\n\n".join(part for part in _text_parts if part)
            output_data = {"result": _content}

        # Attach guardrail usage (current counters + configured limits)
        output_data.setdefault("guardrail_usage", {
            "policy_snapshot_id": guardrail_state.policy_snapshot_id,
            "cumulative_iterations": guardrail_state.cumulative_iterations,
            "delegated_steps": guardrail_state.delegated_steps,
            "delegation_depth": guardrail_state.delegation_depth,
            "elapsed_seconds": guardrail_state.elapsed_seconds(),
            "token_usage_current_session": guardrail_state.token_usage_current_session,
        })

        _guardrail_log = {
            **output_data.get("guardrail_usage", {}),
            "current_value": {
                "cumulative_iterations": guardrail_state.cumulative_iterations,
                "delegated_steps": guardrail_state.delegated_steps,
                "delegation_depth": guardrail_state.delegation_depth,
                "elapsed_seconds": guardrail_state.elapsed_seconds(),
                "token_usage_current_session": guardrail_state.token_usage_current_session,
            },
            "threshold_value": {
                "max_iterations": guardrail_state.max_iterations,
                "max_delegation_depth": guardrail_state.max_delegation_depth,
                "max_delegated_steps": guardrail_state.max_delegated_steps,
                "token_budget": guardrail_state.token_budget,
                "execution_timeout_seconds": guardrail_state.execution_timeout_seconds,
            },
        }

        await data_client.log_execution_event(
            session_id=session_id,
            event_type="task_loop_completed",
            message="Task loop completed via create_agent",
            data={
                "output_keys": list(output_data.keys()),
                "guardrail": _guardrail_log,
            },
        )
        return output_data


    async def _execute_mcp_tool_ar(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        role_mcp_sessions: dict[str, dict[str, str]],
        agent_type_id: str | None,
        session_id: str,
        comm_hub_client: "CommHubToolClient",
        conv_session_id: str | None = None,
    ) -> dict[str, Any]:
        """Dispatch tool call from Agent Runtime via Communication Hub (no DB access).

        Routes ALL tools (external MCP + system tools) through Communication Hub:
        - Permission validation (via Control Center)
        - Credential retrieval (from Control Center)
        - Routing to MCP servers or system tool endpoints

        Args:
            tool_name: Tool name (e.g., "hello-world/helloWorld", "save_result")
            tool_args: Tool arguments
            role_mcp_sessions: Session mapping (not used - for backward compatibility)
            agent_type_id: Agent type ID
            session_id: Agent session ID
            comm_hub_client: Communication Hub tool client
            conv_session_id: Parent conversation session ID (for conversation-context interventions)

        Returns:
            Tool execution result
        """
        from app.agent_runtime.comm_hub_client import CommHubToolClientError

        try:
            # Use conversation session ID from delegation context if available
            effective_conv_session_id = conv_session_id or getattr(self, "_conv_session_id", None)
            result = await comm_hub_client.call_tool(
                tool_name=tool_name,
                tool_args=tool_args,
                session_id=session_id,
                agent_type_id=agent_type_id or "",
                conv_session_id=effective_conv_session_id,
            )
            return result
        except CommHubToolClientError as exc:
            logger.warning("Tool %s failed via Communication Hub: %s", tool_name, exc)
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("Unexpected error calling tool %s", tool_name)
            return {"error": str(exc)}

    async def execute_conversation_turn(
        self,
        agent_type: Any,
        messages: list[dict[str, Any]],
        conv_session_id: uuid.UUID,
        db: AsyncSession,
        cert_path: str | None = None,
        key_path: str | None = None,
    ) -> str:
        """Execute one WebSocket conversation turn using the full observe-reason-act loop.

        Receives the complete message list (system instruction + conversation history)
        and runs the same tool-calling loop used by task agents, giving conversation
        agents access to SOPs, Skills, and MCP tools.

        Unlike the task loop this method does NOT write to ``execution_log_entries``
        (which has a FK to ``agent_jobs``) — it uses the Python logger instead.

        Returns the final text response from the agent.
        """
        from app.db.models.agents import AgentTypeSopBinding, AgentTypeSkillBinding
        from app.services.agents.model_binding import ModelBindingLayer
        from sqlalchemy import select as _sel

        # Resolve model config via ModelBindingLayer seam (enables patching in tests)
        binding = ModelBindingLayer()
        model_config = await binding.resolve_model_config(agent_type.model_id, db)

        # Query AgentType bindings for permission scoping
        bind_sop_rows = await db.execute(
            _sel(AgentTypeSopBinding.sop_id).where(
                AgentTypeSopBinding.agent_type_id == agent_type.id
            )
        )
        bound_sop_ids: set[uuid.UUID] = {row[0] for row in bind_sop_rows.fetchall()}

        bind_skill_rows = await db.execute(
            _sel(AgentTypeSkillBinding.skill_id).where(
                AgentTypeSkillBinding.agent_type_id == agent_type.id
            )
        )
        bound_skill_ids: set[uuid.UUID] = {row[0] for row in bind_skill_rows.fetchall()}

        has_bindings = bool(bound_sop_ids or bound_skill_ids)

        # Resolve allowed tools for the agent's role, scoped by AgentType bindings
        allowed_tools: set[str] = set()
        if agent_type.role_id:
            pm_sop_overrides = bound_sop_ids if (has_bindings and bound_sop_ids) else None
            pm_skill_overrides = bound_skill_ids if (has_bindings and bound_skill_ids) else None

            allowed_tools = await self._permission_manager.calculate_allowed_tools(
                agent_type.role_id, db,
                override_sop_ids=pm_sop_overrides,
                override_skill_ids=pm_skill_overrides,
            )
            delegated_agent_types = await self._permission_manager.calculate_allowed_agent_types(
                agent_type.role_id,
                db,
                override_sop_ids=pm_sop_overrides if has_bindings else None,
            )
            allowed_tools.update(
                {build_tool_name("agent", slug) for slug in delegated_agent_types}
            )

        # Conversation agents should only see explicitly granted system tools.
        tool_definitions, tool_name_map = await self._load_tool_definitions(
            allowed_tools,
            db,
            include_all_system_tools=False,
        )

        # Load MCP session map for tool dispatch
        role_mcp_sessions: dict[str, dict[str, str]] = {}
        if agent_type.role_id:
            role_mcp_sessions = await self._load_role_mcp_session_map(agent_type.role_id, db)

        # ── Initialize Communication Hub tool client (mirrors _run_task_loop_ar) ──
        from app.agent_runtime.comm_hub_client import CommHubToolClient

        comm_hub_client = CommHubToolClient()
        if cert_path and key_path:
            comm_hub_client.set_certificate(cert_path, key_path)
            logger.info(
                "Conversation turn %s: CommHubToolClient configured with Agent Runtime certificate",
                conv_session_id,
            )
        logger.info(
            "Conversation turn %s: CommHubToolClient initialized",
            conv_session_id,
        )

        logger.info(
            "Conversation turn starting: session=%s agent=%s role=%s tools=%d",
            conv_session_id,
            agent_type.id,
            agent_type.role_id,
            len(tool_definitions),
        )

        system_instruction: str | None = None
        last_user_prompt: str | None = None
        user_message_count = 0
        assistant_message_count = 0
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "system" and isinstance(content, str):
                system_instruction = content
            elif role == "user" and isinstance(content, str):
                user_message_count += 1
                last_user_prompt = content
            elif role == "assistant":
                assistant_message_count += 1

        allowed_tool_names = _canonicalize_tool_list_for_log(allowed_tools)
        logger.info(
            "Conversation runtime initialized: session=%s agent=%s role=%s allowed_tools=%s",
            conv_session_id,
            agent_type.id,
            agent_type.role_id,
            allowed_tool_names,
        )
        conv_tool_names = _canonicalize_tool_list_for_log(
            _tool_names_from_definitions(tool_definitions),
            tool_name_map,
        )
        logger.info(
            "Conversation runtime tools: session=%s total=%d system=%s agent=%s mcp=%s has_send_notification=%s",
            conv_session_id,
            len(conv_tool_names),
            sorted([t for t in conv_tool_names if _tool_route_type(t) == "system"]),
            sorted([t for t in conv_tool_names if _tool_route_type(t) == "agent"]),
            sorted([t for t in conv_tool_names if _tool_route_type(t) == "mcp"]),
            build_tool_name("system", "send_notification") in conv_tool_names,
        )
        logger.info(
            "Conversation prompt captured: session=%s system_instruction_length=%d user_prompt_length=%d",
            conv_session_id,
            len(system_instruction or ""),
            len(last_user_prompt or ""),
            extra={
                "data": {
                    "system_instruction": system_instruction,
                    "user_prompt": last_user_prompt,
                    "message_count": len(messages),
                    "user_message_count": user_message_count,
                    "assistant_message_count": assistant_message_count,
                }
            },
        )

        # Work on a local copy so we don't mutate the caller's list
        local_messages = list(messages)

        max_iterations = 10
        for iteration in range(max_iterations):
            logger.debug(
                "Conversation turn iteration %d for session %s", iteration + 1, conv_session_id
            )

            raw_response = await binding.complete(
                agent_type,
                model_config,
                local_messages,
                tool_definitions or None,
            )

            response_text = ModelBindingLayer.extract_text(raw_response, model_config.provider_type)
            raw_tool_calls = ModelBindingLayer.extract_tool_calls(raw_response, model_config.provider_type)

            if not raw_tool_calls:
                # No tool calls — this is the final answer
                logger.info(
                    "Conversation response finalized: session=%s iteration=%d response_length=%d",
                    conv_session_id,
                    iteration + 1,
                    len(response_text or ""),
                    extra={"data": {"response_text": response_text or ""}},
                )
                return response_text or "I processed your message but received an empty response."

            # Append assistant message with tool_calls before tool result messages (OpenAI requirement)
            local_messages.append({
                "role": "assistant",
                "content": response_text or "",
                "tool_calls": raw_tool_calls,
            })

            logger.info(
                "Conversation turn: agent called %d tool(s) in iteration %d: %s",
                len(raw_tool_calls),
                iteration + 1,
                [tc.get("function", {}).get("name", "") for tc in raw_tool_calls],
            )

            for tc in raw_tool_calls:
                sanitized_name = tc.get("function", {}).get("name", "")
                original_name = _restore_tool_name_from_openai(sanitized_name, tool_name_map)
                args_raw = tc.get("function", {}).get("arguments", "{}")
                args: dict[str, Any] = (
                    json.loads(args_raw)
                    if isinstance(args_raw, str)
                    else (args_raw if isinstance(args_raw, dict) else {})
                )
                call_id = tc.get("id", "")

                # Enforce permission boundary on every dispatch
                try:
                    self._permission_manager.check_tool_allowed(
                        original_name, allowed_tools, agent_type.role_id
                    )
                except PermissionDeniedError as exc:
                    tool_result: Any = {"error": f"Permission denied: {exc}"}
                    logger.warning(
                        "Tool %s denied in conversation session %s: %s",
                        original_name,
                        conv_session_id,
                        exc,
                    )
                else:
                    delegated_target_slug = _extract_agent_delegation_target(original_name)
                    if delegated_target_slug is not None:
                        tool_result = await comm_hub_client.call_a2a_request(
                            target_agent_type_slug=delegated_target_slug,
                            session_id=str(conv_session_id),
                            requester_role_id=str(agent_type.role_id) if agent_type.role_id else None,
                            request_payload=_build_delegation_request_payload(args),
                            session_link_id=args.get("session_link_id"),
                            wait_for_response=True,
                            wait_timeout_seconds=45.0,
                            conv_session_id=str(conv_session_id),
                        )
                    else:
                        logger.info(
                            "Conversation tool dispatch: session=%s tool=%s route_type=%s",
                            conv_session_id,
                            original_name,
                            _tool_route_type(original_name),
                        )
                        tool_result = await self._execute_mcp_tool_ar(
                            original_name,
                            args,
                            role_mcp_sessions,
                            str(agent_type.id),
                            str(conv_session_id),
                            comm_hub_client,
                            conv_session_id=str(conv_session_id),
                        )

                    local_messages.append({
                        "role": "tool",
                        "content": str(tool_result),
                        "tool_call_id": call_id,
                    })

        logger.warning(
            "Conversation turn exceeded max iterations (%d) for session %s",
            max_iterations,
            conv_session_id,
        )
        return "I was unable to complete the task within the allowed number of steps."

    async def execute_conversation_turn_from_context(
        self,
        agent_type_id: uuid.UUID,
        agent_context: dict[str, Any],
        model_config: dict[str, Any],
        messages: list[dict[str, Any]],
        conv_session_id: uuid.UUID,
        cert_path: str | None = None,
        key_path: str | None = None,
        status_event_callback: Callable[[dict[str, str]], Awaitable[None]] | None = None,
    ) -> tuple[str, dict[str, Any], list[dict[str, str]]]:
        """Execute one conversation turn using the same LangGraph/create_agent framework
        as non-conversational agents. Only input/output differ:
          - Input: full conversation message history (not a single user prompt)
          - Output: last assistant message text (not structured output_data)
        """
        # 1. Extract tool context
        allowed_tools = self._permission_manager.get_allowed_tools_from_context(
            agent_context.get("allowed_tools", [])
        )
        tool_definitions = list(agent_context.get("tool_definitions", []))
        tool_name_map = dict(agent_context.get("tool_name_map", {}))
        role_id_raw = agent_context.get("role_id")

        # 2. Extract system_instruction
        system_instruction = None
        for msg in messages:
            if msg.get("role") == "system":
                system_instruction = msg.get("content")
                break

        # 3. CommHub client (mTLS)
        from app.agent_runtime.comm_hub_client import CommHubToolClient
        comm_hub_client = CommHubToolClient()
        if cert_path and key_path:
            comm_hub_client.set_certificate(cert_path, key_path)

        # 4. Status events accumulator
        status_events: list[dict[str, str]] = []

        async def emit_status_event(event: dict[str, str]) -> None:
            status_events.append(event)
            if status_event_callback is not None:
                await status_event_callback(event)

        # 5. Guardrail state (same _build_guardrail_state as non-conv path)
        guardrail_state = self._build_guardrail_state(
            agent_context,
            {"input_data": {"__delegation_depth": 0}},
        )

        def build_conversation_guardrail_usage() -> dict[str, Any]:
            return {
                "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                "token_usage_current_session": guardrail_state.token_usage_current_session,
                "token_budget": guardrail_state.token_budget,
                "cumulative_iterations": guardrail_state.cumulative_iterations,
                "max_iterations": guardrail_state.max_iterations,
                "delegated_steps": guardrail_state.delegated_steps,
                "max_delegated_steps": guardrail_state.max_delegated_steps,
                "delegation_depth": guardrail_state.delegation_depth,
                "max_delegation_depth": guardrail_state.max_delegation_depth,
            }

        # 6. Build LangChain model
        model_id = agent_context.get("model_id")
        provider_type = model_config.get("provider_type")
        if not model_id:
            raise ValueError("Agent context missing model_id")
        if not provider_type:
            raise ValueError("Model config missing provider_type")

        from app.services.agents.langchain_model_factory import LangChainModelFactory
        try:
            _llm = LangChainModelFactory().get_model_from_config_dict(
                model_id=str(model_id),
                model_config_dict=model_config,
            )
        except Exception as _model_exc:
            raise ValueError(f"Failed to initialise model: {_model_exc}") from _model_exc

        # 7. Build LangChain callbacks (GuardrailCallback — same as non-conv path)
        from app.services.agents.guardrail_callback import GuardrailCallback
        lc_callbacks: list[Any] = [
            GuardrailCallback(
                guardrail_state=guardrail_state,
                session_id=str(conv_session_id),
                data_client=None,  # No agent_job for conversation turns; skip execution logging
                execution_mode="conversation",
            ),
        ]

        # 8. Build LangChain tools (same build_langchain_tools_for_ar_path as non-conv path)
        from app.services.agents.langchain_tool_wrapper import build_langchain_tools_for_ar_path
        lc_tools = build_langchain_tools_for_ar_path(
            tool_definitions=tool_definitions,
            comm_hub_client=comm_hub_client,
            data_client=None,  # No agent_job for conversation turns
            session_id=str(conv_session_id),
            agent_type_id=str(agent_type_id),
            conv_session_id=str(conv_session_id),
            tool_name_map=tool_name_map,
            role_id=str(role_id_raw) if role_id_raw else "",
            guardrail_state=guardrail_state,
            status_event_callback=emit_status_event,
        )

        # 9. Disable parallel tool calls when delegation tools present (same as non-conv path)
        _has_delegation_tools = any(t.name.startswith("agent____") for t in lc_tools)
        if _has_delegation_tools:
            try:
                _existing_mk = dict(getattr(_llm, "model_kwargs", None) or {})
                _existing_mk["parallel_tool_calls"] = False
                _llm = _llm.model_copy(update={"model_kwargs": _existing_mk})
            except Exception:
                pass

        # 10. Create agent (same create_agent as non-conv; no response_format for conv)
        from langchain.agents import create_agent
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.errors import GraphInterrupt

        _checkpointer = MemorySaver()
        _recursion_limit = max(1, guardrail_state.max_iterations) * 3 + 1
        _agent = create_agent(
            model=_llm,
            tools=lc_tools,
            system_prompt=system_instruction or None,
            response_format=None,  # Conversational: plain text response, no typed output
            checkpointer=_checkpointer,
        )
        _config: dict[str, Any] = {
            "configurable": {"thread_id": str(conv_session_id)},
            "callbacks": lc_callbacks,
            "recursion_limit": _recursion_limit,
        }

        # 11. Filter system messages — passed via system_prompt above
        input_messages = [m for m in messages if m.get("role") != "system"]

        # 12. Invoke agent
        try:
            _result = await _agent.ainvoke(
                {"messages": input_messages},
                config=_config,
            )
        except GraphInterrupt:
            # HITL not supported for conversational turns (user input comes via WebSocket)
            logger.warning("Conversation turn %s received unexpected GraphInterrupt", conv_session_id)
            return (
                "I need more information to continue. Please provide additional details.",
                build_conversation_guardrail_usage(),
                status_events,
            )
        except GuardrailStop as exc:
            logger.warning(
                "Conversation guardrail stop (LangGraph): session=%s reason=%s",
                conv_session_id, exc.reason,
            )
            return exc.message, build_conversation_guardrail_usage(), status_events

        # 13. LangGraph 1.1.10: detect interrupt from return value
        _pending_interrupts: list[Any] = (
            _result.get("__interrupt__", []) if isinstance(_result, dict) else []
        )
        if _pending_interrupts:
            logger.warning("Conversation turn %s interrupted (LangGraph return-based) — not supported", conv_session_id)
            return (
                "I need more information to continue. Please provide additional details.",
                build_conversation_guardrail_usage(),
                status_events,
            )

        # 14. Extract response text from last AI message
        _final_messages: list[Any] = _result.get("messages", []) if isinstance(_result, dict) else []
        response_text = ""
        for msg in reversed(_final_messages):
            _content: Any = getattr(msg, "content", "") or ""
            if _content and getattr(msg, "type", "") in ("ai", "assistant"):
                # Normalize content blocks ([{"type":"text","text":"..."}]) to plain string
                if isinstance(_content, list):
                    _text_parts = [
                        block.get("text", "")
                        for block in _content
                        if isinstance(block, dict) and block.get("type") == "text"
                    ]
                    response_text = "\n\n".join(part for part in _text_parts if part)
                else:
                    response_text = str(_content)
                break
        if not response_text:
            response_text = "I processed your message but received an empty response."

        return response_text, build_conversation_guardrail_usage(), status_events

    async def _save_result_for_conversation(
        self,
        tool_args: dict[str, Any],
        agent_type_id: uuid.UUID,
        conv_session_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Persist a save_result tool call for a conversation agent.

        Associates the ResultRecord with both the agent type and conversation session.
        """
        try:
            from app.db.models.results import ResultRecord

            record = ResultRecord(
                agent_type_id=agent_type_id,
                conversation_session_id=conv_session_id,
                payload=tool_args.get("data") or tool_args,
                content_type="application/json",
                title=tool_args.get("title", "Conversation result"),
                tags=["conversation"],
            )
            db.add(record)
            await db.flush()
            logger.info(
                "Saved result %s for conversation session %s", record.id, conv_session_id
            )
            return {"status": "saved", "result_id": str(record.id)}
        except Exception as exc:
            logger.warning(
                "save_result failed for conversation session %s: %s", conv_session_id, exc
            )
            return {"status": "error", "error": str(exc)}

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _execute_job(self, job: AgentJob, db: AsyncSession) -> dict[str, Any]:
        """Orchestrate execution using the appropriate LangChain agent loop."""
        from app.db.models.agents import AgentType, AgentIdentity, AgentRole

        agent_type = await db.get(AgentType, job.agent_type_id)
        if not agent_type:
            raise ValueError(f"AgentType {job.agent_type_id} not found")

        # Validate that the agent identity is explicitly assigned to the agent role
        # via the agent_role_identities join table (architectural correction)
        if agent_type.identity_id and agent_type.role_id:
            from app.db.models.agents import AgentRoleIdentity
            from sqlalchemy import select as _select
            result = await db.execute(
                _select(AgentRoleIdentity).where(
                    AgentRoleIdentity.role_id == agent_type.role_id,
                    AgentRoleIdentity.identity_id == agent_type.identity_id,
                )
            )
            if result.scalar_one_or_none() is None:
                raise PermissionDeniedError(
                    f"identity={agent_type.identity_id}",
                    agent_type.role_id,
                )

        # Resolve identity and role names for session_started traceability
        identity_name: str | None = None
        role_name: str | None = None
        if agent_type.identity_id:
            from app.db.models.agents import AgentIdentity as _AgentIdentity
            _identity = await db.get(_AgentIdentity, agent_type.identity_id)
            identity_name = _identity.name if _identity else None
        if agent_type.role_id:
            from app.db.models.agents import AgentRole as _AgentRole
            _role = await db.get(_AgentRole, agent_type.role_id)
            role_name = _role.name if _role else None

        await self._log_execution_event(
            session_id=job.id,
            event_type="session_started",
            message="Session execution started",
            data={
                "agent_type_id": str(job.agent_type_id),
                "agent_type_name": agent_type.name,
                "model_id": agent_type.model_id,
                "input_type": agent_type.input_type.value,
                "system_instruction_length": len(agent_type.system_instruction or ""),
                "identity_name": identity_name,
                "role_name": role_name,
            },
        )

        # Resolve permissions — scoped by AgentType bindings
        allowed_tools: set[str] = set()
        if agent_type.role_id:
            with tracer.start_as_current_span(
                "runtime_executor.resolve_permissions",
                attributes={"role_id": str(agent_type.role_id)},
            ):
                # Load AgentType bindings
                from sqlalchemy import select as _sel2
                from app.db.models.agents import AgentTypeSopBinding, AgentTypeSkillBinding  # noqa: F811

                _sop_rows = await db.execute(
                    _sel2(AgentTypeSopBinding.sop_id).where(
                        AgentTypeSopBinding.agent_type_id == agent_type.id
                    )
                )
                _bound_sop_set: set[uuid.UUID] = {row[0] for row in _sop_rows.fetchall()}

                _skill_rows = await db.execute(
                    _sel2(AgentTypeSkillBinding.skill_id).where(
                        AgentTypeSkillBinding.agent_type_id == agent_type.id
                    )
                )
                _bound_skill_set: set[uuid.UUID] = {row[0] for row in _skill_rows.fetchall()}

                _has_bindings = bool(_bound_sop_set or _bound_skill_set)
                _sop_overrides = _bound_sop_set if (_has_bindings and _bound_sop_set) else None
                _skill_overrides = _bound_skill_set if (_has_bindings and _bound_skill_set) else None

                allowed_tools = await self._permission_manager.calculate_allowed_tools(
                    agent_type.role_id, db,
                    override_sop_ids=_sop_overrides,
                    override_skill_ids=_skill_overrides,
                )
                delegated_agent_types = await self._permission_manager.calculate_allowed_agent_types(
                    agent_type.role_id,
                    db,
                    override_sop_ids=_sop_overrides if _has_bindings else None,
                )
                allowed_tools.update(
                    {build_tool_name("agent", slug) for slug in delegated_agent_types}
                )
        else:
            logger.warning(
                "AgentType %s has no role — no tools permitted beyond save_data",
                agent_type.id,
            )
            allowed_tools = {"save_data"}

        logger.info(
            "Session %s: %d tools permitted for role %s",
            job.id,
            len(allowed_tools),
            agent_type.role_id,
        )

        await self._log_execution_event(
            session_id=job.id,
            event_type="tools_resolved",
            message=f"Resolved {len(allowed_tools)} allowed tool(s)",
            data={
                "allowed_tools": _canonicalize_tool_list_for_log(allowed_tools),
                "role_name": role_name,
            },
        )

        # Load and log SOPs/Skills assigned to the role (GAP-1 fix)
        if agent_type.role_id:
            await self._log_sops_skills(job.id, agent_type.role_id, db)

        if agent_type.input_type == AgentInputType.conversation:
            return await self._run_conversational_loop(job, agent_type, allowed_tools, db)
        else:
            return await self._run_task_loop(job, agent_type, allowed_tools, db)

    async def _run_task_loop(
        self,
        job: AgentJob,
        agent_type: Any,
        allowed_tools: set[str],
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Execute a task agent via the LangChain observe-reason-act loop."""
        with tracer.start_as_current_span(
            "runtime_executor.task_loop",
            attributes={"session_id": str(job.id)},
        ):
            input_data = job.input_data or {}
            current_depth = 0
            if isinstance(input_data, dict):
                current_depth = _int_or_default(input_data.get("__delegation_depth"), 0)

            ctx = TaskAgentLoop(
                session_id=str(job.id),
                agent_type_id=str(job.agent_type_id),
                role_id=str(agent_type.role_id) if agent_type.role_id else None,
                allowed_tools=sorted(allowed_tools),
                system_instruction=agent_type.system_instruction,
                output_type=agent_type.output_type.value,
                output_schema=agent_type.output_schema,
                input_data=input_data,
                # Phase 1.1: Non-conversational agents are limited to 1 level of delegation
                max_delegation_depth=1,
                delegation_depth=0,
                tree_depth=max(0, current_depth),
            )

            # ── Load binding content (bound SOPs+skills) and append to system instruction ──
            binding_content = await self._load_binding_content(agent_type, db)
            if binding_content:
                base = ctx.system_instruction or ""
                ctx.system_instruction = f"{base}\n\n{binding_content}".strip()
                await self._log_execution_event(
                    session_id=job.id,
                    event_type="binding_content_loaded",
                    message="Binding content loaded into system instruction",
                    data={
                            "agent_type_id": str(agent_type.id),
                            "binding_content_preview": binding_content[:300],
                            "total_instruction_length": len(ctx.system_instruction),
                        },
                    )

            # ── Load MCP session context and append to system instruction ────
            if agent_type.role_id:
                mcp_context = await self._load_mcp_session_context(agent_type.role_id, db)
                if mcp_context:
                    base = ctx.system_instruction or ""
                    ctx.system_instruction = f"{base}\n\n{mcp_context}".strip()
                    await self._log_execution_event(
                        session_id=job.id,
                        event_type="mcp_context_loaded",
                        message=f"MCP session context loaded into system instruction",
                        data={
                            "role_id": str(agent_type.role_id),
                            "mcp_context_preview": mcp_context[:300],
                            "total_instruction_length": len(ctx.system_instruction),
                        },
                    )

            # ── Load and inject saved plan into system instruction ────────────
            updated_instruction, plan_injected = await self._runtime_loader.inject_plan_into_system_instruction(
                agent_type_id=agent_type.id,
                system_instruction=ctx.system_instruction,
                db=db,
            )
            if plan_injected:
                ctx.system_instruction = updated_instruction
                await self._log_execution_event(
                    session_id=job.id,
                    event_type="plan_injected",
                    message="Pre-approved plan injected into system instruction",
                    data={
                        "agent_type_id": str(agent_type.id),
                        "total_instruction_length": len(ctx.system_instruction or ""),
                    },
                )

            # ── Load tool definitions once for the whole session ──────────────
            ctx.tool_definitions, tool_name_map = await self._load_tool_definitions(allowed_tools, db)
            ctx._tool_name_map = tool_name_map  # type: ignore[attr-defined]  # Store for tool call restoration

            # Seed the message thread with the user prompt derived from input_data
            user_prompt = await self._format_user_prompt(job.input_data, agent_type, db)
            if user_prompt:
                ctx.append_user_message(user_prompt)

            # ── Capture prompt log before first LLM call ──────────────────────
            await self._capture_prompt_log(
                session_id=job.id,
                system_instruction=ctx.system_instruction,
                user_prompt=user_prompt,
                db=db,
            )

            # ── Observe-Reason-Act loop ────────────────────────────────────────
            from app.services.agents.guardrails import RuntimeGuardrailState
            from app.services.agents.guardrail_callback import GuardrailCallback
            from app.services.agents.execution_logging_callback import ExecutionLoggingCallback

            # ── Build LangChain model and tools for CC path (task 9.6) ──────────
            from app.services.agents.langchain_model_factory import LangChainModelFactory
            from app.services.agents.langchain_tool_wrapper import (
                _sanitize_tool_name, _schema_to_pydantic,
            )
            from langchain_core.tools import StructuredTool as _StructuredTool

            guardrail_state = RuntimeGuardrailState(
                max_iterations=10,
                max_delegation_depth=1,
                max_delegated_steps=20,
                execution_timeout_seconds=300,
                token_budget=None,
                token_enforcement_mode="observe",
                token_fallback_mode="observe_and_log",
                conversational_token_visibility_mode="enabled",
                conversational_continuation_policy="allow",
                policy_snapshot_id="unknown",
            )
            _iteration_ref = [0]
            _lc_callbacks: list[Any] = [
                ExecutionLoggingCallback(
                    session_id=str(job.id),
                    data_client=None,
                    iteration_ref=_iteration_ref,
                ),
            ]

            # Build tools from ctx.tool_definitions (CommHub routing)

            def _make_cc_tool(orig_name: str) -> tuple:
                async def _arun(**kwargs: Any) -> str:
                    try:
                        if _extract_agent_delegation_target(orig_name) is not None:
                            from app.agent_runtime.comm_hub_client import CommHubToolClient as _CH
                            _ch = _CH()
                            _target = _extract_agent_delegation_target(orig_name)
                            _a2a = await _ch.call_a2a_request(
                                target_agent_type_slug=_target,
                                session_id=ctx.session_id,
                                requester_role_id=ctx.role_id,
                                request_payload=kwargs,
                                wait_for_response=True,
                                wait_timeout_seconds=float(guardrail_state.execution_timeout_seconds),
                            )
                            return json.dumps(_a2a) if isinstance(_a2a, (dict, list)) else str(_a2a)

                        else:
                            # All tools (system or MCP) route through CommHub — no hardcoded name dispatch.
                            from app.agent_runtime.comm_hub_client import CommHubToolClient as _CH
                            _ch = _CH()
                            _result = await _ch.call_tool(
                                tool_name=orig_name,
                                tool_args=kwargs,
                                session_id=ctx.session_id,
                                agent_type_id=ctx.agent_type_id,
                            )
                            return json.dumps(_result) if isinstance(_result, (dict, list)) else str(_result)

                    except Exception as _exc:
                        logger.warning("CC tool %s failed: %s", orig_name, _exc)
                        return json.dumps({"error": str(_exc), "tool": orig_name})

                def _run(**kwargs: Any) -> str:
                    import asyncio as _aio
                    try:
                        return _aio.get_event_loop().run_until_complete(_arun(**kwargs))
                    except Exception as _exc:
                        return json.dumps({"error": str(_exc)})

                return _run, _arun

            _lc_tools: list[Any] = []
            for _td in (ctx.tool_definitions or []):
                _f = _td.get("function") or {}
                _on = _f.get("name", "")
                if not _on:
                    continue
                _sn = _sanitize_tool_name(_on)
                _sync, _async = _make_cc_tool(_on)
                _t = _StructuredTool.from_function(
                    func=_sync,
                    coroutine=_async,
                    name=_sn,
                    description=_f.get("description", "") or f"Call {_on}.",
                    args_schema=_schema_to_pydantic(
                        _sn, _f.get("parameters") or {"type": "object", "properties": {}}
                    ),
                )
                _t.metadata = {"original_name": _on}
                _lc_tools.append(_t)

            # Build model
            _cc_llm = None
            if _LANGCHAIN_AVAILABLE:
                try:
                    from app.db.models.agents import ModelConfig as _MCfg
                    from sqlalchemy import select as _selmc
                    from app.core.credential_vault import get_vault as _gv

                    _mc_rows = (await db.execute(_selmc(_MCfg))).scalars().all()
                    _mc = next(
                        (_r for _r in _mc_rows if agent_type.model_id in (_r.enabled_models or [])),
                        None,
                    )
                    _ak: str | None = None
                    if _mc and _mc.encrypted_api_key:
                        try:
                            _ak = json.loads(_gv().decrypt(_mc.encrypted_api_key)).get("api_key")
                        except Exception:
                            pass
                    _pk = (
                        _mc.provider_type.value
                        if _mc and hasattr(_mc.provider_type, "value")
                        else "openai"
                    )
                    _cc_llm = LangChainModelFactory().get_model(
                        provider_key=_pk,
                        model_id=agent_type.model_id,
                        api_key=_ak,
                        base_url=getattr(_mc, "api_base_url", None),
                    )
                except Exception as _mex:
                    logger.error("CC path: failed to build model: %s", _mex)

            # Build response_format (task 9.8)
            # Skip for Gemini/Cohere — ToolStrategy conflicts with tool use.
            _CC_PROVIDER_STRATEGY_KEYS: frozenset[str] = frozenset({
                "openai", "azure_openai", "litellm_proxy",
                "mistral", "groq", "together", "fireworks",
                "perplexity", "deepseek", "anthropic",
            })
            _cc_rf: Any = (
                agent_type.output_schema
                if (_pk in _CC_PROVIDER_STRATEGY_KEYS and agent_type.output_schema)
                else None
            )

            if _cc_llm is None:
                # Stub fallback
                output_data: dict[str, Any] = {
                    "result": "Task completed (stub — model unavailable)",
                    "stub": True,
                }
            else:
                from langchain.agents import create_agent
                from langgraph.checkpoint.memory import MemorySaver
                from langgraph.errors import GraphInterrupt

                _cc_checkpointer = MemorySaver()
                _cc_agent = create_agent(
                    model=_cc_llm,
                    tools=_lc_tools,
                    system_prompt=ctx.system_instruction or None,
                    response_format=_cc_rf,
                    checkpointer=_cc_checkpointer,
                )
                _cc_cfg: dict[str, Any] = {
                    "configurable": {"thread_id": str(job.id)},
                    "callbacks": _lc_callbacks,
                    "recursion_limit": 50,
                }

                try:
                    _cc_result = await _cc_agent.ainvoke(
                        {"messages": ctx.messages},
                        config=_cc_cfg,
                    )
                    _cc_sr = _cc_result.get("structured_response")
                    if _save_result_holder:
                        output_data = {**_save_result_holder}
                    elif _cc_sr is not None:
                        output_data = (
                            _cc_sr.model_dump()
                            if hasattr(_cc_sr, "model_dump")
                            else (_cc_sr if isinstance(_cc_sr, dict) else {"result": str(_cc_sr)})
                        )
                    else:
                        _cc_msgs = _cc_result.get("messages", [])
                        _cc_last = _cc_msgs[-1] if _cc_msgs else None
                        output_data = {
                            "result": (getattr(_cc_last, "content", "") or "") if _cc_last else ""
                        }
                except GraphInterrupt:
                    logger.warning("Unexpected HITL interrupt in CC task loop for session %s", job.id)
                    output_data = {"result": "Task paused — unexpected human intervention requested"}

            await self._log_execution_event(
                session_id=job.id,
                event_type="task_loop_completed",
                message="Task loop completed via create_agent",
                data={
                    "output_keys": list(output_data.keys()),
                    "guardrail": {
                        "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                        "current_value": {
                            "cumulative_iterations": guardrail_state.cumulative_iterations,
                            "delegated_steps": guardrail_state.delegated_steps,
                            "delegation_depth": guardrail_state.delegation_depth,
                            "elapsed_seconds": guardrail_state.elapsed_seconds(),
                            "token_usage_current_session": guardrail_state.token_usage_current_session,
                        },
                        "threshold_value": {
                            "max_iterations": guardrail_state.max_iterations,
                            "max_delegation_depth": guardrail_state.max_delegation_depth,
                            "max_delegated_steps": guardrail_state.max_delegated_steps,
                            "token_budget": guardrail_state.token_budget,
                            "execution_timeout_seconds": guardrail_state.execution_timeout_seconds,
                        },
                    },
                },
            )

            return output_data

    async def _run_conversational_loop(
        self,
        job: AgentJob,
        agent_type: Any,
        allowed_tools: set[str],
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Stub for conversational agents — full implementation driven via WebSocket."""
        with tracer.start_as_current_span(
            "runtime_executor.conversational_stub",
            attributes={"session_id": str(job.id)},
        ):
            ctx = ConversationalAgentLoop(
                session_id=str(job.id),
                agent_type_id=str(job.agent_type_id),
                role_id=str(agent_type.role_id) if agent_type.role_id else None,
                allowed_tools=sorted(allowed_tools),
                system_instruction=agent_type.system_instruction,
                output_type=agent_type.output_type.value,
                output_schema=agent_type.output_schema,
            )

            # ── Load binding content (bound SOPs+skills) and append to system instruction ──
            binding_content = await self._load_binding_content(agent_type, db)
            if binding_content:
                base = ctx.system_instruction or ""
                ctx.system_instruction = f"{base}\n\n{binding_content}".strip()

            # ── Load MCP session context and append to system instruction ────
            if agent_type.role_id:
                mcp_context = await self._load_mcp_session_context(agent_type.role_id, db)
                if mcp_context:
                    base = ctx.system_instruction or ""
                    ctx.system_instruction = f"{base}\n\n{mcp_context}".strip()

            # ── Load and inject saved plan into system instruction ────────────
            updated_instruction, plan_injected = await self._runtime_loader.inject_plan_into_system_instruction(
                agent_type_id=agent_type.id,
                system_instruction=ctx.system_instruction,
                db=db,
            )
            if plan_injected:
                ctx.system_instruction = updated_instruction
                logger.info(
                    "Injected plan into conversational agent system instruction (agent_type=%s)",
                    agent_type.id,
                )

            # Extract initial message from input_data if present
            initial_message: str | None = None
            if job.input_data and isinstance(job.input_data, dict):
                initial_message = str(job.input_data.get("message", ""))
            if initial_message:
                ctx.append_user_message(initial_message)

            # Capture prompt log before any LLM interaction
            await self._capture_prompt_log(
                session_id=job.id,
                system_instruction=agent_type.system_instruction,
                user_prompt=initial_message,
                db=db,
            )

            await self._log_execution_event(
                session_id=job.id,
                event_type="system",
                message="Conversational loop initialised — WebSocket-driven execution",
                data={
                    "langchain_available": _LANGCHAIN_AVAILABLE,
                    "allowed_tools": sorted(allowed_tools),
                },
            )

            return {
                "result": "Conversational session initialised",
                "session_id": str(job.id),
                "allowed_tool_count": len(allowed_tools),
            }

    # ── Observe-Reason-Act phases ──────────────────────────────────────────────

    async def _observe(self, ctx: TaskAgentLoop, db: AsyncSession) -> TaskAgentLoop:
        """Observe: snapshot current context for the upcoming reasoning step."""
        with tracer.start_as_current_span(
            "agent.observe",
            attributes={"session_id": ctx.session_id, "iteration": ctx.iteration},
        ):
            logger.debug(
                "Session %s observe phase (iteration %d): %d messages, %d tool results",
                ctx.session_id,
                ctx.iteration,
                len(ctx.messages),
                len(ctx.tool_results),
            )
            await self._log_execution_event(
                session_id=uuid.UUID(ctx.session_id),
                event_type="observe",
                message=f"Observe phase — iteration {ctx.iteration}",
                data={
                    "message_count": len(ctx.messages),
                    "tool_result_count": len(ctx.tool_results),
                    "is_complete": ctx.is_complete,
                },
            )
        return ctx

    async def _reason(
        self,
        ctx: TaskAgentLoop,
        agent_type: Any,
        db: AsyncSession,
        callbacks: list[Any] | None = None,
    ) -> TaskAgentLoop:
        """Reason: call the LLM to decide the next action.

        Builds the full message list (system instruction + conversation history),
        logs ``llm_request`` before the call, dispatches to ``ModelBindingLayer``,
        logs ``llm_response`` after, normalises tool calls and stores them for
        the act phase.  Falls back to a stub when the LLM is unavailable.
        """
        with tracer.start_as_current_span(
            "agent.reason",
            attributes={"session_id": ctx.session_id, "iteration": ctx.iteration},
        ):
            logger.debug(
                "Session %s reason phase (iteration %d)", ctx.session_id, ctx.iteration
            )

            # Build full message list: system instruction first, then conversation history
            full_messages: list[dict[str, Any]] = []
            if ctx.system_instruction:
                full_messages.append({"role": "system", "content": ctx.system_instruction})
            full_messages.extend(ctx.messages)

            tool_defs = ctx.tool_definitions or []
            tool_names = [t.get("function", {}).get("name", "") for t in tool_defs]

            # Log LLM request at INFO level (summary) and DEBUG level (full details)
            await self._log_execution_event(
                session_id=uuid.UUID(ctx.session_id),
                event_type="llm_request",
                message=f"LLM request — iteration {ctx.iteration + 1}",
                log_level="info",
                data={
                    "model_id": agent_type.model_id,
                    "message_count": len(full_messages),
                    "messages": full_messages,
                    "tool_count": len(tool_defs),
                    "available_tools": tool_names,
                },
            )
            
            # Full request details at DEBUG level
            await self._log_execution_event(
                session_id=uuid.UUID(ctx.session_id),
                event_type="llm_request_detail",
                message=f"LLM request full details — iteration {ctx.iteration + 1}",
                log_level="debug",
                data={
                    "messages": full_messages,
                    "tool_definitions": tool_defs,
                },
            )

            llm_success = False
            if _LANGCHAIN_AVAILABLE:
                try:
                    from app.services.agents.langchain_model_factory import LangChainModelFactory
                    from app.db.models.agents import ModelConfig as _ModelConfig
                    from sqlalchemy import select as _sel_mc
                    from app.core.credential_vault import get_vault as _get_vault

                    # Resolve model config from DB
                    _mc_result = await db.execute(_sel_mc(_ModelConfig))
                    _mc_configs = list(_mc_result.scalars().all())
                    model_config = None
                    for _mc in _mc_configs:
                        if agent_type.model_id in (_mc.enabled_models or []):
                            model_config = _mc
                            break
                    if model_config is None:
                        raise RuntimeError(
                            f"No ModelConfig found with model '{agent_type.model_id}' "
                            "in its enabled_models list"
                        )

                    # Resolve API key from encrypted credentials
                    _api_key: str | None = None
                    if model_config.encrypted_api_key:
                        try:
                            _vault = _get_vault()
                            _creds = json.loads(_vault.decrypt(model_config.encrypted_api_key))
                            _api_key = _creds.get("api_key")
                        except Exception as _key_exc:
                            logger.warning(
                                "Failed to decrypt model config credentials: %s", _key_exc
                            )

                    _provider_key = (
                        model_config.provider_type.value
                        if hasattr(model_config.provider_type, "value")
                        else str(model_config.provider_type)
                    )
                    _factory = LangChainModelFactory()
                    _llm = _factory.get_model(
                        provider_key=_provider_key,
                        model_id=agent_type.model_id,
                        api_key=_api_key,
                        base_url=model_config.api_base_url,
                    )
                    if tool_defs:
                        _llm = _llm.bind_tools(tool_defs)
                    _invoke_config = {"callbacks": callbacks} if callbacks else {}
                    raw_response = await _llm.ainvoke(
                        full_messages, config=_invoke_config or None
                    )
                    response_text, raw_tool_calls, _ = _extract_ai_message_response(raw_response)

                    # Normalise to internal format: [{id, name, args}]
                    # Restore original tool names from sanitized OpenAI names
                    tool_name_map = getattr(ctx, "_tool_name_map", {})
                    tool_calls: list[dict[str, Any]] = []
                    for tc in raw_tool_calls:
                        sanitized_name = tc.get("function", {}).get("name", "")
                        original_name = _restore_tool_name_from_openai(sanitized_name, tool_name_map)
                        args_raw = tc.get("function", {}).get("arguments", "{}")
                        args: dict[str, Any] = (
                            json.loads(args_raw)
                            if isinstance(args_raw, str)
                            else (args_raw if isinstance(args_raw, dict) else {})
                        )
                        tool_calls.append(
                            {"id": tc.get("id", ""), "name": original_name, "args": args}
                        )

                    # Append assistant message with tool_calls if present, otherwise just text
                    if tool_calls:
                        # OpenAI requires assistant message with tool_calls before tool messages
                        assistant_msg: dict[str, Any] = {"role": "assistant"}
                        if response_text:
                            assistant_msg["content"] = response_text
                        else:
                            assistant_msg["content"] = ""  # OpenAI requires content even if empty
                        assistant_msg["tool_calls"] = raw_tool_calls  # Include full tool_calls array
                        ctx.messages.append(assistant_msg)
                    elif response_text:
                        ctx.append_assistant_message(response_text)

                    # Log LLM response AFTER receiving it (summary at INFO, full at DEBUG)
                    await self._log_execution_event(
                        session_id=uuid.UUID(ctx.session_id),
                        event_type="llm_response",
                        message=f"LLM response — iteration {ctx.iteration + 1}",
                        log_level="info",
                        data={
                            "response_text": response_text[:500] if response_text else "",
                            "tool_calls": [
                                {"name": tc["name"], "args": tc["args"]}
                                for tc in tool_calls
                            ],
                            "has_tool_calls": bool(tool_calls),
                            "finish_reason": "tool_calls" if tool_calls else "stop",
                        },
                    )
                    
                    # Full response at DEBUG level
                    await self._log_execution_event(
                        session_id=uuid.UUID(ctx.session_id),
                        event_type="llm_response_detail",
                        message=f"LLM response full details — iteration {ctx.iteration + 1}",
                        log_level="debug",
                        data={
                            "raw_response": raw_response,
                            "response_text_full": response_text,
                        },
                    )

                    if tool_calls:
                        ctx._pending_tool_calls = tool_calls  # type: ignore[attr-defined]
                    else:
                        ctx.output_data = {
                            "result": response_text,
                            "model_id": agent_type.model_id,
                        }
                        ctx.is_complete = True

                    llm_success = True
                except Exception as exc:
                    error_msg = f"{type(exc).__name__}: {str(exc)}"
                    logger.error(
                        "LLM call failed for session %s (%s) — falling back to stub",
                        ctx.session_id,
                        error_msg,
                        exc_info=True,
                    )
                    # Store error details for diagnostic visibility
                    llm_error = error_msg

            if not llm_success:
                # Emit stub response event with error details
                stub_data: dict[str, Any] = {
                    "stub": True,
                    "langchain_available": _LANGCHAIN_AVAILABLE,
                }
                if "llm_error" in locals():
                    stub_data["error"] = llm_error
                
                await self._log_execution_event(
                    session_id=uuid.UUID(ctx.session_id),
                    event_type="llm_response",
                    message=f"LLM response (stub) — iteration {ctx.iteration + 1}",
                    log_level="warn",
                    data=stub_data,
                )
                
                # Whether LangChain failed or is unavailable, always use stub reasoning.
                # This ensures the full trace (including save_result) is emitted and
                # the session completes rather than hanging in an incomplete state.
                ctx = self._apply_stub_reasoning(ctx, agent_type)

        return ctx

    def _apply_stub_reasoning(self, ctx: TaskAgentLoop, agent_type: Any) -> TaskAgentLoop:
        """Synthetic LLM response used when the real LLM is unavailable.

        Simulates a ``save_result`` tool call so the full observe-reason-act cycle
        (including tool dispatch and result persistence) is exercised even in stub mode.
        Setting ``is_complete = True`` ensures the loop exits after ``_act()`` processes
        the pending tool call.
        """
        ctx.append_assistant_message(
            f"Task processed by stub executor (model_id={agent_type.model_id})"
        )
        ctx._pending_tool_calls = [  # type: ignore[attr-defined]
            {
                "id": "stub_save_result",
                "name": "save_result",
                "args": {
                    "title": f"Session {ctx.session_id} result",
                    "content": "Task completed (stub executor)",
                    "data": {
                        "session_id": ctx.session_id,
                        "allowed_tool_count": len(ctx.allowed_tools),
                        "input": ctx.input_data if hasattr(ctx, "input_data") else None,
                        "iterations": ctx.iteration + 1,
                    },
                },
            }
        ]
        ctx.is_complete = True
        return ctx

    async def _act(
        self,
        ctx: TaskAgentLoop,
        allowed_tools: set[str],
        db: AsyncSession,
        guardrail_state: RuntimeGuardrailState | None = None,
    ) -> TaskAgentLoop:
        """Act: dispatch pending tool calls with permission enforcement.

        Each tool call is logged before and after execution.  ``save_result`` is
        handled as a special pseudo-tool that persists to the Result Repository.
        All other calls are dispatched via ``McpProxyEngine``.
        An ``iteration_complete`` event is emitted after all tool calls finish.
        """
        ctx.iteration += 1

        pending: list[dict[str, Any]] = getattr(ctx, "_pending_tool_calls", [])  # type: ignore[attr-defined]
        if not pending:
            with tracer.start_as_current_span(
                "agent.act",
                attributes={
                    "session_id": ctx.session_id,
                    "iteration": ctx.iteration,
                    "tool_calls": 0,
                },
            ):
                logger.debug(
                    "Session %s act phase (iteration %d): no tool calls",
                    ctx.session_id,
                    ctx.iteration,
                )
                await self._log_execution_event(
                    session_id=uuid.UUID(ctx.session_id),
                    event_type="iteration_complete",
                    message=f"Iteration {ctx.iteration} complete — no tool calls",
                    data={
                        "iteration": ctx.iteration,
                        "tool_calls": 0,
                        "is_complete": ctx.is_complete,
                    },
                )
            return ctx

        with tracer.start_as_current_span(
            "agent.act",
            attributes={
                "session_id": ctx.session_id,
                "iteration": ctx.iteration,
                "tool_calls": len(pending),
            },
        ):
            role_id = uuid.UUID(ctx.role_id) if ctx.role_id else uuid.uuid4()
            executed = 0
            from app.agent_runtime.comm_hub_client import CommHubToolClient
            comm_hub_client = CommHubToolClient()

            # Load role's MCP session assignments for tool execution
            role_mcp_sessions = await self._load_role_mcp_session_map(role_id, db)

            for tool_call in pending:
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("args", {})
                call_id = tool_call.get("id", "")

                # Enforce permission boundary on every dispatch
                self._permission_manager.check_tool_allowed(tool_name, allowed_tools, role_id)

                await self._log_execution_event(
                    session_id=uuid.UUID(ctx.session_id),
                    event_type="tool_call",
                    message=f"Tool call: {tool_name}",
                    data={"tool": tool_name, "args": tool_args, "call_id": call_id},
                )

                if tool_name == "save_result":
                    result = await self._handle_save_result_tool_call(ctx, tool_args, db)
                elif tool_name == "send_notification":
                    from app.services.notifications.mcp_tool import handle_send_notification
                    result = await handle_send_notification(
                        args=tool_args,
                        db_session=db,
                        caller_identity={
                            "agent_id": ctx.agent_type_id,
                            "session_id": ctx.session_id,
                        },
                    )
                elif tool_name == "get_recipient_group":
                    from app.services.notifications.mcp_tool import handle_get_recipient_group
                    result = await handle_get_recipient_group(
                        args=tool_args,
                        db_session=db,
                        caller_identity={
                            "agent_id": ctx.agent_type_id,
                            "session_id": ctx.session_id,
                        },
                    )
                elif _extract_agent_delegation_target(tool_name) is not None:
                    if guardrail_state is None:
                        guardrail_state = RuntimeGuardrailState(
                            max_iterations=10,
                            max_delegation_depth=1,
                            max_delegated_steps=20,
                            execution_timeout_seconds=300,
                            token_budget=None,
                            token_enforcement_mode="observe",
                            token_fallback_mode="observe_and_log",
                            conversational_token_visibility_mode="enabled",
                            conversational_continuation_policy="allow",
                            policy_snapshot_id="unknown",
                        )
                    target_slug = _extract_agent_delegation_target(tool_name)
                    next_depth = ctx.tree_depth + 1

                    # Phase 1.1: Delegation depth guard for TaskAgentLoop path
                    if next_depth > ctx.max_delegation_depth:
                        await self._log_execution_event(
                            session_id=uuid.UUID(ctx.session_id),
                            event_type="delegation_depth_blocked",
                            message=(
                                f"Delegation depth limit reached: "
                                f"{ctx.tree_depth} >= {ctx.max_delegation_depth}"
                            ),
                            data={
                                "delegation_target": target_slug,
                                "current_depth": ctx.tree_depth,
                                "max_depth": ctx.max_delegation_depth,
                            },
                        )
                        result = {
                            "blocked": True,
                            "reason": (
                                f"Delegation depth limit reached "
                                f"({ctx.tree_depth} >= "
                                f"{ctx.max_delegation_depth}). "
                                f"Non-conversational agents are limited to "
                                f"1 level of delegation."
                            ),
                        }
                    else:
                        ctx.delegation_depth = next_depth

                        # Phase 1.2: Emit delegation_started before dispatch
                        await self._log_execution_event(
                            session_id=uuid.UUID(ctx.session_id),
                            event_type="delegation_started",
                            message=f"Delegating to agent '{target_slug}'",
                            data={
                                "delegation_target": target_slug,
                                "delegation_depth": next_depth,
                                "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                            },
                        )

                        # Dispatch A2A request without blocking so receiver_session_id
                        # is available immediately for streaming in the execution log.
                        _a2a_dispatch_result: dict[str, Any] | None = None
                        _a2a_dispatch_err: str | None = None
                        try:
                            _a2a_dispatch_result = await comm_hub_client.call_a2a_request(
                                target_agent_type_slug=target_slug or "",
                                session_id=ctx.session_id,
                                requester_role_id=ctx.role_id,
                                request_payload=_build_delegation_request_payload(tool_args),
                                session_link_id=tool_args.get("session_link_id"),
                                wait_for_response=False,
                            )
                        except Exception as _dispatch_exc:
                            _a2a_dispatch_err = str(_dispatch_exc)

                        # receiver_session_id is now known — log delegation_waiting with it
                        _rsid_early = (
                            _a2a_dispatch_result.get("receiver_session_id")
                            if isinstance(_a2a_dispatch_result, dict)
                            else None
                        )
                        await self._log_execution_event(
                            session_id=uuid.UUID(ctx.session_id),
                            event_type="delegation_waiting",
                            message=f"Waiting for delegated agent '{target_slug}'",
                            data={
                                "delegation_target": target_slug,
                                "delegation_depth": next_depth,
                                "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                                **({
                                    "receiver_session_id": _rsid_early
                                } if _rsid_early else {}),
                            },
                        )

                        if _a2a_dispatch_err or _a2a_dispatch_result is None:
                            err_msg = _a2a_dispatch_err or "A2A dispatch returned no result"
                            _is_timeout = "timeout" in err_msg.lower()
                            _dispatch_event_type = "delegation_timeout" if _is_timeout else "delegation_failed"
                            _dispatch_msg = (
                                f"Delegated agent '{target_slug}' timed out: {err_msg}"
                                if _is_timeout else
                                f"Delegated agent '{target_slug}' failed: {err_msg}"
                            )
                            await self._log_execution_event(
                                session_id=uuid.UUID(ctx.session_id),
                                event_type=_dispatch_event_type,
                                message=_dispatch_msg,
                                data={
                                    "delegation_target": target_slug,
                                    "error": err_msg,
                                    "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                                },
                            )
                            result = {"error": err_msg, "blocked": False}
                        else:
                            # Wait for the delegated agent to finish
                            try:
                                if _rsid_early:
                                    _wait_result = await comm_hub_client.wait_for_a2a_response(
                                        receiver_session_id=_rsid_early,
                                        timeout_seconds=45.0,
                                    )
                                    a2a_result: dict[str, Any] = {
                                        **_wait_result,
                                        "receiver_session_id": _rsid_early,
                                        "session_link_id": _a2a_dispatch_result.get("session_link_id"),
                                        "receiver_instance_id": _a2a_dispatch_result.get("receiver_instance_id"),
                                    }
                                else:
                                    a2a_result = {
                                        "status": "failed",
                                        "error": "No receiver session ID returned by dispatch",
                                    }
                            except Exception as a2a_exc:
                                err_msg = str(a2a_exc)
                                if "timeout" in err_msg.lower():
                                    await self._log_execution_event(
                                        session_id=uuid.UUID(ctx.session_id),
                                        event_type="delegation_timeout",
                                        message=f"Delegated agent '{target_slug}' timed out",
                                        data={
                                            "delegation_target": target_slug,
                                            "receiver_session_id": _rsid_early,
                                            "error": err_msg,
                                            "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                                        },
                                    )
                                else:
                                    await self._log_execution_event(
                                        session_id=uuid.UUID(ctx.session_id),
                                        event_type="delegation_failed",
                                        message=f"Delegated agent '{target_slug}' failed: {err_msg}",
                                        data={
                                            "delegation_target": target_slug,
                                            "receiver_session_id": _rsid_early,
                                            "error": err_msg,
                                            "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                                        },
                                    )
                                result = {"error": err_msg, "blocked": False}
                            else:
                                # Determine exit condition from wait result status
                                exit_condition = "completed"
                                if isinstance(a2a_result, dict):
                                    resp_status = a2a_result.get("status", "")
                                    if resp_status == "timeout":
                                        exit_condition = "timeout"
                                        await self._log_execution_event(
                                            session_id=uuid.UUID(ctx.session_id),
                                            event_type="delegation_timeout",
                                            message=f"Delegated agent '{target_slug}' timed out",
                                            data={
                                                "delegation_target": target_slug,
                                                "receiver_session_id": _rsid_early,
                                                "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                                            },
                                        )
                                    elif resp_status in ("failed", "expired"):
                                        exit_condition = "failed"
                                        await self._log_execution_event(
                                            session_id=uuid.UUID(ctx.session_id),
                                            event_type="delegation_failed",
                                            message=f"Delegated agent '{target_slug}' failed",
                                            data={
                                                "delegation_target": target_slug,
                                                "receiver_session_id": _rsid_early,
                                                "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                                            },
                                        )

                                rsid = a2a_result.get("receiver_session_id")
                                await self._log_execution_event(
                                    session_id=uuid.UUID(ctx.session_id),
                                    event_type="delegation_resumed",
                                    message=(
                                        f"Delegation from '{target_slug}' "
                                        f"resumed — exit condition: {exit_condition}"
                                    ),
                                    data={
                                        "delegation_target": target_slug,
                                        "exit_condition": exit_condition,
                                        "receiver_session_id": rsid,
                                        "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                                    },
                                )

                                result = a2a_result
                else:
                    result = await self._execute_mcp_tool(
                        tool_name, tool_args, db, role_mcp_sessions,
                        agent_type_id=ctx.agent_type_id,
                    )

                ctx.append_tool_result(call_id, tool_name, result)
                executed += 1

            if hasattr(ctx, "_pending_tool_calls"):
                ctx._pending_tool_calls = []  # type: ignore[attr-defined]

            await self._log_execution_event(
                session_id=uuid.UUID(ctx.session_id),
                event_type="iteration_complete",
                message=f"Iteration {ctx.iteration} complete — {executed} tool call(s) executed",
                data={
                    "iteration": ctx.iteration,
                    "tool_calls": executed,
                    "is_complete": ctx.is_complete,
                },
            )

        return ctx

    def _resolve_content_type(self, output_type: str | None) -> str:
        """Resolve MIME content type from agent output type configuration.

        Mirrors the logic in ``_content_type_from_output_type()`` from
        ``system_tools.py`` to ensure consistent content type derivation.
        """
        if not output_type:
            return "application/json"
        normalized = output_type.strip().lower()
        if normalized == "markdown":
            return "text/markdown"
        if normalized == "typed":
            return "application/json"
        # auto or unknown — default to JSON for ResultRecord compatibility
        return "application/json"

    async def _handle_save_result_tool_call(
        self,
        ctx: TaskAgentLoop,
        args: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Execute the ``save_result`` pseudo-tool: persist a ResultRecord.

        Updates ``ctx.output_data`` so the session result is available to callers.
        Emits a ``save_result`` execution log event for full traceability.
        """
        result_id: str | None = None
        try:
            from app.db.models.results import ResultRecord

            # Phase 1.4: Derive content_type from output_type instead of hardcoding
            content_type = self._resolve_content_type(ctx.output_type)

            record = ResultRecord(
                agent_type_id=uuid.UUID(ctx.agent_type_id),
                payload=args.get("data") or args,
                content_type=content_type,
                title=args.get("title", f"Session {ctx.session_id} result"),
                tags=["agent_session"],
            )
            db.add(record)
            await db.flush()
            result_id = str(record.id)
            logger.info("Persisted ResultRecord %s for session %s", result_id, ctx.session_id)
        except Exception as exc:
            logger.warning(
                "save_result tool call: failed to persist ResultRecord for session %s: %s",
                ctx.session_id,
                exc,
            )

        ctx.output_data = {
            "result": args.get("content", ""),
            "title": args.get("title", ""),
            "result_id": result_id,
        }

        await self._log_execution_event(
            session_id=uuid.UUID(ctx.session_id),
            event_type="save_result",
            message="save_result: ResultRecord persisted to Result Repository",
            data={
                "result_id": result_id,
                "title": args.get("title", ""),
                "output_keys": list(args.keys()),
            },
        )

        return {"status": "saved", "result_id": result_id}

    async def _load_role_mcp_session_map(
        self, role_id: uuid.UUID, db: AsyncSession
    ) -> dict[str, dict[str, str]]:
        """Load a map of server_id -> {session_id, auth_type} for the role.
        
        Includes passthrough sessions so tool dispatch does not fail for them.
        
        Returns:
            Dict mapping server UUID (as string) to a dict with 'session_id' and 'auth_type' keys.
        """
        from sqlalchemy import select
        from app.db.models.agents import AgentRoleMcpSession
        from app.db.models.mcp_hub import McpSession
        
        result = await db.execute(
            select(McpSession.id, McpSession.server_id, McpSession.auth_type)
            .join(AgentRoleMcpSession, AgentRoleMcpSession.mcp_session_id == McpSession.id)
            .where(AgentRoleMcpSession.role_id == role_id)
            .where(McpSession.is_active.is_(True))
        )
        
        return {
            str(row.server_id): {
                "session_id": str(row.id),
                "auth_type": row.auth_type.value,
            }
            for row in result.all()
        }

    async def _execute_mcp_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        db: AsyncSession,
        role_mcp_sessions: dict[str, dict[str, str]],
        agent_type_id: str | None = None,
    ) -> dict[str, Any]:
        """Dispatch a single MCP tool call via McpProxyEngine.

        .. deprecated::
            Use :meth:`_execute_mcp_tool_ar` instead, which routes tool calls through
            CommHubToolClient and Communication Hub, following the service decomposition
            architecture. This method retains direct McpProxyEngine and database access
            and is only kept for the legacy task loop path that has not yet been migrated.

        Looks up the McpTool record by namespaced name, loads its server
        relationship, and calls the proxy with the MCP session assigned to the
        role for that server. For passthrough sessions, retrieves the agent
        identity JWT and forwards it. Returns an error dict on any failure so
        the agent loop can continue rather than abort.
        """
        from sqlalchemy import select
        from app.db.models.mcp_hub import McpTool
        from app.services.mcp.proxy import McpProxyEngine, McpProxyError

        try:
            result = await db.execute(
                select(McpTool)
                .where(McpTool.name == tool_name)
                .where(McpTool.is_active.is_(True))
            )
            tool = result.scalar_one_or_none()
            if not tool:
                logger.warning("MCP tool '%s' not found or inactive", tool_name)
                return {"error": f"Tool '{tool_name}' not found or inactive"}

            await db.refresh(tool, ["server"])
            
            # Look up the MCP session for this tool's server from role assignments
            server_id_str = str(tool.server_id)
            session_info = role_mcp_sessions.get(server_id_str)
            
            if not session_info:
                logger.error(
                    "No MCP session assigned to role for server %s (tool: %s)",
                    server_id_str,
                    tool_name,
                )
                return {
                    "error": f"No MCP session configured for server {tool.server.name}. "
                    f"Please assign an MCP session to the role for this server."
                }

            mcp_session_id = session_info["session_id"]
            auth_type = session_info["auth_type"]

            # Resolve agent JWT for passthrough sessions
            agent_jwt: str | None = None
            if auth_type == "passthrough":
                agent_jwt = await self._get_agent_identity_jwt(agent_type_id, db)
                if not agent_jwt:
                    logger.error(
                        "Passthrough session for tool '%s' but no agent identity JWT available. "
                        "Check if agent identity refresh token is valid in Keycloak.",
                        tool_name,
                    )
                    return {
                        "error": f"Passthrough session requires an agent identity JWT "
                        f"but none is available for tool '{tool_name}'. "
                        f"The agent identity may need to be recreated if the refresh token is invalid."
                    }

            proxy = McpProxyEngine()
            tool_result = await proxy.call_tool(
                tool=tool,
                tool_input=tool_args,
                db=db,
                session_id=mcp_session_id,
                agent_jwt=agent_jwt,
            )
            return {"result": tool_result}
        except McpProxyError as exc:
            logger.error("MCP tool '%s' call failed: %s", tool_name, exc)
            return {"error": str(exc)}
        except Exception as exc:
            logger.error("MCP tool '%s' unexpected error: %s", tool_name, exc)
            return {"error": str(exc)}

    async def _get_agent_identity_jwt(
        self, agent_type_id: str | None, db: AsyncSession
    ) -> str | None:
        """Retrieve the decrypted access token for the agent identity bound to an AgentType.

        Automatically refreshes the token if it is expired or expiring within 5 minutes.
        Returns None if the identity has no token, refresh fails, or decryption fails.
        """
        if not agent_type_id:
            return None

        try:
            from app.db.models.agents import AgentType, AgentIdentity
            from app.core.credential_vault import get_vault
            from app.services.token_refresh import (
                check_token_expiration,
                refresh_oauth_token,
                TokenRefreshError,
            )

            agent_type = await db.get(AgentType, uuid.UUID(agent_type_id))
            if not agent_type or not agent_type.identity_id:
                logger.debug("AgentType %s has no identity_id", agent_type_id)
                return None

            identity = await db.get(AgentIdentity, agent_type.identity_id)
            if not identity:
                logger.debug("AgentIdentity %s not found", agent_type.identity_id)
                return None

            # Check if token needs refresh BEFORE decrypting
            if await check_token_expiration(identity.id, db):
                logger.info(
                    "Agent identity %s token expired or expiring soon, refreshing...",
                    identity.id,
                )
                try:
                    await refresh_oauth_token(identity.id, db)
                    await db.commit()
                    await db.refresh(identity)
                except TokenRefreshError as exc:
                    logger.error(
                        "Token refresh failed for agent identity %s: %s. "
                        "This usually indicates an invalid or expired refresh token in Keycloak. "
                        "Consider deleting and recreating the agent identity.",
                        identity.id,
                        exc,
                    )
                    return None

            if not identity.access_token:
                logger.debug("AgentIdentity %s has no access_token", identity.id)
                return None

            vault = get_vault()
            decrypted = vault.decrypt(identity.access_token)
            return decrypted
        except Exception as exc:
            logger.warning("Failed to retrieve agent identity JWT: %s", exc)
            return None

    async def _persist_result(
        self, job: AgentJob, output_data: dict[str, Any], db: AsyncSession
    ) -> None:
        """Persist output_data as a ResultRecord (Result Repository / save_result)."""
        with tracer.start_as_current_span(
            "runtime_executor.persist_result",
            attributes={"session_id": str(job.id)},
        ):
            result_id: str | None = None
            try:
                from app.db.models.results import ResultRecord
                record = ResultRecord(
                    agent_type_id=job.agent_type_id,
                    payload=output_data,
                    content_type="application/json",
                    title=f"Session {job.id} result",
                    tags=["agent_session"],
                )
                db.add(record)
                await db.flush()
                result_id = str(record.id)
                logger.info("Persisted ResultRecord for session %s", job.id)
            except Exception as exc:
                logger.warning(
                    "Failed to persist ResultRecord for session %s: %s — continuing",
                    job.id,
                    exc,
                )

            # GAP-2: log save_result so operators can trace result persistence
            await self._log_execution_event(
                session_id=job.id,
                event_type="save_result",
                message="save_result: ResultRecord persisted to Result Repository",
                data={
                    "result_id": result_id,
                    "output_keys": list(output_data.keys()) if output_data else [],
                    "title": f"Session {job.id} result",
                },
            )

    async def _format_user_prompt(
        self,
        input_data: dict[str, Any] | None,
        agent_type: Any,
        db: AsyncSession | None = None,
    ) -> str | None:
        """Derive a string user prompt from the structured input_data.

        For ``input_type=none``, the prompt is auto-generated from the agent type's
        first bound SOP: "Follow the SOP '<name>' to complete the task".

        Phase 1.4: Appends output type formatting instructions (markdown, typed with
        schema, or auto) based on the agent type's ``output_type`` configuration, so
        the agent respects its configured output type at runtime.
        """
        user_prompt: str | None = None

        if agent_type.input_type == AgentInputType.none:
            if db:
                from sqlalchemy import select
                from sqlalchemy.orm import selectinload
                from app.db.models.agents import AgentTypeSopBinding
                from app.db.models.skills import Sop

                try:
                    # Find first SOP binding
                    result = await db.execute(
                        select(AgentTypeSopBinding)
                        .where(AgentTypeSopBinding.agent_type_id == agent_type.id)
                        .options(selectinload(AgentTypeSopBinding.sop))
                        .order_by(AgentTypeSopBinding.order)
                        .limit(1)
                    )
                    first_binding = result.scalar_one_or_none()
                    if first_binding and first_binding.sop:
                        user_prompt = f"Follow the SOP '{first_binding.sop.name}' to complete the task"
                    else:
                        logger.warning(
                            "none-input agent_type %s has no SOP bindings set",
                            agent_type.id,
                        )
                except Exception as exc:
                    logger.warning(
                        "Failed to resolve SOP binding for none-input agent_type %s: %s",
                        agent_type.id,
                        exc,
                    )
        elif not input_data:
            pass  # user_prompt stays None
        elif isinstance(input_data, dict):
            # Conversational: use the initial message
            if "message" in input_data:
                user_prompt = str(input_data["message"])
            else:
                # Typed: serialise as compact JSON for the prompt
                user_prompt = json.dumps(input_data, ensure_ascii=False)
        else:
            user_prompt = str(input_data)

        # Phase 1.4: Append output type formatting instruction for non-conversational agents
        output_instruction: str | None = None
        if agent_type.input_type != AgentInputType.conversation:
            output_type = getattr(agent_type, "output_type", None)
            if output_type is not None:
                output_type_value = (
                    output_type.value if hasattr(output_type, "value") else str(output_type)
                )
                if output_type_value == "markdown":
                    output_instruction = (
                        "You must produce your final output in markdown format."
                    )
                elif output_type_value == "typed":
                    output_schema = getattr(agent_type, "output_schema", None)
                    if output_schema:
                        output_instruction = (
                            "The final output must be valid JSON conforming to this schema:\n"
                            f"```json\n{json.dumps(output_schema, indent=2)}\n```"
                        )
                # auto: no additional instruction

        if output_instruction:
            if user_prompt:
                return f"{user_prompt}\n\n{output_instruction}"
            return output_instruction

        return user_prompt


