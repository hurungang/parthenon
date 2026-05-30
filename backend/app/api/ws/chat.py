"""WebSocket server — authenticates connections, runs conversational agent, persists turns."""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.config import get_settings
from app.core.oidc_client import OIDCError, get_oidc_client
from app.core.ssl_context import get_ssl_context
from app.communication_hub.data_client import ControlCenterDataClient
from app.services.agents.model_binding import ModelBindingError

logger = logging.getLogger(__name__)

ws_router = APIRouter(tags=["WebSocket"])


def _build_chat_status_event(
    status_value: str,
    agent_type: str | None = None,
    tool_name: str | None = None,
    receiver_session_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, str]:
    """Build a normalized websocket status event payload for chat UI."""
    payload = {"status": status_value}
    if agent_type:
        payload["agent_type"] = agent_type
    if tool_name:
        payload["tool_name"] = tool_name
    if receiver_session_id:
        payload["receiver_session_id"] = receiver_session_id
    payload["timestamp"] = timestamp or datetime.now(timezone.utc).isoformat()
    return payload


class WebSocketServer:
    """
    WebSocket endpoint handler.
    Authenticates the connection via token query param and returns claims.
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
    Conversational agent WebSocket endpoint.

    Authenticates the connection, processes each inbound user message by:
      1. Persisting a ConversationTurn (user role)
      2. Building message history from all session turns
      3. Calling the configured LLM via ModelBindingLayer
      4. Persisting the agent response as a ConversationTurn
      5. Returning the agent response to the client

    Auto-names the session on the first message.
    """
    server = WebSocketServer()
    claims = await server.authenticate(websocket)
    if not claims:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("WebSocket rejected: invalid token for session %s", session_id)
        return

    await websocket.accept()
    subject = claims.get("sub", "unknown")
    logger.info(
        "WebSocket connected: session=%s subject=%s",
        session_id,
        subject,
    )

    try:
        conv_session_id = uuid.UUID(session_id)
    except ValueError:
        await websocket.close(code=4003, reason="Invalid session ID format")
        return

    message_count = 0

    try:
        while True:
            raw_text = await websocket.receive_text()

            # Parse JSON payload — client sends {"message": "..."}
            try:
                payload = json.loads(raw_text)
                user_message: str = (
                    payload.get("message", raw_text)
                    if isinstance(payload, dict)
                    else raw_text
                )
            except (json.JSONDecodeError, AttributeError):
                user_message = raw_text

            user_message = user_message.strip()
            if not user_message:
                continue

            message_count += 1
            logger.debug(
                "Conversation user prompt received: message=%d session=%s length=%d",
                message_count,
                session_id,
                len(user_message),
                extra={"data": {"user_prompt": user_message}},
            )

            await websocket.send_json(
                {
                    "type": "chat_status",
                    **_build_chat_status_event("thinking"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

            async def send_status_event(status_event: dict[str, str]) -> None:
                event_timestamp = status_event.get("timestamp")
                await websocket.send_json(
                    {
                        "type": "chat_status",
                        **status_event,
                        "timestamp": event_timestamp or datetime.now(timezone.utc).isoformat(),
                    }
                )

            # Persist turns, call LLM, optionally auto-name
            agent_reply, session_title, guardrail_usage, status_events = await _process_message(
                conv_session_id=conv_session_id,
                user_message=user_message,
                is_first_message=(message_count == 1),
                app=websocket.app,
                on_status_event=send_status_event,
            )

            # Send agent response back to client
            await websocket.send_json(
                {
                    "sender_role": "agent",
                    "content": agent_reply,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            logger.debug(
                "Conversation agent response sent: message=%d session=%s length=%d",
                message_count,
                session_id,
                len(agent_reply),
                extra={"data": {"agent_response": agent_reply}},
            )

            # Push auto-generated title on first message
            if session_title:
                await websocket.send_json(
                    {"type": "title_update", "title": session_title}
                )

            if guardrail_usage:
                await websocket.send_json(
                    {"type": "guardrail_update", "guardrail_usage": guardrail_usage}
                )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: session=%s", session_id)
    except Exception as exc:
        logger.error("WebSocket error for session %s: %s", session_id, exc, exc_info=True)


async def _process_message(
    conv_session_id: uuid.UUID,
    user_message: str,
    is_first_message: bool,
    app: Any,
    on_status_event: Callable[[dict[str, str]], Awaitable[None]] | None = None,
) -> tuple[str, str | None, dict[str, Any] | None, list[dict[str, str]]]:
    """
    Persist user turn, call LLM, persist agent turn, optionally auto-name the session.

    Returns:
        (agent_reply, session_title, guardrail_usage, status_events) — session_title is set only on the first message.
    """
    data_client: ControlCenterDataClient | None = getattr(app.state, "data_client", None)
    if data_client is None:
        logger.error("Control Center data client is unavailable in Communication Hub app state")
        return "Service temporarily unavailable. Please try again.", None, None, []

    guardrail_usage: dict[str, Any] | None = None
    status_events: list[dict[str, str]] = []

    prepared = await data_client.prepare_conversation_turn(conv_session_id, user_message)

    no_agent_message = prepared.get("no_agent_message")
    agent_type_id_raw = prepared.get("agent_type_id")
    prepared_messages = prepared.get("messages") or []

    if no_agent_message:
        agent_reply = str(no_agent_message)
    elif agent_type_id_raw:
        agent_reply, guardrail_usage, status_events = await _call_llm(
            conv_session_id=conv_session_id,
            agent_type_id=uuid.UUID(str(agent_type_id_raw)),
            messages=prepared_messages,
            app=app,
            on_status_event=on_status_event,
        )
    else:
        agent_reply = "No model is configured for this agent."

    appended = await data_client.append_conversation_turn(
        conv_session_id=conv_session_id,
        agent_reply=agent_reply,
        is_first_message=is_first_message,
        first_user_message=user_message if is_first_message else None,
        guardrail_usage=guardrail_usage,
        status_events=status_events,
    )
    session_title = appended.get("title")
    return agent_reply, (str(session_title) if session_title else None), guardrail_usage, status_events


async def _call_llm(
    conv_session_id: uuid.UUID,
    agent_type_id: uuid.UUID,
    messages: list[dict[str, str]],
    app: Any,
    on_status_event: Callable[[dict[str, str]], Awaitable[None]] | None = None,
) -> tuple[str, dict[str, Any] | None, list[dict[str, str]]]:
    """Execute one conversation turn using the deep agent framework.

    Returns the agent's text response, or a friendly error string on failure.
    """
    try:
        logger.debug(
            "Conversation message history assembled for session %s",
            conv_session_id,
            extra={
                "data": {
                    "message_count": len(messages),
                    "user_message_count": sum(1 for m in messages if m.get("role") == "user"),
                    "assistant_message_count": sum(1 for m in messages if m.get("role") == "assistant"),
                    "system_message_count": sum(1 for m in messages if m.get("role") == "system"),
                    "latest_user_prompt": next(
                        (
                            m.get("content")
                            for m in reversed(messages)
                            if m.get("role") == "user"
                        ),
                        None,
                    ),
                }
            },
        )

        logger.debug(
            "Delegating session %s conversation turn to Agent Runtime (%d messages, system=%s)",
            conv_session_id,
            len(messages),
            any(m.get("role") == "system" for m in messages),
        )
        return await _delegate_conversation_turn_to_agent_runtime(
            app=app,
            conv_session_id=conv_session_id,
            agent_type_id=agent_type_id,
            messages=messages,
            on_status_event=on_status_event,
        )

    except ModelBindingError as exc:
        logger.warning("Model binding error for session %s: %s", conv_session_id, exc)
        return (
            f"Unable to process your message: {exc}",
            None,
            [_build_chat_status_event("timeout_or_failed")],
        )
    except httpx.TimeoutException as exc:
        logger.warning("Conversation timeout for session %s: %s", conv_session_id, exc)
        return (
            "An error occurred while processing your message. Please try again.",
            None,
            [_build_chat_status_event("timeout_or_failed")],
        )
    except Exception as exc:
        logger.error(
            "LLM call error for session %s: %s",
            conv_session_id,
            exc,
            exc_info=True,
        )
        return (
            "An error occurred while processing your message. Please try again.",
            None,
            [_build_chat_status_event("timeout_or_failed")],
        )


async def _delegate_conversation_turn_to_agent_runtime(
    app: Any,
    conv_session_id: uuid.UUID,
    agent_type_id: uuid.UUID,
    messages: list[dict[str, str]],
    on_status_event: Callable[[dict[str, str]], Awaitable[None]] | None = None,
) -> tuple[str, dict[str, Any] | None, list[dict[str, str]]]:
    """Call Agent Runtime to execute one conversation turn.

    Communication Hub owns websocket transport but delegates execution logic to
    Agent Runtime so the runtime boundary remains explicit.
    """
    settings = get_settings()
    ar_base = (settings.agent_runtime_url or "http://localhost:8001").rstrip("/")
    endpoint = f"{ar_base}/internal/conversation/turn"
    configured_timeout = int(getattr(settings, "agent_question_timeout_seconds", 300))
    timeout_seconds = float(max(30, configured_timeout))

    payload = {
        "conv_session_id": str(conv_session_id),
        "agent_type_id": str(agent_type_id),
        "messages": messages,
        "stream_status_events": bool(on_status_event),
    }

    cert_manager = getattr(app.state, "certificate_manager", None)
    client_kwargs: dict[str, Any] = {
        "timeout": timeout_seconds,
        "verify": get_ssl_context(),
    }
    headers: dict[str, str] = {}

    if cert_manager and cert_manager.cert_path and cert_manager.key_path:
        if ar_base.startswith("https://"):
            client_kwargs["cert"] = (str(cert_manager.cert_path), str(cert_manager.key_path))
        else:
            from pathlib import Path

            cert_content = Path(cert_manager.cert_path).read_text()
            headers["X-Client-Certificate"] = cert_content.replace("\n", "\\n")

    async with httpx.AsyncClient(**client_kwargs) as client:
        if on_status_event is not None:
            status_events: list[dict[str, str]] = []
            final_response = ""
            final_guardrail_usage: dict[str, Any] | None = None

            async with client.stream("POST", endpoint, json=payload, headers=headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    chunk_type = chunk.get("type")
                    if chunk_type == "status_event":
                        item = chunk.get("event")
                        if not isinstance(item, dict):
                            continue
                        status_value = item.get("status")
                        if not isinstance(status_value, str) or not status_value:
                            continue
                        agent_type = item.get("agent_type")
                        tool_name = item.get("tool_name")
                        normalized = _build_chat_status_event(
                            status_value,
                            agent_type if isinstance(agent_type, str) and agent_type else None,
                            tool_name if isinstance(tool_name, str) and tool_name else None,
                            item.get("receiver_session_id")
                            if isinstance(item.get("receiver_session_id"), str)
                            and item.get("receiver_session_id")
                            else None,
                            item.get("timestamp")
                            if isinstance(item.get("timestamp"), str) and item.get("timestamp")
                            else None,
                        )
                        status_events.append(normalized)
                        await on_status_event(normalized)
                        continue

                    if chunk_type == "final":
                        final_response = str(chunk.get("response") or "")
                        guardrail_raw = chunk.get("guardrail_usage")
                        final_guardrail_usage = (
                            guardrail_raw if isinstance(guardrail_raw, dict) else None
                        )
                        break

                    if chunk_type == "error":
                        raise RuntimeError("Agent Runtime streaming error")

            return final_response, final_guardrail_usage, status_events

        response = await client.post(endpoint, json=payload, headers=headers)
        response.raise_for_status()
        body = response.json()
        status_events_raw = body.get("status_events")
        status_events: list[dict[str, str]] = []
        if isinstance(status_events_raw, list):
            for item in status_events_raw:
                if not isinstance(item, dict):
                    continue
                status_value = item.get("status")
                if not isinstance(status_value, str) or not status_value:
                    continue
                agent_type = item.get("agent_type")
                tool_name = item.get("tool_name")
                status_events.append(
                    _build_chat_status_event(
                        status_value,
                        agent_type if isinstance(agent_type, str) and agent_type else None,
                        tool_name if isinstance(tool_name, str) and tool_name else None,
                        item.get("receiver_session_id")
                        if isinstance(item.get("receiver_session_id"), str)
                        and item.get("receiver_session_id")
                        else None,
                    )
                )

        return str(body.get("response") or ""), body.get("guardrail_usage"), status_events


