"""A2A (Agent-to-Agent) Communication Hub API.

Handles A2A requests from SopOrchestrator, resolving receiver agents,
provisioning dynamic receivers when needed, and managing session links.
"""
import asyncio
import json
from datetime import datetime, timezone
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.agents import A2ARequest, A2AResponse
from app.services.comm_hub.broker import MessageBroker
from app.communication_hub.data_client import ControlCenterDataClient, ControlCenterDataError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/a2a", tags=["a2a"])


async def _wait_for_receiver_result(
    receiver_session_id: uuid.UUID,
    timeout_seconds: float,
    broker: MessageBroker | None = None,
    data_client: Any | None = None,
) -> dict[str, Any]:
    """Wait for a receiver result message on Redis pub/sub until timeout.

    Only messages with metadata.message_type == "agent_result" are processed.
    When a data_client is provided, the session status is periodically checked
    and the deadline is extended while the session is ``waiting_for_human``,
    ensuring human-in-the-loop interventions do not trigger a timeout.
    """
    base_deadline = asyncio.get_running_loop().time() + max(0.5, timeout_seconds)
    deadline = base_deadline
    active_broker = broker or MessageBroker()
    owns_broker = broker is None
    status_check_interval = 5.0  # seconds between session status polls

    try:
        subscription = active_broker.subscribe(str(receiver_session_id))
        is_waiting = False
        _terminal_status: str | None = None

        while True:
            # Check session status if data_client is available
            prev_is_waiting = is_waiting
            is_waiting = False
            if data_client is not None:
                try:
                    session_data = await data_client.get_session(receiver_session_id)
                    if session_data:
                        status = session_data.get("status")
                        if status == "waiting_for_human":
                            is_waiting = True
                        elif status in ("completed", "failed", "terminated"):
                            # Bug #2: Don't return "expired" immediately — a result
                            # message may already be pending in Redis.  Defer the
                            # "expired" decision until the deadline fires.
                            _terminal_status = status
                except Exception:
                    pass

            # Bug #1: When transitioning OUT of waiting_for_human (e.g. human
            # responded and sub-agent resumed), extend the deadline so the poll
            # loop keeps waiting for the sub-agent's final result.
            if prev_is_waiting and not is_waiting:
                deadline = asyncio.get_running_loop().time() + max(timeout_seconds, 30.0)

            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0 and not is_waiting:
                # Bug #2: Only return "expired" after confirming no result message
                # arrived (deadline fired while session is in a terminal state).
                if _terminal_status:
                    return {
                        "status": "expired",
                        "error": f"Session {_terminal_status} before result received",
                    }
                return {
                    "status": "timeout",
                    "error": "Timed out waiting for receiver response",
                }

            poll_timeout = min(max(remaining, 5.0), status_check_interval) if is_waiting else min(remaining, status_check_interval)

            try:
                message = await asyncio.wait_for(subscription.__anext__(), timeout=poll_timeout)
            except asyncio.TimeoutError:
                continue
            except StopAsyncIteration:
                subscription = active_broker.subscribe(str(receiver_session_id))
                continue

            metadata = message.metadata if isinstance(message.metadata, dict) else {}
            if metadata.get("message_type") != "agent_result":
                continue

            content: Any = message.content
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    content = {"output_data": content}

            if isinstance(content, dict):
                payload_status = content.get("status")
                if payload_status == "completed":
                    return {
                        "status": "completed",
                        "output_data": content.get("output_data", {}),
                    }
                if payload_status == "failed":
                    return {
                        "status": "failed",
                        "error": content.get("error") or "Receiver session failed",
                        "output_data": content.get("output_data", {}),
                        "stop_category": content.get("stop_category"),
                        "stop_reason": content.get("stop_reason"),
                        "stop_details": content.get("stop_details"),
                    }
                if payload_status == "timeout":
                    return {
                        "status": "timeout",
                        "error": "Timed out waiting for receiver response",
                    }

                # Backward compatibility: plain output dict without status means success.
                return {
                    "status": "completed",
                    "output_data": content,
                }

            return {
                "status": "completed",
                "output_data": content,
            }
    finally:
        if owns_broker:
            await active_broker.close()


@router.post("/request", response_model=A2AResponse)
async def request_a2a(
    request: A2ARequest,
    http_request: Request,
) -> A2AResponse:
    """Handle A2A request from SopOrchestrator to delegate to another agent.
    
    This endpoint:
    1. Validates that target_agent_type_slug exists and is active.
    2. Checks permission (derived from SOP allowed_agent_type_slugs) — Phase 2.2.
    3. Attempts to resolve active receiver by agent type.
    4. If no active receiver: requests Agent Runtime Service to provision dynamic receiver.
    5. Creates and persists A2A session link.
    
    Args:
        request: A2ARequest with target slug, metadata, and payload.
        db: Database session.
    
    Returns:
        A2AResponse with receiver_instance_id and session_link_id.
    
    Raises:
        HTTPException: If target agent type not found (404), unauthorized (403),
                      or receiver provisioning fails (500).
    """
    data_client: ControlCenterDataClient | None = getattr(http_request.app.state, "data_client", None)
    if data_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Control Center data client is not initialized",
        )

    target_slug = request.target_agent_type_slug
    requester_instance_id = request.conversation_metadata.get(
        "requester_instance_id", f"requester_{uuid.uuid4()}"
    )
    requester_role_id = request.conversation_metadata.get("requester_role_id")
    if requester_role_id:
        try:
            uuid.UUID(str(requester_role_id))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid requester_role_id '{requester_role_id}'",
            ) from exc

    # Request preparation is fully delegated to Control Center (DB owner).
    session_link_id = request.conversation_metadata.get("session_link_id")
    conv_session_id_raw = request.conversation_metadata.get("conv_session_id")
    active_receiver_instance_id = request.conversation_metadata.get(
        "active_receiver_instance_id"
    )
    try:
        prepared = await data_client.prepare_a2a_request(
            target_agent_type_slug=target_slug,
            requester_instance_id=requester_instance_id,
            requester_role_id=str(requester_role_id) if requester_role_id else None,
            request_payload=request.request_payload,
            session_link_id=str(session_link_id) if session_link_id else None,
            active_receiver_instance_id=(
                str(active_receiver_instance_id) if active_receiver_instance_id else None
            ),
            conv_session_id=str(conv_session_id_raw) if conv_session_id_raw else None,
        )
    except ControlCenterDataError as exc:
        detail = str(exc)
        if "returned 404" in detail:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
        if "returned 403" in detail:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail) from exc
        if "returned 400" in detail:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail) from exc

    receiver_instance_id = str(prepared.get("receiver_instance_id"))
    resolved_session_link_id = str(prepared.get("session_link_id"))
    receiver_session_id_raw = prepared.get("receiver_session_id")
    receiver_session_id = uuid.UUID(str(receiver_session_id_raw)) if receiver_session_id_raw else None

    response_payload: dict[str, Any] | None = None
    wait_flag = bool(request.conversation_metadata.get("wait_for_response"))
    if wait_flag and receiver_session_id is not None:
        timeout_raw = request.conversation_metadata.get("wait_timeout_seconds", 20)
        try:
            timeout_seconds = float(timeout_raw)
        except (TypeError, ValueError):
            timeout_seconds = 20.0
        timeout_seconds = min(max(timeout_seconds, 1.0), 120.0)
        response_payload = await _wait_for_receiver_result(
            receiver_session_id, timeout_seconds, data_client=data_client,
        )
    
    return A2AResponse(
        receiver_instance_id=receiver_instance_id,
        session_link_id=resolved_session_link_id,
        status="accepted",
        receiver_session_id=(str(receiver_session_id) if receiver_session_id else None),
        response_payload=response_payload,
    )


@router.get("/wait/{receiver_session_id}")
async def wait_for_a2a_response(
    receiver_session_id: uuid.UUID,
    http_request: Request,
    timeout_seconds: float = Query(default=20.0, ge=1.0, le=120.0),
) -> dict[str, Any]:
    """Wait for a delegated receiver session result."""
    dc: ControlCenterDataClient | None = getattr(http_request.app.state, "data_client", None)
    return await _wait_for_receiver_result(receiver_session_id, timeout_seconds, data_client=dc)


@router.post("/disconnect/{session_link_id}")
async def disconnect_a2a(
    session_link_id: str,
    http_request: Request,
) -> dict[str, str]:
    """Handle A2A session disconnect and cleanup.
    
    This endpoint:
    1. Marks A2A session as completed.
    2. If receiver is dynamic, requests Agent Runtime Service to clean up.
    
    Args:
        session_link_id: The A2A session link ID.
        db: Database session.
    
    Returns:
        Status message.
    
    Raises:
        HTTPException: If session not found (404).
    """
    data_client: ControlCenterDataClient | None = getattr(http_request.app.state, "data_client", None)
    if data_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Control Center data client is not initialized",
        )

    try:
        result = await data_client.disconnect_a2a_session(session_link_id)
    except ControlCenterDataError as exc:
        detail = str(exc)
        if "returned 404" in detail:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail) from exc

    return {
        "status": str(result.get("status", "disconnected")),
        "session_link_id": str(result.get("session_link_id", session_link_id)),
    }
