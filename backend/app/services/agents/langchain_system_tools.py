"""LangChain System Tools — LangChain BaseTool subclasses for Parthenon system operations.

These replace the inline tool-dispatch checks in runtime_executor.py with
proper LangChain tool objects that can be bound to a ChatModel.

System tools:
- LangChainSaveResultTool     — stores the agent's final result (DEPRECATED)
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

class _SaveResultArgs(BaseModel):
    result_summary: str = Field(description="Summary of the result to save.")
    output_data: Optional[dict] = Field(default=None, description="Structured output data dict.")
    content_type: str = Field(default="text/plain", description="MIME type of the result.")


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


# ── Tool classes ──────────────────────────────────────────────────────────────

class LangChainSaveResultTool(BaseTool):
    """LangChain tool that stores the agent's final task result.

    Deprecated: use save_data instead. This tool is no longer bound to agent
    sessions. The class is retained only for backward compatibility with
    the final session completion flow in langchain_tool_wrapper.py.
    """

    name: str = "save_result"
    description: str = (
        "Save the final result of the task. Use this when you have completed the task "
        "and have a result to return. Provide a summary and optional structured data."
    )
    args_schema: Type[BaseModel] = _SaveResultArgs

    data_client: Any = Field(exclude=True)
    session_id: str = Field(exclude=True)

    class Config:
        arbitrary_types_allowed = True

    def _run(self, result_summary: str, output_data: Optional[dict] = None, content_type: str = "text/plain") -> str:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(
                self._arun(result_summary=result_summary, output_data=output_data, content_type=content_type)
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    async def _arun(self, result_summary: str, output_data: Optional[dict] = None, content_type: str = "text/plain") -> str:
        try:
            await self.data_client.save_output(
                session_id=self.session_id,
                result=result_summary,
                output_data=output_data or {},
                content_type=content_type,
            )
            return json.dumps({"status": "saved", "summary": result_summary[:100]})
        except Exception as exc:
            logger.error("LangChainSaveResultTool failed for session %s: %s", self.session_id, exc)
            return json.dumps({"error": str(exc)})


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

        request_id = ""
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
            # Registration failed — do NOT interrupt; return error so the model
            # can decide how to proceed (retry, skip, or complete without HITL).
            return json.dumps({"error": str(exc)})

        # CommHub registration succeeded — pause the agent.
        # GraphInterrupt is caught by _run_task_loop_ar, which extracts
        # conversation state from the checkpointer and saves it to CC DB.
        interrupt({"request_id": request_id, "intervention_type": intervention_type, "reason": reason})

        # Reached only if resumed via Command(resume=...) — not used in current impl.
        return json.dumps({"status": "pending", "request_id": request_id})


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
