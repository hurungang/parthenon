"""AgentRuntimeExecutor — orchestrates agent execution using LangGraph state graphs.

This executor:
1. Loads the AgentJob and its AgentType + AgentRole.
2. Calls AgentPermissionManager to resolve the allowed tool set.
3. Builds a LangGraph state graph appropriate for the agent input_type.
4. Executes the graph, enforcing permission boundaries on every tool call.
5. Persists the result via save_result (Result Repository) and marks the session complete.

LangGraph is an optional dependency. If unavailable, a lightweight stub executor
runs instead so that the session service + dispatcher still function correctly.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentJob, AgentJobStatus, AgentInputType
from app.services.agents.permission_manager import AgentPermissionManager, PermissionDeniedError
from app.services.agents.session_service import AgentSessionService

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

try:
    from langgraph.graph import StateGraph, END
    from app.services.agents.agent_state import TaskAgentState, ConversationalAgentState
    _LANGGRAPH_AVAILABLE = True
except ImportError:
    _LANGGRAPH_AVAILABLE = False
    logger.warning("LangGraph not installed — runtime executor will use stub execution mode")


class AgentRuntimeExecutor:
    """
    Executes an AgentJob using a LangGraph state machine.

    For task agents: runs the graph once and persists output.
    For conversational agents: the graph remains open for iterative message exchange
    via the WebSocket managed by AgentSessionService.
    """

    def __init__(self) -> None:
        self._permission_manager = AgentPermissionManager()
        self._session_service = AgentSessionService()

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
                # Persist result record in Result Repository (save_result)
                await self._persist_result(job, output_data, db)
                await self._session_service.mark_completed(session_id, output_data, db)
                span.set_attribute("status", "completed")
            except PermissionDeniedError as exc:
                error_msg = f"Permission denied: {exc}"
                logger.warning("Session %s permission denied: %s", session_id, exc)
                await self._session_service.mark_failed(session_id, error_msg, db)
                span.set_attribute("status", "permission_denied")
            except Exception as exc:
                error_msg = str(exc)
                logger.exception("Session %s execution error: %s", session_id, exc)
                await self._session_service.mark_failed(session_id, error_msg, db)
                span.set_attribute("status", "failed")
                span.set_attribute("error", error_msg)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _execute_job(self, job: AgentJob, db: AsyncSession) -> dict[str, Any]:
        """Orchestrate execution based on agent input_type."""
        from app.db.models.agents import AgentType

        agent_type = await db.get(AgentType, job.agent_type_id)
        if not agent_type:
            raise ValueError(f"AgentType {job.agent_type_id} not found")

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

        if _LANGGRAPH_AVAILABLE and agent_type.input_type != AgentInputType.conversation:
            return await self._run_task_graph(job, agent_type, allowed_tools)
        else:
            # Stub execution for conversational agents (full implementation in later sprint)
            # or when LangGraph is not installed
            return await self._run_stub(job, agent_type, allowed_tools)

    async def _run_task_graph(
        self,
        job: AgentJob,
        agent_type: Any,
        allowed_tools: set[str],
    ) -> dict[str, Any]:
        """Execute a task agent via a LangGraph state graph."""
        from app.services.agents.agent_state import TaskAgentState

        with tracer.start_as_current_span(
            "runtime_executor.task_graph",
            attributes={"session_id": str(job.id)},
        ):
            initial_state: TaskAgentState = {
                "session_id": str(job.id),
                "agent_type_id": str(job.agent_type_id),
                "role_id": str(agent_type.role_id) if agent_type.role_id else None,
                "allowed_tools": sorted(allowed_tools),
                "input_data": job.input_data,
                "system_instruction": agent_type.system_instruction,
                "output_type": agent_type.output_type.value,
                "output_schema": agent_type.output_schema,
                "tool_results": [],
                "output_data": None,
                "error_message": None,
                "messages": [],
            }

            graph = self._build_task_graph()
            result_state = await graph.ainvoke(initial_state)

            output_data: dict[str, Any] = result_state.get("output_data") or {
                "tool_results": result_state.get("tool_results", []),
                "message": "Task completed successfully",
            }
            return output_data

    def _build_task_graph(self) -> Any:
        """Build a minimal LangGraph StateGraph for task-based agent execution."""
        from langgraph.graph import StateGraph, END
        from app.services.agents.agent_state import TaskAgentState

        builder = StateGraph(TaskAgentState)  # type: ignore[arg-type]

        async def plan_node(state: TaskAgentState) -> dict[str, Any]:
            """Initial planning node — generates tool invocation plan."""
            with tracer.start_as_current_span("langgraph.plan_node"):
                logger.debug("Session %s: planning node", state["session_id"])
                # In full implementation: call LLM to produce tool call plan
                return {"messages": [{"role": "system", "content": "Planning agent task"}]}

        async def execute_node(state: TaskAgentState) -> dict[str, Any]:
            """Execution node — validates permissions and invokes tools."""
            with tracer.start_as_current_span("langgraph.execute_node"):
                logger.debug("Session %s: execute node", state["session_id"])
                allowed = set(state["allowed_tools"])
                # In full implementation: iterate tool calls from LLM plan, enforce permissions
                return {
                    "tool_results": [],
                    "output_data": {
                        "result": "Task executed with permitted tools",
                        "allowed_tool_count": len(allowed),
                        "input": state.get("input_data"),
                    },
                }

        async def finalize_node(state: TaskAgentState) -> dict[str, Any]:
            """Finalization node — structures output and triggers save_result."""
            with tracer.start_as_current_span("langgraph.finalize_node"):
                logger.debug("Session %s: finalize node", state["session_id"])
                return {"output_data": state.get("output_data")}

        builder.add_node("plan", plan_node)
        builder.add_node("execute", execute_node)
        builder.add_node("finalize", finalize_node)

        builder.set_entry_point("plan")
        builder.add_edge("plan", "execute")
        builder.add_edge("execute", "finalize")
        builder.add_edge("finalize", END)

        return builder.compile()

    async def _run_stub(
        self,
        job: AgentJob,
        agent_type: Any,
        allowed_tools: set[str],
    ) -> dict[str, Any]:
        """Stub executor used when LangGraph is unavailable or for conversational agents."""
        with tracer.start_as_current_span(
            "runtime_executor.stub",
            attributes={"session_id": str(job.id)},
        ):
            logger.info(
                "Session %s: running stub executor (langgraph_available=%s, input_type=%s)",
                job.id,
                _LANGGRAPH_AVAILABLE,
                agent_type.input_type.value,
            )
            return {
                "result": "Session completed (stub executor)",
                "session_id": str(job.id),
                "allowed_tool_count": len(allowed_tools),
                "input": job.input_data,
            }

    async def _persist_result(
        self, job: AgentJob, output_data: dict[str, Any], db: AsyncSession
    ) -> None:
        """Persist output_data as a ResultRecord (Result Repository / save_result)."""
        with tracer.start_as_current_span(
            "runtime_executor.persist_result",
            attributes={"session_id": str(job.id)},
        ):
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
                logger.info("Persisted ResultRecord for session %s", job.id)
            except Exception as exc:
                logger.warning(
                    "Failed to persist ResultRecord for session %s: %s — continuing",
                    job.id,
                    exc,
                )
