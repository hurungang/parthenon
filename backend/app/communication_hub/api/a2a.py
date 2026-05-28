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

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.agents import A2ARequest, A2AResponse
from app.services.comm_hub.broker import MessageBroker
from app.communication_hub.data_client import ControlCenterDataClient, ControlCenterDataError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/a2a", tags=["a2a"])


async def _wait_for_receiver_result(
    receiver_session_id: uuid.UUID,
    timeout_seconds: float,
    broker: MessageBroker | None = None,
) -> dict[str, Any]:
    """Wait for a receiver result message on Redis pub/sub until timeout.

    Only messages with metadata.message_type == "agent_result" are processed.
    """
    deadline = asyncio.get_running_loop().time() + max(0.5, timeout_seconds)
    active_broker = broker or MessageBroker()
    owns_broker = broker is None

    try:
        subscription = active_broker.subscribe(str(receiver_session_id))

        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return {
                    "status": "timeout",
                    "error": "Timed out waiting for receiver response",
                }

            try:
                message = await asyncio.wait_for(subscription.__anext__(), timeout=remaining)
            except asyncio.TimeoutError:
                return {
                    "status": "timeout",
                    "error": "Timed out waiting for receiver response",
                }
            except StopAsyncIteration:
                return {
                    "status": "timeout",
                    "error": "Timed out waiting for receiver response",
                }

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
        response_payload = await _wait_for_receiver_result(receiver_session_id, timeout_seconds)
    
    return A2AResponse(
        receiver_instance_id=receiver_instance_id,
        session_link_id=resolved_session_link_id,
        status="accepted",
        receiver_session_id=(str(receiver_session_id) if receiver_session_id else None),
        response_payload=response_payload,
    )


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
