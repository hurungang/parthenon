"""LangChain System Tools — LangChain BaseTool subclasses for Parthenon system operations.

These replace the inline tool-dispatch checks in runtime_executor.py with
proper LangChain tool objects that can be bound to a ChatModel.

System tools:
- LangChainSaveResultTool     — stores the agent's final result
- LangChainSendNotificationTool — sends a notification via CommHub
- LangChainGetRecipientGroupTool — retrieves a recipient group
- LangChainHumanInterveneTool — requests human intervention (HITL)
- LangChainQueryResultTool    — queries a previously stored result

These tools are constructed with references to the data_client and
comm_hub_client at runtime so they are ready for LangChain execution.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional, Type

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
    message: str = Field(description="Message to display to the human reviewer.")
    context: Optional[dict] = Field(default=None, description="Additional context for the reviewer.")


class _QueryResultArgs(BaseModel):
    session_id: Optional[str] = Field(default=None, description="Session ID to query results from.")
    query: Optional[str] = Field(default=None, description="Optional query filter.")


# ── Tool classes ──────────────────────────────────────────────────────────────

class LangChainSaveResultTool(BaseTool):
    """LangChain tool that stores the agent's final task result."""

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
            await self.data_client.submit_result(
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
    """LangChain tool that requests human intervention (HITL).

    Raises HumanInterveneRequired exception to halt agent execution and
    wait for human input, identical to the existing HITL mechanism in
    runtime_executor.py.
    """

    name: str = "human_intervene"
    description: str = (
        "Request human intervention. Use this when you need human input, "
        "approval, or clarification to proceed with the task."
    )
    args_schema: Type[BaseModel] = _HumanInterveneArgs

    comm_hub_client: Any = Field(exclude=True)
    data_client: Any = Field(exclude=True)
    session_id: str = Field(exclude=True)
    agent_type_id: str = Field(exclude=True, default="")

    class Config:
        arbitrary_types_allowed = True

    def _run(self, message: str, context: Optional[dict] = None) -> str:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._arun(message=message, context=context))
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    async def _arun(self, message: str, context: Optional[dict] = None) -> str:
        """Request HITL — marks session as waiting and raises HumanInterveneRequired."""
        try:
            # Import from existing HITL module to reuse the established exception
            from app.services.agents.runtime_executor import HumanInterveneRequired  # type: ignore
        except ImportError:
            # Fallback exception if import fails (e.g. in unit tests)
            class HumanInterveneRequired(Exception):  # type: ignore
                pass

        try:
            # Mark the session as waiting for human intervention
            await self.data_client.mark_session_waiting_for_human(
                session_id=self.session_id,
                message=message,
                context=context or {},
            )
        except Exception as exc:
            logger.error("Failed to mark session as waiting for human: %s", exc)

        raise HumanInterveneRequired(message)


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
