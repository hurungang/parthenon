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
import uuid
from copy import deepcopy
from typing import Any, TYPE_CHECKING

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
    RuntimeGuardrailState,
    detect_cycle_path,
    extract_total_tokens_from_usage,
)
from app.services.agents.runtime_loader import AgentRuntimeLoader
from app.services.agents.session_service import AgentSessionService
from app.services.agents.tool_naming import build_tool_name, parse_tool_name, is_system_tool

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

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

    if tool_name in {"save_result", "send_notification", "get_recipient_group"}:
        return build_tool_name("system", tool_name)

    if tool_name.startswith("system/"):
        bare = tool_name[len("system/"):]
        return build_tool_name("system", bare)

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


def _build_dynamic_agent_tool_definition(
    target_agent_type_slug: str,
    target_description: str | None,
    target_input_type: str,
    target_input_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build dynamic delegation tool schema for ``agent____<slug>``."""
    canonical_name = build_tool_name("agent", target_agent_type_slug)
    sanitized_name = canonical_name.replace("____", "__")

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
            "name": sanitized_name,
            "description": " ".join(description_parts),
            "parameters": parameters,
        },
    }


# Save-result pseudo-tool definition injected into every agent's tool set
_SAVE_RESULT_TOOL_DEF: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "save_result",
        "description": (
            "Persist the final output to the Result Repository. "
            "Call this when the task is complete and you have a result to save."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title for the result"},
                "content": {"type": "string", "description": "Summary or text of the result"},
                "data": {
                    "type": "object",
                    "description": "Structured payload to persist",
                },
            },
            "required": ["content"],
        },
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

# get_recipient_group system tool definition
_GET_RECIPIENT_GROUP_TOOL_DEF: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_recipient_group",
        "description": (
            "Retrieve information about a recipient group, including which channels "
            "are configured and their recipient properties. Use this before sending "
            "notifications to verify the group exists and understand its delivery setup."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "group_slug": {
                    "type": "string",
                    "description": "Slug of the recipient group to retrieve.",
                },
            },
            "required": ["group_slug"],
        },
    },
}

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

        return RuntimeGuardrailState(
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
            delegation_depth=max(0, current_depth),
        )

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

        if state.delegation_depth > state.max_delegation_depth:
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

    async def _load_sop_content(
        self, primary_sop_id: uuid.UUID, db: AsyncSession
    ) -> str | None:
        """Load a SOP and its steps from the database and format as instruction text.

        Returns a human-readable block that is appended to the system instruction so
        the LLM knows exactly which steps to follow.  Returns None on any failure.
        """
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.db.models.skills import Sop

        try:
            result = await db.execute(
                select(Sop)
                .where(Sop.id == primary_sop_id)
                .options(selectinload(Sop.steps))
            )
            sop = result.scalar_one_or_none()
            if not sop:
                logger.warning("SOP %s not found in database", primary_sop_id)
                return None

            lines: list[str] = [f"Follow this SOP to complete the task: {sop.name}"]
            if sop.description:
                lines.append(f"\nDescription: {sop.description}")
            if sop.instructions:
                lines.append(f"\nInstructions: {sop.instructions}")

            steps = sorted(sop.steps, key=lambda s: s.order)
            if steps:
                lines.append("\nSteps:")
                for step in steps:
                    step_num = step.order + 1
                    step_text = f"{step_num}."
                    if step.name:
                        step_text += f" {step.name}"
                    if step.description:
                        step_text += f": {step.description}"
                    lines.append(step_text)

            return "\n".join(lines)
        except Exception as exc:
            logger.warning("Failed to load SOP content for %s: %s", primary_sop_id, exc)
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
            "save_result": _SAVE_RESULT_TOOL_DEF,
            "send_notification": _SEND_NOTIFICATION_TOOL_DEF,
            "get_recipient_group": _GET_RECIPIENT_GROUP_TOOL_DEF,
        }

        explicit_system_tools: set[str] = set()
        for t in allowed_tools:
            if is_system_tool(t):
                try:
                    _, bare_tool = parse_tool_name(t)
                    explicit_system_tools.add(bare_tool)
                except ValueError:
                    if t.startswith("system/"):
                        explicit_system_tools.add(t[len("system/"):])
                    elif t.startswith("system__"):
                        explicit_system_tools.add(t[len("system__"):])
                    elif t.startswith("system_"):
                        explicit_system_tools.add(t[len("system_"):])
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

    async def run(self, session_id: uuid.UUID, data_client: "ControlCenterDataClient") -> None:
        """Entry point called by the /execute trigger endpoint. Executes the session end-to-end.

        The session is already in ``running`` state when this is called — the
        /execute endpoint transitions it before launching this coroutine.
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
                output_data = await self._run_task_loop_ar(job_data, context, data_client)
                await data_client.mark_session_completed(session_id, output_data)
                span.set_attribute("status", "completed")

                await data_client.log_execution_event(
                    session_id=session_id,
                    event_type="session_completed",
                    message="Session completed successfully",
                    data={"output_keys": list(output_data.keys()) if output_data else []},
                )
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
                error_msg = str(exc)
                logger.exception("Session %s execution error: %s", session_id, exc)
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
                span.set_attribute("status", "failed")
                span.set_attribute("error", error_msg)

    async def _run_task_loop_ar(
        self,
        job_data: dict[str, Any],
        context: dict[str, Any],
        data_client: "ControlCenterDataClient",
    ) -> dict[str, Any]:
        """Execute a task agent using pre-fetched context from Control Center.

        No database access — all data comes from ``context`` (the CC agent context API
        response) and all logging flows through ``data_client``.
        """
        from app.services.agents.agent_loop import TaskAgentLoop, ConversationalAgentLoop
        from app.services.agents.model_binding import ModelBindingLayer, ModelBindingError

        session_id = uuid.UUID(job_data["id"])
        agent_type_id = job_data["agent_type_id"]
        input_data = job_data.get("input_data") or {}

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
                "role_id": context.get("role_id"),
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

        # ── Build system instruction with SOP + MCP context ───────────────────
        system_instruction: str | None = context.get("system_instruction")
        sop_content: str | None = context.get("sop_content")
        if sop_content:
            base = system_instruction or ""
            system_instruction = f"{base}\n\n{sop_content}".strip()
            await data_client.log_execution_event(
                session_id=session_id,
                event_type="sop_loaded",
                message="SOP content loaded into system instruction",
                data={
                    "primary_sop_id": context.get("primary_sop_id"),
                    "sop_content_preview": sop_content[:300],
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
        tool_definitions: list[dict[str, Any]] = context.get("tool_definitions") or [
            _SAVE_RESULT_TOOL_DEF,
            _SEND_NOTIFICATION_TOOL_DEF,
            _GET_RECIPIENT_GROUP_TOOL_DEF,
        ]
        tool_name_map: dict[str, str] = context.get("tool_name_map") or {}
        role_mcp_sessions: dict[str, dict[str, str]] = context.get("role_mcp_sessions") or {}
        allowed_agent_types: set[str] = set(context.get("allowed_agent_types") or [])

        # ── Initialize Communication Hub tool client ──────────────────────────
        from app.agent_runtime.comm_hub_client import CommHubToolClient

        comm_hub_client = CommHubToolClient()
        
        # Configure mTLS certificate for authentication with Communication Hub
        # Get certificate paths from the CertificateManager via data_client
        cert_manager = getattr(data_client, "_cert_manager", None)
        logger.info(
            "Session %s: Configuring CommHubToolClient - cert_manager=%s",
            session_id,
            "available" if cert_manager else "None",
        )
        
        if cert_manager:
            cert_path = cert_manager.cert_path
            key_path = cert_manager.key_path
            logger.info(
                "Session %s: Certificate paths - cert_path=%s, key_path=%s",
                session_id,
                cert_path,
                key_path,
            )
            
            if cert_path and key_path:
                cert_path_str = str(cert_path)
                key_path_str = str(key_path)
                comm_hub_client.set_certificate(cert_path_str, key_path_str)
                logger.info(
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
            event_type="runtime_context_loaded",
            message="Runtime context prepared for task execution",
            data={
                "tools": tool_def_names,
                "tool_count": len(tool_def_names),
                "allowed_tools": allowed_tool_names,
                "tool_definitions": sorted(tool_def_names),
                "tool_routes": route_summary,
                "has_send_notification_tool": build_tool_name("system", "send_notification") in tool_def_names,
                "system_instruction": system_instruction,
                "system_instruction_length": len(system_instruction or ""),
                "user_prompt": user_prompt,
                "user_prompt_length": len(user_prompt or ""),
            },
            data_client=data_client,
        )

        # ── Capture prompt log ────────────────────────────────────────────────
        await data_client.log_prompt(
            session_id=session_id,
            system_instruction=system_instruction,
            user_prompt=user_prompt,
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

        # ── Observe-Reason-Act loop ───────────────────────────────────────────
        messages: list[dict[str, Any]] = []
        if user_prompt:
            messages.append({"role": "user", "content": user_prompt})

        output_data: dict[str, Any] = {}
        max_iterations = max(1, guardrail_state.max_iterations)

        for iteration in range(max_iterations):
            guardrail_state.cumulative_iterations += 1
            self._check_runtime_limits_or_raise(guardrail_state)

            await data_client.log_execution_event(
                session_id=session_id,
                event_type="guardrail.runtime.snapshot",
                message=f"Guardrail snapshot before iteration {iteration + 1}",
                data={
                    "guardrail_reason": "runtime_snapshot",
                    "execution_mode": execution_mode,
                    "current_value": {
                        "cumulative_iterations": guardrail_state.cumulative_iterations,
                        "delegation_depth": guardrail_state.delegation_depth,
                        "delegated_steps": guardrail_state.delegated_steps,
                        "elapsed_seconds": guardrail_state.elapsed_seconds(),
                        "token_usage_current_session": guardrail_state.token_usage_current_session,
                    },
                    "threshold_value": {
                        "max_iterations": guardrail_state.max_iterations,
                        "max_delegation_depth": guardrail_state.max_delegation_depth,
                        "max_delegated_steps": guardrail_state.max_delegated_steps,
                        "execution_timeout_seconds": guardrail_state.execution_timeout_seconds,
                        "token_budget": guardrail_state.token_budget,
                    },
                    "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                },
            )

            # ── Observe ───────────────────────────────────────────────────────
            await self._log_execution_event(
                session_id=session_id,
                event_type="observe",
                message=f"Observe phase — iteration {iteration}",
                data={
                    "message_count": len(messages),
                    "is_complete": False,
                },
                data_client=data_client,
            )

            # ── Reason ────────────────────────────────────────────────────────
            full_messages: list[dict[str, Any]] = []
            if system_instruction:
                full_messages.append({"role": "system", "content": system_instruction})
            full_messages.extend(messages)

            await self._log_execution_event(
                session_id=session_id,
                event_type="llm_request",
                message=f"LLM request — iteration {iteration + 1}",
                data={
                    "model_id": model_id,
                    "message_count": len(full_messages),
                    "tool_count": len(tool_definitions),
                },
                data_client=data_client,
            )

            raw_response: dict[str, Any] = {}
            llm_success = False
            if _LANGCHAIN_AVAILABLE and model_config_dict:
                try:
                    binding = ModelBindingLayer()
                    raw_response = await binding.complete_from_context(
                        model_id=model_id,
                        model_config_dict=model_config_dict,
                        messages=full_messages,
                        tools=tool_definitions if tool_definitions else None,
                    )
                    llm_success = True
                except Exception as exc:
                    logger.error(
                        "LLM call failed for session %s: %s — using stub", session_id, exc
                    )

            if not llm_success:
                # Stub response: emit save_result and complete
                await self._log_execution_event(
                    session_id=session_id,
                    event_type="llm_response",
                    message=f"LLM response (stub) — iteration {iteration + 1}",
                    log_level="WARN",
                    data={"stub": True, "langchain_available": _LANGCHAIN_AVAILABLE},
                    data_client=data_client,
                )
                output_data = {
                    "result": "Task completed (stub executor)",
                    "session_id": str(session_id),
                    "iterations": iteration + 1,
                }
                break

            # Extract text and tool calls from LLM response
            provider = (model_config_dict.get("provider_type") or "openai")
            from app.services.agents.model_binding import ModelBindingLayer as _MBL
            response_text = _MBL.extract_text(raw_response, provider)
            raw_tool_calls = _MBL.extract_tool_calls(raw_response, provider)
            usage = _MBL.extract_usage(raw_response, provider)
            iteration_tokens = extract_total_tokens_from_usage(usage)
            if iteration_tokens > 0:
                guardrail_state.token_usage_current_session += iteration_tokens

            token_budget = guardrail_state.token_budget
            token_threshold_hit = (
                token_budget is not None
                and token_budget > 0
                and guardrail_state.token_usage_current_session >= token_budget
            )

            if token_threshold_hit:
                guardrail_state.token_threshold_reached = True
                provider_supported = usage is not None

                if (
                    guardrail_state.token_enforcement_mode == "enforce"
                    and provider_supported
                ):
                    raise GuardrailStop(
                        reason=GuardrailStopReason.TOKEN_BUDGET_EXCEEDED_NON_CONVERSATIONAL,
                        message="Token budget exceeded for non-conversational execution",
                        details={
                            "current_value": guardrail_state.token_usage_current_session,
                            "threshold_value": token_budget,
                            "execution_mode": execution_mode,
                            "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                            "provider": provider,
                        },
                    )

                if guardrail_state.token_enforcement_mode == "enforce" and not provider_supported:
                    await data_client.log_execution_event(
                        session_id=session_id,
                        event_type="guardrail.runtime.token_fallback_applied",
                        message="Token fallback mode applied due to unsupported provider usage accounting",
                        data={
                            "guardrail_reason": GuardrailStopReason.TOKEN_GUARDRAIL_FALLBACK_APPLIED,
                            "execution_mode": execution_mode,
                            "provider": provider,
                            "fallback_mode": guardrail_state.token_fallback_mode,
                            "current_value": guardrail_state.token_usage_current_session,
                            "threshold_value": token_budget,
                            "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                        },
                    )

            await self._log_execution_event(
                session_id=session_id,
                event_type="llm_response",
                message=f"LLM response — iteration {iteration + 1}",
                data={
                    "response_text": (response_text or "")[:500],
                    "has_tool_calls": bool(raw_tool_calls),
                    "token_usage": usage,
                    "token_usage_current_session": guardrail_state.token_usage_current_session,
                    "selected_tools": [
                        _canonicalize_tool_name_for_log(
                            _restore_tool_name_from_openai(
                                tc.get("function", {}).get("name", ""),
                                tool_name_map,
                            ),
                            tool_name_map,
                        )
                        for tc in (raw_tool_calls or [])
                    ],
                    "finish_reason": "tool_calls" if raw_tool_calls else "stop",
                },
                data_client=data_client,
            )

            if not raw_tool_calls:
                # Final answer — no more tool calls
                output_data = {"result": response_text or "", "model_id": model_id}
                break

            # Append assistant message with tool calls
            messages.append({
                "role": "assistant",
                "content": response_text or "",
                "tool_calls": raw_tool_calls,
            })

            # ── Act ───────────────────────────────────────────────────────────
            role_id_str = context.get("role_id") or ""
            role_id = uuid.UUID(role_id_str) if role_id_str else uuid.uuid4()

            save_requested = False
            save_output_data: dict[str, Any] | None = None

            for tc in raw_tool_calls:
                sanitized_name = tc.get("function", {}).get("name", "")
                original_name = _restore_tool_name_from_openai(sanitized_name, tool_name_map)
                canonical_name = _canonicalize_tool_name_for_log(original_name, tool_name_map)
                args_raw = tc.get("function", {}).get("arguments", "{}")
                args: dict[str, Any] = (
                    json.loads(args_raw)
                    if isinstance(args_raw, str)
                    else (args_raw if isinstance(args_raw, dict) else {})
                )
                call_id = tc.get("id", "")

                try:
                    self._permission_manager.check_tool_allowed(
                        original_name, allowed_tools, role_id
                    )
                except PermissionDeniedError as exc:
                    tool_result: Any = {"error": f"Permission denied: {exc}"}
                    messages.append({
                        "role": "tool",
                        "content": str(tool_result),
                        "tool_call_id": call_id,
                    })
                    continue

                await self._log_execution_event(
                    session_id=session_id,
                    event_type="tool_call",
                    message=f"Tool call: {canonical_name}",
                    data={"tool": canonical_name, "args": args, "call_id": call_id},
                    data_client=data_client,
                )

                if original_name == "save_result":
                    # AR path: result is shipped to CC via data_client
                    output_data = {
                        "result": args.get("content", ""),
                        "title": args.get("title", ""),
                    }
                    await data_client.submit_result(session_id, output_data)
                    tool_result = {"status": "saved"}
                    save_requested = True
                    save_output_data = output_data

                    await self._log_execution_event(
                        session_id=session_id,
                        event_type="save_result",
                        message="save_result: result submitted to Control Center",
                        data={"title": args.get("title", ""), "output_keys": list(args.keys())},
                        data_client=data_client,
                    )
                    messages.append({
                        "role": "tool",
                        "content": str(tool_result),
                        "tool_call_id": call_id,
                    })
                elif original_name in ("send_notification", "get_recipient_group"):
                    # System tools now route through Communication Hub
                    tool_result = await self._execute_mcp_tool_ar(
                        tool_name=original_name,
                        tool_args=args,
                        role_mcp_sessions=role_mcp_sessions,
                        agent_type_id=agent_type_id,
                        session_id=str(session_id),
                        comm_hub_client=comm_hub_client,
                    )
                else:
                    delegated_target_slug = _extract_agent_delegation_target(original_name)
                    if delegated_target_slug is not None:
                        guardrail_state.delegated_steps += 1
                        next_depth = guardrail_state.delegation_depth + 1
                        if next_depth > guardrail_state.max_delegation_depth:
                            raise GuardrailStop(
                                reason=GuardrailStopReason.DELEGATION_DEPTH_EXCEEDED,
                                message="Delegation depth limit exceeded before dispatch",
                                details={
                                    "current_value": next_depth,
                                    "threshold_value": guardrail_state.max_delegation_depth,
                                    "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                                },
                            )
                        if guardrail_state.delegated_steps > guardrail_state.max_delegated_steps:
                            raise GuardrailStop(
                                reason=GuardrailStopReason.DELEGATED_STEPS_EXCEEDED,
                                message="Delegated-step limit exceeded before dispatch",
                                details={
                                    "current_value": guardrail_state.delegated_steps,
                                    "threshold_value": guardrail_state.max_delegated_steps,
                                    "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                                },
                            )

                        if (
                            allowed_agent_types
                            and delegated_target_slug not in allowed_agent_types
                        ):
                            tool_result = {
                                "error": (
                                    f"Delegation target '{delegated_target_slug}' is not allowed for this requester. "
                                    f"Allowed targets: {sorted(allowed_agent_types)}"
                                )
                            }
                        else:
                            delegation_payload = _build_delegation_request_payload(args)
                            delegation_payload["__delegation_depth"] = next_depth
                            tool_result = await comm_hub_client.call_a2a_request(
                                target_agent_type_slug=delegated_target_slug,
                                session_id=str(session_id),
                                requester_role_id=context.get("role_id"),
                                request_payload=delegation_payload,
                                session_link_id=args.get("session_link_id"),
                            )
                    else:
                        # MCP tool via Communication Hub
                        tool_result = await self._execute_mcp_tool_ar(
                            tool_name=original_name,
                            tool_args=args,
                            role_mcp_sessions=role_mcp_sessions,
                            agent_type_id=agent_type_id,
                            session_id=str(session_id),
                            comm_hub_client=comm_hub_client,
                        )

                messages.append({
                    "role": "tool",
                    "content": str(tool_result),
                    "tool_call_id": call_id,
                })

            # save_result signals task completion, but only after all tool calls
            # from the same model turn have been executed.
            if save_requested:
                await self._log_execution_event(
                    session_id=session_id,
                    event_type="task_loop_completed",
                    message="Task loop completed",
                    data={"iterations": iteration + 1},
                    data_client=data_client,
                )
                return save_output_data or output_data

            await self._log_execution_event(
                session_id=session_id,
                event_type="iteration_complete",
                message=f"Iteration {iteration + 1} complete",
                data={"iteration": iteration + 1, "tool_calls": len(raw_tool_calls)},
                data_client=data_client,
            )
        else:
            # Max iterations exceeded
            logger.warning("Session %s exceeded max iterations", session_id)
            raise GuardrailStop(
                reason=GuardrailStopReason.ITERATION_LIMIT_EXCEEDED,
                message="Task did not complete within max iterations",
                details={
                    "current_value": guardrail_state.cumulative_iterations,
                    "threshold_value": guardrail_state.max_iterations,
                    "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                },
            )

        await self._log_execution_event(
            session_id=session_id,
            event_type="task_loop_completed",
            message="Task loop completed",
            data={
                "output_keys": list(output_data.keys()),
                "guardrail": {
                    "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                    "cumulative_iterations": guardrail_state.cumulative_iterations,
                    "delegated_steps": guardrail_state.delegated_steps,
                    "delegation_depth": guardrail_state.delegation_depth,
                    "elapsed_seconds": guardrail_state.elapsed_seconds(),
                    "token_usage_current_session": guardrail_state.token_usage_current_session,
                },
            },
            data_client=data_client,
        )
        output_data.setdefault("guardrail_usage", {
            "policy_snapshot_id": guardrail_state.policy_snapshot_id,
            "cumulative_iterations": guardrail_state.cumulative_iterations,
            "delegated_steps": guardrail_state.delegated_steps,
            "delegation_depth": guardrail_state.delegation_depth,
            "elapsed_seconds": guardrail_state.elapsed_seconds(),
            "token_usage_current_session": guardrail_state.token_usage_current_session,
        })
        return output_data

    async def _execute_mcp_tool_ar(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        role_mcp_sessions: dict[str, dict[str, str]],
        agent_type_id: str | None,
        session_id: str,
        comm_hub_client: "CommHubToolClient",
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

        Returns:
            Tool execution result
        """
        from app.agent_runtime.comm_hub_client import CommHubToolClientError

        try:
            result = await comm_hub_client.call_tool(
                tool_name=tool_name,
                tool_args=tool_args,
                session_id=session_id,
                agent_type_id=agent_type_id or "",
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
        from app.services.agents.model_binding import ModelBindingLayer

        binding = ModelBindingLayer()
        model_config = await binding.resolve_model_config(agent_type.model_id, db)

        # Resolve allowed tools for the agent's role, including delegated agent tools.
        allowed_tools: set[str] = set()
        if agent_type.role_id:
            allowed_tools = await self._permission_manager.calculate_allowed_tools(
                agent_type.role_id, db
            )
            delegated_agent_types = await self._permission_manager.calculate_allowed_agent_types(
                agent_type.role_id,
                db,
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
                agent_type=agent_type,
                model_config=model_config,
                messages=local_messages,
                tools=tool_definitions if tool_definitions else None,
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
    ) -> tuple[str, dict[str, Any]]:
        """Execute one conversation turn using Control Center context only.

        This is the Agent Runtime DB-free path: all execution context and model
        credentials are fetched from Control Center internal data APIs.
        """
        from app.services.agents.model_binding import ModelBindingLayer

        binding = ModelBindingLayer()

        model_id = agent_context.get("model_id")
        if not model_id:
            raise ValueError("Agent context missing model_id")

        provider_type = model_config.get("provider_type")
        if not provider_type:
            raise ValueError("Model config missing provider_type")

        allowed_tools = self._permission_manager.get_allowed_tools_from_context(
            agent_context.get("allowed_tools", [])
        )
        tool_definitions = list(agent_context.get("tool_definitions", []))
        tool_name_map: dict[str, str] = dict(agent_context.get("tool_name_map", {}))
        role_mcp_sessions: dict[str, dict[str, str]] = dict(
            agent_context.get("role_mcp_sessions", {})
        )
        role_id_raw = agent_context.get("role_id")
        role_id = uuid.UUID(str(role_id_raw)) if role_id_raw else uuid.UUID(int=0)

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

        from app.agent_runtime.comm_hub_client import CommHubToolClient

        comm_hub_client = CommHubToolClient()
        if cert_path and key_path:
            comm_hub_client.set_certificate(cert_path, key_path)

        conv_tool_names = _canonicalize_tool_list_for_log(
            _tool_names_from_definitions(tool_definitions),
            tool_name_map,
        )
        allowed_tool_names = _canonicalize_tool_list_for_log(allowed_tools)
        logger.info(
            "Conversation runtime initialized (from context): session=%s agent=%s role=%s",
            conv_session_id,
            agent_type_id,
            role_id_raw,
            extra={
                "data": {
                    "tools": conv_tool_names,
                    "tool_count": len(conv_tool_names),
                    "allowed_tools": allowed_tool_names,
                    "tool_definitions": sorted(conv_tool_names),
                    "tool_routes": {
                        "system": sorted([t for t in conv_tool_names if _tool_route_type(t) == "system"]),
                        "agent": sorted([t for t in conv_tool_names if _tool_route_type(t) == "agent"]),
                        "mcp": sorted([t for t in conv_tool_names if _tool_route_type(t) == "mcp"]),
                    },
                    "sops": agent_context.get("sops", []),
                    "skills": agent_context.get("skills", []),
                    "system_instruction": system_instruction,
                    "system_instruction_length": len(system_instruction or ""),
                    "user_prompt": last_user_prompt,
                    "user_prompt_length": len(last_user_prompt or ""),
                    "message_count": len(messages),
                    "user_message_count": user_message_count,
                    "assistant_message_count": assistant_message_count,
                    "has_send_notification_tool": build_tool_name("system", "send_notification") in conv_tool_names,
                }
            },
        )

        local_messages = list(messages)
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

        max_iterations = max(1, guardrail_state.max_iterations)

        for iteration in range(max_iterations):
            guardrail_state.cumulative_iterations += 1
            try:
                self._check_runtime_limits_or_raise(guardrail_state)
            except GuardrailStop as exc:
                logger.warning(
                    "Conversation guardrail stop (from context): session=%s reason=%s",
                    conv_session_id,
                    exc.reason,
                )
                return exc.message, build_conversation_guardrail_usage()

            raw_response = await binding.complete_from_context(
                model_id=str(model_id),
                model_config_dict=model_config,
                messages=local_messages,
                tools=tool_definitions if tool_definitions else None,
            )

            response_text = ModelBindingLayer.extract_text(raw_response, provider_type)
            raw_tool_calls = ModelBindingLayer.extract_tool_calls(raw_response, provider_type)
            usage = ModelBindingLayer.extract_usage(raw_response, provider_type)
            guardrail_state.token_usage_current_session += extract_total_tokens_from_usage(usage)

            token_budget = guardrail_state.token_budget
            token_threshold_hit = (
                token_budget is not None
                and token_budget > 0
                and guardrail_state.token_usage_current_session >= token_budget
            )
            if (
                token_threshold_hit
                and guardrail_state.conversational_token_visibility_mode == "enabled"
            ):
                logger.info(
                    "guardrail.runtime.conversational_token_usage_snapshot",
                    extra={
                        "data": {
                            "guardrail_reason": GuardrailInfoReason.CONVERSATIONAL_TOKEN_THRESHOLD_OBSERVED,
                            "execution_mode": "conversational",
                            "token_usage_current_session": guardrail_state.token_usage_current_session,
                            "threshold_value": token_budget,
                            "continuation_allowed": True,
                            "policy_snapshot_id": guardrail_state.policy_snapshot_id,
                            "provider": provider_type,
                        }
                    },
                )

            logger.info(
                "Conversation LLM response (from context): session=%s iteration=%d has_tool_calls=%s selected_tools=%s",
                conv_session_id,
                iteration + 1,
                bool(raw_tool_calls),
                [
                    _canonicalize_tool_name_for_log(
                        _restore_tool_name_from_openai(
                            tc.get("function", {}).get("name", ""),
                            tool_name_map,
                        ),
                        tool_name_map,
                    )
                    for tc in (raw_tool_calls or [])
                ],
            )

            if not raw_tool_calls:
                return (
                    response_text or "I processed your message but received an empty response.",
                    build_conversation_guardrail_usage(),
                )

            local_messages.append(
                {
                    "role": "assistant",
                    "content": response_text or "",
                    "tool_calls": raw_tool_calls,
                }
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

                try:
                    self._permission_manager.check_tool_allowed(
                        original_name,
                        allowed_tools,
                        role_id,
                    )
                except PermissionDeniedError as exc:
                    tool_result: Any = {"error": f"Permission denied: {exc}"}
                    logger.warning(
                        "Conversation tool denied (from context): session=%s tool=%s error=%s",
                        conv_session_id,
                        original_name,
                        exc,
                    )
                else:
                    delegated_target_slug = _extract_agent_delegation_target(original_name)
                    if delegated_target_slug is not None:
                        guardrail_state.delegated_steps += 1
                        next_depth = guardrail_state.delegation_depth + 1
                        if next_depth > guardrail_state.max_delegation_depth:
                            return "Delegation depth limit exceeded.", build_conversation_guardrail_usage()
                        if guardrail_state.delegated_steps > guardrail_state.max_delegated_steps:
                            return "Delegated-step budget exceeded.", build_conversation_guardrail_usage()

                        delegation_payload = _build_delegation_request_payload(args)
                        delegation_payload["__delegation_depth"] = next_depth
                        tool_result = await comm_hub_client.call_a2a_request(
                            target_agent_type_slug=delegated_target_slug,
                            session_id=str(conv_session_id),
                            requester_role_id=(str(role_id_raw) if role_id_raw else None),
                            request_payload=delegation_payload,
                            session_link_id=args.get("session_link_id"),
                            wait_for_response=True,
                            wait_timeout_seconds=45.0,
                        )
                    else:
                        logger.info(
                            "Conversation tool dispatch (from context): session=%s tool=%s route_type=%s",
                            conv_session_id,
                            original_name,
                            _tool_route_type(original_name),
                        )
                        tool_result = await self._execute_mcp_tool_ar(
                            original_name,
                            args,
                            role_mcp_sessions,
                            str(agent_type_id),
                            str(conv_session_id),
                            comm_hub_client,
                        )

                local_messages.append(
                    {
                        "role": "tool",
                        "content": str(tool_result),
                        "tool_call_id": call_id,
                    }
                )

        return (
            "I was unable to complete the task within the allowed number of steps.",
            build_conversation_guardrail_usage(),
        )

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
                "model_id": agent_type.model_id,
                "input_type": agent_type.input_type.value,
                "system_instruction_length": len(agent_type.system_instruction or ""),
                "identity_name": identity_name,
                "role_name": role_name,
            },
        )

        # Resolve permissions
        allowed_tools: set[str] = set()
        if agent_type.role_id:
            with tracer.start_as_current_span(
                "runtime_executor.resolve_permissions",
                attributes={"role_id": str(agent_type.role_id)},
            ):
                allowed_tools = await self._permission_manager.calculate_allowed_tools(
                    agent_type.role_id, db
                )
                delegated_agent_types = await self._permission_manager.calculate_allowed_agent_types(
                    agent_type.role_id,
                    db,
                )
                allowed_tools.update(
                    {build_tool_name("agent", slug) for slug in delegated_agent_types}
                )
        else:
            logger.warning(
                "AgentType %s has no role — no tools permitted beyond save_result",
                agent_type.id,
            )
            allowed_tools = {"save_result"}

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
                "role_id": str(agent_type.role_id) if agent_type.role_id else None,
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
            ctx = TaskAgentLoop(
                session_id=str(job.id),
                agent_type_id=str(job.agent_type_id),
                role_id=str(agent_type.role_id) if agent_type.role_id else None,
                allowed_tools=sorted(allowed_tools),
                system_instruction=agent_type.system_instruction,
                output_type=agent_type.output_type.value,
                output_schema=agent_type.output_schema,
                input_data=job.input_data,
            )

            # ── Load SOP content and append to system instruction ─────────────
            if agent_type.primary_sop_id:
                sop_content = await self._load_sop_content(agent_type.primary_sop_id, db)
                if sop_content:
                    base = ctx.system_instruction or ""
                    ctx.system_instruction = f"{base}\n\n{sop_content}".strip()
                    await self._log_execution_event(
                        session_id=job.id,
                        event_type="sop_loaded",
                        message=f"SOP content loaded into system instruction",
                        data={
                            "primary_sop_id": str(agent_type.primary_sop_id),
                            "sop_content": sop_content,
                            "sop_content_preview": sop_content[:300],
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
            while ctx.should_continue():
                ctx = await self._observe(ctx, db)
                ctx = await self._reason(ctx, agent_type, db)
                ctx = await self._act(ctx, allowed_tools, db)
                ctx.iteration += 1

            output_data: dict[str, Any] = ctx.output_data or {
                "tool_results": ctx.tool_results,
                "message": "Task completed",
                "iterations": ctx.iteration,
            }

            await self._log_execution_event(
                session_id=job.id,
                event_type="task_loop_completed",
                message="Task loop completed",
                data={
                    "iterations": ctx.iteration,
                    "tool_results_count": len(ctx.tool_results),
                    "output_keys": list(output_data.keys()),
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

            # ── Load SOP content and append to system instruction ─────────────
            if agent_type.primary_sop_id:
                sop_content = await self._load_sop_content(agent_type.primary_sop_id, db)
                if sop_content:
                    base = ctx.system_instruction or ""
                    ctx.system_instruction = f"{base}\n\n{sop_content}".strip()

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
                    from app.services.agents.model_binding import (
                        ModelBindingLayer,
                        ModelBindingError,
                    )
                    binding = ModelBindingLayer()
                    model_config = await binding.resolve_model_config(agent_type.model_id, db)
                    raw_response = await binding.complete(
                        agent_type=agent_type,
                        model_config=model_config,
                        messages=full_messages,
                        tools=tool_defs if tool_defs else None,
                    )

                    provider = model_config.provider_type
                    response_text = ModelBindingLayer.extract_text(raw_response, provider)
                    raw_tool_calls = ModelBindingLayer.extract_tool_calls(raw_response, provider)

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
                    target_slug = _extract_agent_delegation_target(tool_name)
                    result = await comm_hub_client.call_a2a_request(
                        target_agent_type_slug=target_slug or "",
                        session_id=ctx.session_id,
                        requester_role_id=ctx.role_id,
                        request_payload=_build_delegation_request_payload(tool_args),
                        session_link_id=tool_args.get("session_link_id"),
                        wait_for_response=True,
                        wait_timeout_seconds=45.0,
                    )
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

            record = ResultRecord(
                agent_type_id=uuid.UUID(ctx.agent_type_id),
                payload=args.get("data") or args,
                content_type="application/json",
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
        ``primary_sop_id``: "Follow the SOP '<name>' to complete the task".
        """
        if agent_type.input_type == AgentInputType.none:
            if not agent_type.primary_sop_id:
                logger.warning(
                    "none-input agent_type %s has no primary_sop_id set",
                    agent_type.id,
                )
                return None
            if db:
                from sqlalchemy import select
                from app.db.models.skills import Sop

                try:
                    row = await db.execute(
                        select(Sop.name).where(Sop.id == agent_type.primary_sop_id)
                    )
                    sop_name = row.scalar_one_or_none()
                    if sop_name:
                        return f"Follow the SOP '{sop_name}' to complete the task"
                    logger.warning(
                        "primary_sop_id %s not found for agent_type %s",
                        agent_type.primary_sop_id,
                        agent_type.id,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to resolve SOP for none-input agent_type %s: %s",
                        agent_type.id,
                        exc,
                    )
            return None
        if not input_data:
            return None
        if isinstance(input_data, dict):
            # Conversational: use the initial message
            if "message" in input_data:
                return str(input_data["message"])
            # Typed: serialise as compact JSON for the prompt
            import json
            return json.dumps(input_data, ensure_ascii=False)
        return str(input_data)


