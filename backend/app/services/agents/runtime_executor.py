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
from typing import Any

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentJob, AgentJobStatus, AgentInputType
from app.services.agents.agent_loop import TaskAgentLoop, ConversationalAgentLoop
from app.services.agents.permission_manager import AgentPermissionManager, PermissionDeniedError
from app.services.agents.session_service import AgentSessionService

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


class AgentRuntimeExecutor:
    """
    Executes an AgentJob using the LangChain deep agent observe-reason-act loop.

    For task agents: iterates until the agent signals completion or max iterations.
    For conversational agents: the loop is driven externally via WebSocket messages.
    """

    def __init__(self) -> None:
        self._permission_manager = AgentPermissionManager()
        self._session_service = AgentSessionService()

    # ── Execution Log Helper ───────────────────────────────────────────────────

    async def _log_execution_event(
        self,
        session_id: uuid.UUID,
        event_type: str,
        message: str,
        data: dict[str, Any],
        db: AsyncSession,
        log_level: str = "INFO",
    ) -> None:
        """Persist a structured execution event entry and emit to the Python logger."""
        from app.db.models.session_logs import ExecutionLogEntry
        from datetime import datetime, UTC

        logger.info("[%s] %s: %s", session_id, event_type, message, extra={"data": data})

        entry = ExecutionLogEntry(
            id=uuid.uuid4(),
            session_id=session_id,
            event_type=event_type,
            log_level=log_level,
            message=message,
            data=data or {},
            timestamp=datetime.now(UTC),
        )
        db.add(entry)
        try:
            await db.flush()
        except Exception as exc:
            logger.warning(
                "Failed to flush execution log entry for session %s: %s", session_id, exc
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
            db=db,
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
                db=db,
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
        self, allowed_tools: set[str], db: AsyncSession
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """Load MCP tool schemas for all allowed tools and return as OpenAI tool definitions.

        System tools (``save_result``, ``send_notification``) are always included.
        All other active MCP tools whose name appears in allowed_tools are fetched
        and wrapped in the OpenAI function-calling schema.
        
        Returns:
            Tuple of (tool_definitions, tool_name_map) where tool_name_map maps
            sanitized names back to original names for MCP tool lookup.
        """
        from sqlalchemy import select
        from app.db.models.mcp_hub import McpTool

        defs: list[dict[str, Any]] = [_SAVE_RESULT_TOOL_DEF]
        tool_name_map: dict[str, str] = {}  # Maps sanitized_name -> original_name
        
        # Add send_notification system tool
        defs.append({
            "type": "function",
            "function": {
                "name": "send_notification",
                "description": "Send a notification to user or system channels",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string", "description": "Notification channel (email, slack, teams)"},
                        "title": {"type": "string", "description": "Notification title"},
                        "message": {"type": "string", "description": "Notification message"},
                    },
                    "required": ["channel", "title", "message"],
                },
            },
        })

        # Filter out system tools from MCP query; identifiers are mcp_slug/tool_name
        tool_names = []
        for t in allowed_tools:
            if t in ("save_result", "send_notification"):
                continue
            tool_names.append(t)
        
        if not tool_names:
            logger.debug("No MCP tools to load (only system tools)")
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

    async def run(self, session_id: uuid.UUID, db: AsyncSession) -> None:
        """Entry point called by SessionDispatcher. Executes the session end-to-end."""
        with tracer.start_as_current_span(
            "runtime_executor.run",
            attributes={"session_id": str(session_id)},
        ) as span:
            job = await db.get(AgentJob, session_id)
            if not job:
                logger.error("AgentJob %s not found during executor run", session_id)
                return

            if job.status != AgentJobStatus.running:
                logger.warning(
                    "Session %s is not in 'running' state (status=%s) — skipping",
                    session_id,
                    job.status,
                )
                return

            try:
                output_data = await self._execute_job(job, db)
                # Result persistence is handled by the LLM calling save_result as a tool.
                # _persist_result() is no longer called automatically here.
                await self._session_service.mark_completed(session_id, output_data, db)
                span.set_attribute("status", "completed")

                await self._log_execution_event(
                    session_id=session_id,
                    event_type="session_completed",
                    message="Session completed successfully",
                    data={"output_keys": list(output_data.keys()) if output_data else []},
                    db=db,
                )
            except PermissionDeniedError as exc:
                error_msg = f"Permission denied: {exc}"
                logger.warning("Session %s permission denied: %s", session_id, exc)
                await self._log_execution_event(
                    session_id=session_id,
                    event_type="error",
                    message=error_msg,
                    data={"exception_type": type(exc).__name__},
                    db=db,
                    log_level="ERROR",
                )
                await self._session_service.mark_failed(session_id, error_msg, db)
                span.set_attribute("status", "permission_denied")
            except Exception as exc:
                error_msg = str(exc)
                logger.exception("Session %s execution error: %s", session_id, exc)
                await self._log_execution_event(
                    session_id=session_id,
                    event_type="error",
                    message=error_msg,
                    data={"exception_type": type(exc).__name__},
                    db=db,
                    log_level="ERROR",
                )
                await self._session_service.mark_failed(session_id, error_msg, db)
                span.set_attribute("status", "failed")
                span.set_attribute("error", error_msg)

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

        await self._log_execution_event(
            session_id=job.id,
            event_type="session_started",
            message="Session execution started",
            data={
                "agent_type_id": str(job.agent_type_id),
                "model_id": agent_type.model_id,
                "input_type": agent_type.input_type.value,
                "system_instruction_length": len(agent_type.system_instruction or ""),
            },
            db=db,
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
                "allowed_tools": sorted(allowed_tools),
                "role_id": str(agent_type.role_id) if agent_type.role_id else None,
            },
            db=db,
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
                        db=db,
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
                        db=db,
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
                db=db,
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
                db=db,
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
                db=db,
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
                    "tool_count": len(tool_defs),
                    "available_tools": tool_names,
                },
                db=db,
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
                db=db,
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
                        db=db,
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
                        db=db,
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
                    db=db,
                )
                
                # Only apply stub reasoning if LangChain is unavailable or if explicitly stub mode
                # If there's an actual error, mark session as failed instead
                if "llm_error" in locals():
                    # LLM call failed - mark as error and stop
                    ctx.output_data = {
                        "error": "LLM call failed",
                        "details": llm_error,
                    }
                    ctx.is_complete = True
                    logger.error("Session %s marked as failed due to LLM error", ctx.session_id)
                else:
                    # Pure stub mode (no LangChain) - use synthetic save_result
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
                    db=db,
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
                    db=db,
                )

                if tool_name == "save_result":
                    result = await self._handle_save_result_tool_call(ctx, tool_args, db)
                else:
                    result = await self._execute_mcp_tool(
                        tool_name, tool_args, db, role_mcp_sessions
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
                db=db,
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
            db=db,
        )

        return {"status": "saved", "result_id": result_id}

    async def _load_role_mcp_session_map(
        self, role_id: uuid.UUID, db: AsyncSession
    ) -> dict[str, str]:
        """Load a map of server_id -> mcp_session_id for the role.
        
        Returns:
            Dict mapping server UUID (as string) to MCP session UUID (as string)
        """
        from sqlalchemy import select
        from app.db.models.agents import AgentRoleMcpSession
        from app.db.models.mcp_hub import McpSession
        
        result = await db.execute(
            select(McpSession.id, McpSession.server_id)
            .join(AgentRoleMcpSession, AgentRoleMcpSession.mcp_session_id == McpSession.id)
            .where(AgentRoleMcpSession.role_id == role_id)
            .where(McpSession.is_active.is_(True))
        )
        
        return {str(row.server_id): str(row.id) for row in result.all()}

    async def _execute_mcp_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        db: AsyncSession,
        role_mcp_sessions: dict[str, str],
    ) -> dict[str, Any]:
        """Dispatch a single MCP tool call via McpProxyEngine.

        Looks up the McpTool record by namespaced name, loads its server
        relationship, and calls the proxy with the MCP session assigned to the
        role for that server. Returns an error dict on any failure so the agent
        loop can continue rather than abort.
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
            
            # Look up the MCP session ID for this tool's server from role assignments
            server_id_str = str(tool.server_id)
            mcp_session_id = role_mcp_sessions.get(server_id_str)
            
            if not mcp_session_id:
                logger.error(
                    "No MCP session assigned to role for server %s (tool: %s)",
                    server_id_str,
                    tool_name,
                )
                return {
                    "error": f"No MCP session configured for server {tool.server.name}. "
                    f"Please assign an MCP session to the role for this server."
                }

            proxy = McpProxyEngine()
            tool_result = await proxy.call_tool(
                tool=tool,
                tool_input=tool_args,
                db=db,
                session_id=mcp_session_id,
            )
            return {"result": tool_result}
        except McpProxyError as exc:
            logger.error("MCP tool '%s' call failed: %s", tool_name, exc)
            return {"error": str(exc)}
        except Exception as exc:
            logger.error("MCP tool '%s' unexpected error: %s", tool_name, exc)
            return {"error": str(exc)}

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
                db=db,
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


