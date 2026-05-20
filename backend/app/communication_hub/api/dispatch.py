"""Communication Hub — Message Dispatch Endpoint.

Accepts dispatch requests from Control Center (mTLS-authenticated) and
publishes the message payload to the session's Redis pub/sub broker channel
so that connected WebSocket subscribers receive the agent result.

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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.comm_hub.broker import BrokerMessage, MessageBroker

logger = logging.getLogger(__name__)

dispatch_router = APIRouter(prefix="/internal", tags=["internal"])

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
async def dispatch_message(body: DispatchRequest) -> DispatchResponse:
    """Publish a message to the session's Redis pub/sub channel.

    Control Center calls this endpoint to deliver agent execution results
    (and other server-initiated messages) to connected WebSocket subscribers.

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
