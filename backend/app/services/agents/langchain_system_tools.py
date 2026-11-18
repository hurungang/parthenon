"""LangChain System Tools — LangChain BaseTool subclasses for Parthenon system operations.

These replace the inline tool-dispatch checks in runtime_executor.py with
proper LangChain tool objects that can be bound to a ChatModel.

System tools:
- LangChainSendNotificationTool — sends a notification via CommHub
- LangChainGetRecipientGroupTool — retrieves a recipient group
- LangChainHumanInterveneTool — requests human intervention (HITL)
- LangChainQueryResultTool    — queries a previously stored result
- LangChainSaveDataTool       — saves named intermediate data via CommHub
- LangChainGetDataTool        — retrieves named intermediate data via CommHub
- LangChainGetOutputTool      — retrieves typed agent outputs via CommHub

These tools are constructed with references to the data_client and
comm_hub_client at runtime so they are ready for LangChain execution.
"""
from __future__ import annotations

import json
import logging
from typing import Any, List, Literal, Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Arg schemas ───────────────────────────────────────────────────────────────

class _SendNotificationArgs(BaseModel):
    message: str = Field(description="Notification message to send.")
    recipient_group_id: Optional[str] = Field(default=None, description="Recipient group identifier.")
    subject: Optional[str] = Field(default=None, description="Optional notification subject.")


class _GetRecipientGroupArgs(BaseModel):
    group_id: str = Field(description="Recipient group ID to look up.")


class _HumanInterveneArgs(BaseModel):
    intervention_type: Literal["approval", "choice", "text"] = Field(description="Type of intervention: 'approval' (yes/no), 'choice' (pick from list), or 'text' (free-form input).")
    reason: str = Field(description="Reason why human intervention is needed.")
    choices: Optional[List[str]] = Field(default=None, description="Optional list of choices for the human (used with 'choice' type).")
    prompt: Optional[str] = Field(default=None, description="Optional prompt text to display to the human.")


class _QueryResultArgs(BaseModel):
    session_id: Optional[str] = Field(default=None, description="Session ID to query results from.")
    query: Optional[str] = Field(default=None, description="Optional query filter.")


class _RequestLiveTestArgs(BaseModel):
    script_version_id: str = Field(
        description=(
            "The SAVED script version to run end-to-end (the `version_id` "
            "returned by `generate_script`). The whole script runs once."
        )
    )
    reason: str = Field(
        description="Why replay cannot prove this script — what is missing."
    )
    agent_type_id: Optional[str] = Field(
        default=None, description="The subject agent type id (this conversation's agent)."
    )


class LangChainSendNotificationTool(BaseTool):
    """LangChain tool that sends a notification via CommHub."""

    name: str = "send_notification"
    description: str = (
        "Send a notification to a user or group. Use this to inform users of "
        "important events, task completions, or updates."
    )
    args_schema: Type[BaseModel] = _SendNotificationArgs

    comm_hub_client: Any = Field(exclude=True)
    session_id: str = Field(exclude=True)
    agent_type_id: str = Field(exclude=True, default="")

    class Config:
        arbitrary_types_allowed = True

    def _run(self, message: str, recipient_group_id: Optional[str] = None, subject: Optional[str] = None) -> str:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(
                self._arun(message=message, recipient_group_id=recipient_group_id, subject=subject)
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    async def _arun(self, message: str, recipient_group_id: Optional[str] = None, subject: Optional[str] = None) -> str:
        try:
            args: dict[str, Any] = {"message": message}
            if recipient_group_id:
                args["recipient_group_id"] = recipient_group_id
            if subject:
                args["subject"] = subject
            result = await self.comm_hub_client.call_tool(
                tool_name="send_notification",
                tool_args=args,
                session_id=self.session_id,
                agent_type_id=self.agent_type_id,
            )
            return json.dumps(result) if isinstance(result, (dict, list)) else str(result)
        except Exception as exc:
            logger.error("LangChainSendNotificationTool failed: %s", exc)
            return json.dumps({"error": str(exc)})


class LangChainGetRecipientGroupTool(BaseTool):
    """LangChain tool that retrieves a recipient group from CommHub."""

    name: str = "get_recipient_group"
    description: str = (
        "Get information about a recipient group by ID. "
        "Use this to look up who should receive notifications or reports."
    )
    args_schema: Type[BaseModel] = _GetRecipientGroupArgs

    comm_hub_client: Any = Field(exclude=True)
    session_id: str = Field(exclude=True)
    agent_type_id: str = Field(exclude=True, default="")

    class Config:
        arbitrary_types_allowed = True

    def _run(self, group_id: str) -> str:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._arun(group_id=group_id))
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    async def _arun(self, group_id: str) -> str:
        try:
            result = await self.comm_hub_client.call_tool(
                tool_name="get_recipient_group",
                tool_args={"group_id": group_id},
                session_id=self.session_id,
                agent_type_id=self.agent_type_id,
            )
            return json.dumps(result) if isinstance(result, (dict, list)) else str(result)
        except Exception as exc:
            logger.error("LangChainGetRecipientGroupTool failed: %s", exc)
            return json.dumps({"error": str(exc)})


class LangChainHumanInterveneTool(BaseTool):
    """LangChain tool that requests human intervention (HITL) via LangGraph interrupt().

    Calls CommHub to register the intervention, then raises LangGraph interrupt()
    to pause agent execution. The calling code catches GraphInterrupt, extracts
    the conversation state, and saves it to the Control Center DB.
    """

    name: str = "human_intervene"
    description: str = (
        "Request human intervention. Use when you need human approval, input, or "
        "confirmation to proceed. Execution pauses until the human responds."
    )
    args_schema: Type[BaseModel] = _HumanInterveneArgs

    comm_hub_client: Any = Field(exclude=True)
    session_id: str = Field(exclude=True)
    agent_type_id: str = Field(exclude=True, default="")
    conv_session_id: Optional[str] = Field(default=None, exclude=True)
    # Optional async callback for tool-call recording (runtime monitor).
    tool_call_recorder: Optional[Any] = Field(default=None, exclude=True)

    class Config:
        arbitrary_types_allowed = True

    def _run(
        self,
        intervention_type: str,
        reason: str,
        choices: Optional[list] = None,
        prompt: Optional[str] = None,
    ) -> str:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(
                self._arun(
                    intervention_type=intervention_type,
                    reason=reason,
                    choices=choices,
                    prompt=prompt,
                )
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    async def _arun(
        self,
        intervention_type: str,
        reason: str,
        choices: Optional[list] = None,
        prompt: Optional[str] = None,
    ) -> str:
        """Register intervention with CommHub then interrupt agent via LangGraph."""
        from langgraph.types import interrupt

        import time

        _started = time.monotonic()
        _call_status = "success"
        _call_error: Optional[str] = None
        try:
            result = await self.comm_hub_client.call_human_intervene(
                session_id=self.session_id,
                intervention_type=intervention_type,
                reason=reason,
                choices=choices,
                prompt=prompt,
                conv_session_id=self.conv_session_id,
            )
            # CommHub wraps CC's SystemToolResponse, which itself has a 'result' key.
            # This can create double-nesting: {"result": {"request_id": ...}}.
            # Try top-level first, then nested 'result' key as fallback.
            request_id = (
                result.get("request_id")
                or result.get("result", {}).get("request_id", "")
                or ""
            )
        except Exception as exc:
            logger.error("LangChainHumanInterveneTool: CommHub call failed: %s", exc)
            _call_status = "error"
            _call_error = str(exc)
            # Registration failed — do NOT interrupt; return error so the model
            # can decide how to proceed (retry, skip, or complete without HITL).
            return json.dumps({"error": str(exc)})
        finally:
            recorder = self.tool_call_recorder
            if recorder is not None:
                try:
                    await recorder(
                        tool_name="human_intervene",
                        route_type="system",
                        status=_call_status,
                        duration_ms=int((time.monotonic() - _started) * 1000),
                        mcp_slug="system",
                        error=_call_error,
                    )
                except Exception as exc:
                    logger.warning(
                        "Tool-call recording failed for human_intervene: %s", exc
                    )

        # CommHub registration succeeded — pause the agent with LangGraph's
        # native interrupt/resume.  This is the SAME mechanism the task path
        # has always used: a replayed tool task (LangGraph re-executes the
        # interrupted task on resume) reuses the pending request on the CC
        # side, and ``interrupt()`` returns the operator's resume value.
        # The in-process ``conversation_resume`` future is retired — a paused
        # conversational turn is durably resumable on any AR instance.
        resume_value = interrupt(
            {"request_id": request_id, "intervention_type": intervention_type, "reason": reason}
        )

        # Reached only after Command(resume=...): surface the operator's
        # response as the tool result so the model can act on the approval
        # (FIX-20261031-133253 confirmation-before-write contract).
        if isinstance(resume_value, dict):
            return json.dumps(
                {
                    "status": "approved" if resume_value.get("approval_value") else "resolved",
                    "request_id": request_id,
                    **resume_value,
                }
            )
        return json.dumps({"status": "pending", "request_id": request_id})


class LangChainRequestLiveTestTool(BaseTool):
    """LangChain tool that asks for ONE operator-approved live run of a script.

    The conversational optimizer is replay-only. When replay cannot prove a
    script, this tool proposes running **that saved script** once, end to end,
    and pauses the turn with LangGraph's ``interrupt()`` — the same durable
    pause/resume chain as every other in-chat decision:

    1. Control Center validates the request (the script version must be this
       agent's own, saved and runnable, with a statically previewable
       ``tools.call`` set), derives the tool-call preview from the script
       source, and records the ledger row plus an ``approval`` intervention
       (nothing runs and nothing is granted yet);
    2. ``interrupt()`` pauses the turn with the approval card payload;
    3. on resume the operator's decision has already been consumed by Control
       Center; for an approval, the script ran ONCE under this agent's own
       identity and the run record (result + telemetry) rides the resume value,
       which is returned to the model as this tool's result.

    A refusal (unknown/foreign version, no tool calls, out-of-grant script,
    already pending, quota exhausted) is returned as a structured refusal and
    the turn does NOT pause. A replayed tool task (LangGraph re-executes the
    interrupted task on resume) finds the terminal ledger row and returns that
    stored outcome instead of asking for a second approval.
    """

    name: str = "request_live_test"
    description: str = (
        "Request ONE operator-approved live run of a SCRIPT you already saved. "
        "A live test runs the whole script end-to-end against live MCP tools — "
        "it is NOT a per-tool test and MCP tools are assumed to work. Use it "
        "only when replay cannot prove the script: save it with "
        "`generate_script`, then pass its `version_id` as `script_version_id` "
        "plus the reason. The operator must approve; the script runs once, as "
        "this agent, and never automatically. Never request a live test for an "
        "individual tool, never repeat an earlier approval, and never include "
        "credentials, tokens or secrets."
    )
    args_schema: Type[BaseModel] = _RequestLiveTestArgs

    comm_hub_client: Any = Field(exclude=True)
    session_id: str = Field(exclude=True)
    agent_type_id: str = Field(exclude=True, default="")
    conv_session_id: Optional[str] = Field(default=None, exclude=True)
    tool_call_recorder: Optional[Any] = Field(default=None, exclude=True)

    class Config:
        arbitrary_types_allowed = True

    def _run(
        self,
        script_version_id: str,
        reason: str,
        agent_type_id: Optional[str] = None,
    ) -> str:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(
                self._arun(
                    script_version_id=script_version_id,
                    reason=reason,
                    agent_type_id=agent_type_id,
                )
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    async def _arun(
        self,
        script_version_id: str,
        reason: str,
        agent_type_id: Optional[str] = None,
    ) -> str:
        """Record the proposal via Control Center, then pause (or refuse)."""
        from langgraph.types import interrupt

        import time

        _started = time.monotonic()
        _call_status = "success"
        _call_error: Optional[str] = None
        try:
            result = await self.comm_hub_client.call_request_live_test(
                session_id=self.session_id,
                script_version_id=str(script_version_id or ""),
                reason=str(reason or ""),
                # Never widen the subject here: Control Center derives it from
                # the conversation and refuses any other agent type.
                agent_type_id=str(agent_type_id or self.agent_type_id or ""),
                conv_session_id=self.conv_session_id,
            )
        except Exception as exc:
            logger.error("LangChainRequestLiveTestTool: CommHub call failed: %s", exc)
            _call_status = "error"
            _call_error = str(exc)
            return json.dumps({"status": "error", "error": str(exc)})
        finally:
            recorder = self.tool_call_recorder
            if recorder is not None:
                try:
                    await recorder(
                        tool_name="request_live_test",
                        route_type="system",
                        status=_call_status,
                        duration_ms=int((time.monotonic() - _started) * 1000),
                        mcp_slug="system",
                        error=_call_error,
                    )
                except Exception as exc:
                    logger.warning(
                        "Tool-call recording failed for request_live_test: %s", exc
                    )

        status = str(result.get("status") or "")
        if not status and isinstance(result.get("result"), dict):
            # Defensive: CH relays CC's body verbatim; never treat a wrapped
            # refusal as an approval.
            result = result["result"]
            status = str(result.get("status") or "")
        if status != "pending":
            # Refused (nothing recorded) or a replayed task finding the stored
            # outcome — never pause, just hand the result to the model.
            return json.dumps(result)

        live_test_request_id = result.get("live_test_request_id")
        intervene_request_id = result.get("intervene_request_id")
        resume_value = interrupt(
            {
                "request_id": intervene_request_id,
                "intervention_type": "approval",
                "reason": (
                    "Approval requested to run script version "
                    f"{result.get('script_version_id') or script_version_id} live."
                ),
                "live_test": {
                    "live_test_request_id": live_test_request_id,
                    "status": "pending",
                    "expires_at": result.get("expires_at"),
                    "script_version_id": result.get("script_version_id"),
                    # Tool-call PREVIEW of the script that will run (the script
                    # is the unit of approval, not these calls).
                    "operations": result.get("operations") or [],
                },
            }
        )

        # Reached only after Command(resume=...): Control Center has already
        # consumed the decision (and run the approved script once).
        if isinstance(resume_value, dict):
            return json.dumps(
                {
                    "status": "live_test_decided",
                    "live_test_request_id": live_test_request_id,
                    "live_test_status": resume_value.get("live_test_status"),
                    "approval_value": resume_value.get("approval_value"),
                    "script_version_id": resume_value.get("script_version_id")
                    or result.get("script_version_id"),
                    "script_run": resume_value.get("script_run"),
                    "executed_operations": resume_value.get("executed_operations"),
                    "live_test_error": resume_value.get("live_test_error"),
                    "selected_choice": resume_value.get("selected_choice"),
                    "text_value": resume_value.get("text_value"),
                }
            )
        return json.dumps({"status": "pending", **result})


class LangChainQueryResultTool(BaseTool):
    """LangChain tool that queries previously stored task results."""

    name: str = "query_result"
    description: str = (
        "Query stored results from previous agent sessions. "
        "Use this to retrieve data produced by earlier tasks."
    )
    args_schema: Type[BaseModel] = _QueryResultArgs

    comm_hub_client: Any = Field(exclude=True)
    session_id: str = Field(exclude=True)
    agent_type_id: str = Field(exclude=True, default="")

    class Config:
        arbitrary_types_allowed = True

    def _run(self, session_id: Optional[str] = None, query: Optional[str] = None) -> str:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._arun(session_id=session_id, query=query))
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    async def _arun(self, session_id: Optional[str] = None, query: Optional[str] = None) -> str:
        try:
            args: dict[str, Any] = {}
            if session_id:
                args["session_id"] = session_id
            if query:
                args["query"] = query
            result = await self.comm_hub_client.call_tool(
                tool_name="query_result",
                tool_args=args,
                session_id=self.session_id,
                agent_type_id=self.agent_type_id,
            )
            return json.dumps(result) if isinstance(result, (dict, list)) else str(result)
        except Exception as exc:
            logger.error("LangChainQueryResultTool failed: %s", exc)
            return json.dumps({"error": str(exc)})


# ── Arg schemas for new data tools ────────────────────────────────────────────

class _SaveDataArgs(BaseModel):
    data_name: str = Field(description="Name key for this data item.")
    data_value: dict = Field(description="JSON-serialisable value to store.")
    data_type: str = Field(default="json", description="Value type hint (default 'json').")


class _GetDataArgs(BaseModel):
    data_name: Optional[str] = Field(default=None, description="Filter by data name.")
    agent_type_id: Optional[str] = Field(default=None, description="Filter by agent type ID.")
    session_id: Optional[str] = Field(default=None, description="Filter by session ID.")
    limit: Optional[int] = Field(default=50, description="Maximum number of records to return.")


class _GetOutputArgs(BaseModel):
    agent_type_id: Optional[str] = Field(default=None, description="Filter by agent type ID.")
    session_id: Optional[str] = Field(default=None, description="Filter by session ID.")
    date_from: Optional[str] = Field(default=None, description="ISO date string — include records on or after.")
    date_to: Optional[str] = Field(default=None, description="ISO date string — include records on or before.")
    limit: Optional[int] = Field(default=50, description="Maximum number of records to return.")


class LangChainSaveDataTool(BaseTool):
    """LangChain tool that saves named intermediate data via CommHub."""

    name: str = "save_data"
    description: str = (
        "Save named intermediate data for later retrieval. Use this to persist "
        "any structured data produced during the task under a descriptive name."
    )
    args_schema: Type[BaseModel] = _SaveDataArgs

    comm_hub_client: Any = Field(exclude=True)
    session_id: str = Field(exclude=True)
    agent_type_id: str = Field(exclude=True, default="")

    class Config:
        arbitrary_types_allowed = True

    def _run(self, data_name: str, data_value: dict, data_type: str = "json") -> str:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(
                self._arun(data_name=data_name, data_value=data_value, data_type=data_type)
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    async def _arun(self, data_name: str, data_value: dict, data_type: str = "json") -> str:
        try:
            result = await self.comm_hub_client.call_tool(
                tool_name="save_data",
                tool_args={
                    "data_name": data_name,
                    "data_value": data_value,
                    "data_type": data_type,
                },
                session_id=self.session_id,
                agent_type_id=self.agent_type_id,
            )
            return json.dumps(result) if isinstance(result, (dict, list)) else str(result)
        except Exception as exc:
            logger.error("LangChainSaveDataTool failed for session %s: %s", self.session_id, exc)
            return json.dumps({"error": str(exc)})


class LangChainGetDataTool(BaseTool):
    """LangChain tool that retrieves named intermediate data via CommHub."""

    name: str = "get_data"
    description: str = (
        "Retrieve previously saved named data. At least one of data_name, "
        "agent_type_id, or session_id must be provided."
    )
    args_schema: Type[BaseModel] = _GetDataArgs

    comm_hub_client: Any = Field(exclude=True)
    session_id: str = Field(exclude=True)
    agent_type_id: str = Field(exclude=True, default="")

    class Config:
        arbitrary_types_allowed = True

    def _run(
        self,
        data_name: Optional[str] = None,
        agent_type_id: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: Optional[int] = 50,
    ) -> str:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(
                self._arun(
                    data_name=data_name,
                    agent_type_id=agent_type_id,
                    session_id=session_id,
                    limit=limit,
                )
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    async def _arun(
        self,
        data_name: Optional[str] = None,
        agent_type_id: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: Optional[int] = 50,
    ) -> str:
        try:
            args: dict[str, Any] = {}
            if data_name:
                args["data_name"] = data_name
            if agent_type_id:
                args["agent_type_id"] = agent_type_id
            if session_id:
                args["session_id"] = session_id
            if limit is not None:
                args["limit"] = limit
            result = await self.comm_hub_client.call_tool(
                tool_name="get_data",
                tool_args=args,
                session_id=self.session_id,
                agent_type_id=self.agent_type_id,
            )
            return json.dumps(result) if isinstance(result, (dict, list)) else str(result)
        except Exception as exc:
            logger.error("LangChainGetDataTool failed for session %s: %s", self.session_id, exc)
            return json.dumps({"error": str(exc)})


class LangChainGetOutputTool(BaseTool):
    """LangChain tool that retrieves typed agent outputs via CommHub."""

    name: str = "get_output"
    description: str = (
        "Retrieve typed agent output records. All filters are optional. "
        "Results are ordered by creation time, newest first."
    )
    args_schema: Type[BaseModel] = _GetOutputArgs

    comm_hub_client: Any = Field(exclude=True)
    session_id: str = Field(exclude=True)
    agent_type_id: str = Field(exclude=True, default="")

    class Config:
        arbitrary_types_allowed = True

    def _run(
        self,
        agent_type_id: Optional[str] = None,
        session_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: Optional[int] = 50,
    ) -> str:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(
                self._arun(
                    agent_type_id=agent_type_id,
                    session_id=session_id,
                    date_from=date_from,
                    date_to=date_to,
                    limit=limit,
                )
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    async def _arun(
        self,
        agent_type_id: Optional[str] = None,
        session_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: Optional[int] = 50,
    ) -> str:
        try:
            args: dict[str, Any] = {}
            if agent_type_id:
                args["agent_type_id"] = agent_type_id
            if session_id:
                args["session_id"] = session_id
            if date_from:
                args["date_from"] = date_from
            if date_to:
                args["date_to"] = date_to
            if limit is not None:
                args["limit"] = limit
            result = await self.comm_hub_client.call_tool(
                tool_name="get_output",
                tool_args=args,
                session_id=self.session_id,
                agent_type_id=self.agent_type_id,
            )
            return json.dumps(result) if isinstance(result, (dict, list)) else str(result)
        except Exception as exc:
            logger.error("LangChainGetOutputTool failed for session %s: %s", self.session_id, exc)
            return json.dumps({"error": str(exc)})
