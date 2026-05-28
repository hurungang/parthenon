"""Agent Runtime conversation execution endpoint.

Accepts websocket conversation-turn execution requests from Communication Hub.
Communication Hub remains transport-only and delegates all conversational
agent execution to Agent Runtime.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.services.agents.runtime_executor import AgentRuntimeExecutor

logger = logging.getLogger(__name__)

conversation_router = APIRouter(prefix="/internal/conversation", tags=["internal"])


class ConversationTurnRequest(BaseModel):
    """Payload for one conversation turn execution."""

    conv_session_id: uuid.UUID
    agent_type_id: uuid.UUID
    messages: list[dict[str, Any]]


class ConversationTurnResponse(BaseModel):
    """Final text response for one conversation turn."""

    response: str
    guardrail_usage: dict[str, Any] | None = None


@conversation_router.post("/turn", response_model=ConversationTurnResponse)
async def execute_conversation_turn(
    body: ConversationTurnRequest,
    request: Request,
) -> ConversationTurnResponse:
    """Execute one conversation turn in Agent Runtime.

    Security is enforced by Agent Runtime certificate middleware, which allows
    Communication Hub service certificates for this service boundary.
    """
    data_client = getattr(request.app.state, "data_client", None)
    if data_client is None:
        raise HTTPException(
            status_code=503,
            detail="Agent Runtime not ready; startup may be incomplete",
        )

    try:
        agent_context = await data_client.get_agent_context(body.agent_type_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Agent context not found: {exc}") from exc

    if not agent_context.get("is_active", False):
        raise HTTPException(status_code=400, detail="Agent type is not active")
    if not agent_context.get("identity_role_valid", False):
        raise HTTPException(status_code=403, detail="Agent identity is not assigned to role")

    model_id = agent_context.get("model_id")
    model_config_id = agent_context.get("model_config_id")
    if not model_id or not model_config_id:
        raise HTTPException(status_code=400, detail="Agent model is not configured")

    try:
        model_config = await data_client.get_model_config(uuid.UUID(str(model_config_id)))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to resolve model config: {exc}") from exc

    cert_manager = getattr(request.app.state, "certificate_manager", None)
    cert_path = str(cert_manager.cert_path) if cert_manager and cert_manager.cert_path else None
    key_path = str(cert_manager.key_path) if cert_manager and cert_manager.key_path else None

    executor = AgentRuntimeExecutor(data_client=data_client)
    response_text, guardrail_usage = await executor.execute_conversation_turn_from_context(
        agent_type_id=body.agent_type_id,
        agent_context=agent_context,
        model_config=model_config,
        messages=body.messages,
        conv_session_id=body.conv_session_id,
        cert_path=cert_path,
        key_path=key_path,
    )

    logger.info(
        "Conversation turn executed in Agent Runtime: session=%s agent_type=%s",
        body.conv_session_id,
        body.agent_type_id,
    )
    return ConversationTurnResponse(response=response_text, guardrail_usage=guardrail_usage)
