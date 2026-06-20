"""Communication Hub — Message Dispatch Endpoint.

Accepts dispatch requests from Control Center (mTLS-authenticated) and
publishes the message payload to the session's Redis pub/sub broker channel
so that connected WebSocket subscribers receive the agent result.

For conversation-scoped intervention signals (message_type "intervene_request"
with conversation_session_id), routes through the InterventionRouter to
deliver directly to the connected conversation WebSocket client instead of
the operator dashboard.

Route: POST /internal/dispatch

Security:
    ControlPlaneMiddleware (applied in CH main.py) validates the inbound
    X-Client-Certificate on all ``/internal/*`` paths and rejects any
    certificate that is not ``service:control-center``.

Phase 5.2 — Control Flow Implementation.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.services.comm_hub.broker import BrokerMessage, MessageBroker

logger = logging.getLogger(__name__)

dispatch_router = APIRouter(prefix="/internal", tags=["internal"])


def _is_non_conversational_intervention(content: dict[str, Any]) -> bool:
    """Check if an intervention payload targets a non-conversational agent job.

    Non-conversational (task) agent interventions are identified by the
    presence of ``parent_agent_job_id`` or ``agent_job_id`` in the payload
    AND the absence of ``conversation_session_id``.
    """
    has_agent_job_id = bool(
        content.get("parent_agent_job_id") or content.get("agent_job_id")
    )
    has_conv_session_id = bool(content.get("conversation_session_id"))
    return has_agent_job_id and not has_conv_session_id

_broker = MessageBroker()


class DispatchRequest(BaseModel):
    """Message dispatch payload sent by Control Center."""

    session_id: uuid.UUID
    message_type: str = "agent_result"
    content: dict[str, Any] | str
    metadata: dict[str, Any] | None = None


class DispatchResponse(BaseModel):
    """Dispatch confirmation response."""

    dispatched: bool
    channel: str
    subscribers: int


@dispatch_router.post(
    "/dispatch",
    response_model=DispatchResponse,
    summary="Dispatch message to broker channel (Control Center → Communication Hub)",
)
async def dispatch_message(body: DispatchRequest, request: Request) -> DispatchResponse:
    """Publish a message to the session's Redis pub/sub channel.

    Control Center calls this endpoint to deliver agent execution results
    (and other server-initiated messages) to connected WebSocket subscribers.

    For conversation-scoped intervention signals, routes through the
    InterventionRouter to deliver directly to the connected conversation
    WebSocket client.

    ``content`` may be either a plain string or a dict; dicts are
    JSON-serialised before insertion into the BrokerMessage so that existing
    WebSocket clients receive a consistently-formatted string payload.

    Authentication is enforced by ControlPlaneMiddleware — any request to
    ``/internal/*`` without a valid ``service:control-center`` certificate
    is rejected with 401 before this handler runs.

    Returns:
        ``{"dispatched": true, "channel": "...", "subscribers": N}``

    Raises:
        502 — Redis publish failed (broker unreachable).
    """
    content_dict: dict[str, Any] = (
        body.content
        if isinstance(body.content, dict)
        else (json.loads(body.content) if isinstance(body.content, str) else {})
    )

    # Route conversation-scoped intervention signals through InterventionRouter
    if body.message_type in ("intervene_request", "intervention"):
        interven_router = getattr(request.app.state, "intervention_router", None)
        if interven_router is not None:
            try:
                routed = await interven_router.route_intervention_signal(
                    session_id=str(body.session_id),
                    message_type=body.message_type,
                    content=content_dict,
                    metadata=body.metadata,
                )
                if routed:
                    channel = f"parthenon:session:{body.session_id}"
                    return DispatchResponse(
                        dispatched=True,
                        channel=f"{channel} (intervention-router)",
                        subscribers=1,
                    )
            except Exception as exc:
                logger.warning(
                    "Intervention routing failed for session %s: %s — "
                    "falling through to Redis broker",
                    body.session_id,
                    exc,
                )

        # Phase 2.3: Non-conversational intervention routing
        # When no conversation_session_id is present but the payload carries
        # parent_agent_job_id (non-conversational delegation context), route
        # through the Task Delegation Event Router to the execution log viewer.
        if _is_non_conversational_intervention(content_dict):
            tdr = getattr(request.app.state, "task_delegation_router", None)
            if tdr is not None:
                agent_job_id = (
                    content_dict.get("parent_agent_job_id")
                    or content_dict.get("agent_job_id")
                    or str(body.session_id)
                )
                try:
                    await tdr.push_intervene_request(
                        agent_job_id=agent_job_id,
                        payload=content_dict,
                    )
                    logger.info(
                        "Non-conversational intervention %s routed to "
                        "execution log for agent job %s",
                        content_dict.get("request_id", "unknown"),
                        agent_job_id,
                    )
                    return DispatchResponse(
                        dispatched=True,
                        channel=f"task-delegation:{agent_job_id}",
                        subscribers=1,
                    )
                except Exception as exc:
                    logger.warning(
                        "Task delegation router failed for session %s: %s — "
                        "falling through to Redis broker",
                        body.session_id,
                        exc,
                    )

    # Standard dispatch via Redis pub/sub
    content_str = (
        body.content
        if isinstance(body.content, str)
        else json.dumps(body.content)
    )

    message = BrokerMessage(
        session_id=str(body.session_id),
        sender_role="agent",
        content=content_str,
        metadata={"message_type": body.message_type, **(body.metadata or {})},
    )

    try:
        subscriber_count = await _broker.publish(message)
    except Exception as exc:
        logger.exception(
            "Failed to publish dispatch message for session %s: %s",
            body.session_id,
            exc,
        )
        raise HTTPException(
            status_code=502, detail=f"Broker publish failed: {exc}"
        ) from exc

    channel = f"parthenon:session:{body.session_id}"
    logger.info(
        "Dispatched %s to channel %s (%d subscribers)",
        body.message_type,
        channel,
        subscriber_count,
    )
    return DispatchResponse(
        dispatched=True,
        channel=channel,
        subscribers=subscriber_count,
    )
