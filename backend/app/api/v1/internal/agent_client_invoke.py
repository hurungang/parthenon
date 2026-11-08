"""Internal Agent Client Invoke endpoint — mTLS-protected, called by Communication Hub.

Enqueues an AgentJob for a client-invoked agent type and triggers execution via
Communication Hub → Agent Runtime. Returns the session id (the platform executes
agents asynchronously; the caller polls the session for the result).

The agent type runs with its own identity + role exactly as configured — the
client is not an identity and contributes nothing to the execution identity.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import require_service_certificate
from app.db.models.agents import AgentType
from app.db.session import DbSession
from app.services.agents.session_service import AgentSessionService

logger = logging.getLogger(__name__)

InternalAgentClientInvokeRouter = APIRouter(prefix="/internal/clients", tags=["internal"])

_session_service = AgentSessionService()


class ClientInvokeRequest(BaseModel):
    """Request from CH to invoke a client's agent type."""

    agent_type_id: uuid.UUID
    input_data: dict[str, Any] = Field(default_factory=dict)
    # Client invocation provenance (forwarded by CH after credential
    # validation) — lets the runtime monitor attribute the trigger.
    client_id: uuid.UUID | None = None


class ClientInvokeResponse(BaseModel):
    """Response with the enqueued execution session id."""

    session_id: uuid.UUID
    status: str


class ClientSessionStatusResponse(BaseModel):
    """Current status/output of a client-invoked execution session."""

    session_id: uuid.UUID
    status: str
    output_data: Any | None = None
    error_message: str | None = None
    conversation_history: Any | None = None


class ClientConversationCreateRequest(BaseModel):
    """Create a stateful conversation session for a client-invoked agent type."""

    agent_type_id: uuid.UUID
    # Client invocation provenance (forwarded by CH after credential
    # validation) — lets the runtime monitor attribute the trigger.
    client_id: uuid.UUID | None = None


class ClientConversationCreateResponse(BaseModel):
    conversation_id: uuid.UUID


class ClientConversationEndResponse(BaseModel):
    conversation_id: uuid.UUID
    status: str


@InternalAgentClientInvokeRouter.post(
    "/invoke",
    response_model=ClientInvokeResponse,
    dependencies=[Depends(require_service_certificate)],
)
async def invoke_client_agent(
    body: ClientInvokeRequest,
    request: Request,
    db: DbSession,
) -> ClientInvokeResponse:
    """Enqueue and trigger an agent execution on behalf of a validated client."""
    agent_type = await db.get(AgentType, body.agent_type_id)
    if agent_type is None:
        raise HTTPException(status_code=404, detail="Agent type not found")

    # Resolve the tenant from the CH-forwarded signed headers (fail closed).
    from app.core.tenant_signature import (
        TenantSignatureError,
        verify_request_tenant_context,
    )

    try:
        tenant_context = verify_request_tenant_context(request.headers)
    except TenantSignatureError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid tenant context: {exc}")

    tenant_id = tenant_context.tenant_id if tenant_context else None

    job = await _session_service.enqueue(
        agent_type_id=body.agent_type_id,
        input_data=body.input_data,
        user_id=None,
        db=db,
        tenant_id=tenant_id,
        client_id=body.client_id,
    )
    await db.commit()

    from app.services.control_center.comm_hub_client import (
        CommunicationHubClient,
        CommunicationHubClientError,
    )

    try:
        result = await CommunicationHubClient().trigger_execution(
            session_id=job.id,
            agent_type_id=body.agent_type_id,
            input_data=body.input_data,
            tenant_context=tenant_context,
        )
    except CommunicationHubClientError as exc:
        logger.error("Failed to trigger client-invoked execution for job %s: %s", job.id, exc)
        raise HTTPException(
            status_code=502, detail=f"Failed to trigger agent execution: {exc}"
        )

    logger.info(
        "Client-invoked execution enqueued: session=%s agent_type=%s status=%s",
        job.id,
        body.agent_type_id,
        result.get("status"),
    )
    return ClientInvokeResponse(session_id=job.id, status=result.get("status", "queued"))


@InternalAgentClientInvokeRouter.get(
    "/session/{session_id}",
    response_model=ClientSessionStatusResponse,
    dependencies=[Depends(require_service_certificate)],
)
async def get_client_session(
    session_id: uuid.UUID,
    db: DbSession,
) -> ClientSessionStatusResponse:
    """Return the current status/output of a client-invoked execution session."""
    from app.db.models.agents import AgentJob

    job = await db.get(AgentJob, session_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return ClientSessionStatusResponse(
        session_id=job.id,
        status=job.status.value,
        output_data=job.output_data,
        error_message=job.error_message,
        conversation_history=job.conversation_history,
    )


@InternalAgentClientInvokeRouter.post(
    "/conversations",
    response_model=ClientConversationCreateResponse,
    dependencies=[Depends(require_service_certificate)],
)
async def create_client_conversation(
    body: ClientConversationCreateRequest,
    request: Request,
    db: DbSession,
) -> ClientConversationCreateResponse:
    """Create a stateful conversation session for a client-invoked agent type."""
    agent_type = await db.get(AgentType, body.agent_type_id)
    if agent_type is None:
        raise HTTPException(status_code=404, detail="Agent type not found")

    from app.core.tenant_signature import (
        TenantSignatureError,
        verify_request_tenant_context,
    )

    try:
        tenant_context = verify_request_tenant_context(request.headers)
    except TenantSignatureError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid tenant context: {exc}")
    tenant_id = tenant_context.tenant_id if tenant_context else None

    from app.db.models.conversations import ConversationSession, ConversationStatus

    conv = ConversationSession(
        tenant_id=tenant_id,
        agent_type_id=body.agent_type_id,
        triggered_by_client_id=body.client_id,
        channel="integration",
        status=ConversationStatus.active,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    logger.info(
        "Client conversation created: id=%s agent_type=%s", conv.id, body.agent_type_id
    )
    return ClientConversationCreateResponse(conversation_id=conv.id)


@InternalAgentClientInvokeRouter.post(
    "/conversations/{conversation_id}/end",
    response_model=ClientConversationEndResponse,
    dependencies=[Depends(require_service_certificate)],
)
async def end_client_conversation(
    conversation_id: uuid.UUID,
    db: DbSession,
) -> ClientConversationEndResponse:
    """Close a stateful conversation session."""
    from datetime import datetime, timezone

    from app.db.models.conversations import ConversationSession, ConversationStatus

    conv = await db.get(ConversationSession, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv.status = ConversationStatus.closed
    conv.closed_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("Client conversation ended: id=%s", conversation_id)
    return ClientConversationEndResponse(conversation_id=conv.id, status="closed")
