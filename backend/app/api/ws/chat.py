"""WebSocket server — authenticates connections and bridges to MessageBroker."""
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from jose import JWTError

from app.core.oidc_client import OIDCError, get_oidc_client
from app.services.comm_hub.broker import BrokerMessage, MessageBroker

logger = logging.getLogger(__name__)

ws_router = APIRouter(tags=["WebSocket"])

_broker = MessageBroker()


class WebSocketServer:
    """
    WebSocket endpoint handler.
    Authenticates the connection via token query param, subscribes to
    the session channel in MessageBroker, and bridges bidirectional messages.
    """

    @staticmethod
    async def authenticate(websocket: WebSocket) -> dict[str, Any] | None:
        """Validate the token query param and return claims, or None if invalid."""
        token = websocket.query_params.get("token")
        if not token:
            return None
        try:
            client = get_oidc_client()
            claims = await client.validate_token(token)
            return claims
        except OIDCError:
            return None


@ws_router.websocket("/ws/sessions/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str) -> None:
    """
    Bidirectional WebSocket bridge between a client and the MessageBroker session channel.
    """
    server = WebSocketServer()
    claims = await server.authenticate(websocket)
    if not claims:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("WebSocket rejected: invalid token for session %s", session_id)
        return

    await websocket.accept()
    sender_role = claims.get("role", "user")
    subject = claims.get("sub", "unknown")
    logger.info(
        "WebSocket connected: session=%s subject=%s role=%s",
        session_id,
        subject,
        sender_role,
    )

    async def send_messages() -> None:
        """Subscribe and forward broker messages to the WebSocket client."""
        async for msg in _broker.subscribe(session_id):
            try:
                await websocket.send_json(msg.to_dict())
            except Exception:
                break

    import asyncio

    send_task = asyncio.create_task(send_messages())

    try:
        while True:
            data = await websocket.receive_text()
            # Publish inbound client messages to the broker
            message = BrokerMessage(
                session_id=session_id,
                sender_role=sender_role,
                content=data,
                metadata={"subject": subject},
            )
            await _broker.publish(message)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: session=%s", session_id)
    finally:
        send_task.cancel()
