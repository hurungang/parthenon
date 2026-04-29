"""HTTP Gateway Transport and GatewayRouter — lifecycle endpoints over HTTP."""
import uuid
import logging

from fastapi import APIRouter, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.db.session import DbSession
from app.schemas.gateway import (
    GatewayAnswerPayload,
    GatewayAnswerResponse,
    GatewayCloseResponse,
    GatewayInitRequest,
    GatewayInitResponse,
    GatewayQuestionResponse,
    GatewayRequestPayload,
    GatewayRequestResponse,
)
from app.services.gateway.lifecycle_handler import GatewayLifecycleHandler

logger = logging.getLogger(__name__)

GatewayRouter = APIRouter(prefix="/gateway", tags=["Agent Gateway"])

_handler = GatewayLifecycleHandler()
_limiter = Limiter(key_func=get_remote_address)


@GatewayRouter.post("/{agent_type_id}/init", response_model=GatewayInitResponse)
@_limiter.limit("60/minute")
async def gateway_init(
    agent_type_id: uuid.UUID,
    request: Request,
    db: DbSession,
) -> GatewayInitResponse:
    """Initialize a new agent instance; returns session handle."""
    identity = getattr(request.state, "identity", {})
    initiator_subject = identity.get("sub") if identity else None

    try:
        result = await _handler.init(
            agent_type_id=agent_type_id,
            initiator_subject=initiator_subject,
            db=db,
        )
    except ValueError as exc:
        detail = str(exc)
        if "max_instances" in detail.lower() or "limit" in detail.lower():
            raise HTTPException(status_code=429, detail=detail)
        raise HTTPException(status_code=404, detail=detail)

    return GatewayInitResponse(**result)


@GatewayRouter.post("/{session_handle}/request", response_model=GatewayRequestResponse)
@_limiter.limit("60/minute")
async def gateway_request(
    session_handle: str,
    body: GatewayRequestPayload,
    request: Request,
    db: DbSession,
) -> GatewayRequestResponse:
    """Send a user prompt to the agent instance."""
    try:
        result = await _handler.request(
            session_handle=session_handle,
            prompt=body.prompt,
            context=body.context,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return GatewayRequestResponse(**result)


@GatewayRouter.get("/{session_handle}/question", response_model=GatewayQuestionResponse)
@_limiter.limit("60/minute")
async def gateway_question(
    session_handle: str,
    request: Request,
) -> GatewayQuestionResponse:
    """Long-poll for an agent question awaiting user input."""
    try:
        result = await _handler.get_question(session_handle, timeout=30.0)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return GatewayQuestionResponse(
        question=result.get("question"),
        instance_id=uuid.uuid4(),  # Placeholder — would normally come from instance lookup
        pending=result.get("pending", False),
    )


@GatewayRouter.post("/{session_handle}/answer", response_model=GatewayAnswerResponse)
@_limiter.limit("60/minute")
async def gateway_answer(
    session_handle: str,
    body: GatewayAnswerPayload,
    request: Request,
    db: DbSession,
) -> GatewayAnswerResponse:
    """Provide an answer to a pending agent question."""
    try:
        result = await _handler.answer(session_handle=session_handle, answer_text=body.answer)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    instance = await _handler._instance_manager.get_by_handle(session_handle, db)
    instance_id = instance.id if instance else uuid.uuid4()
    return GatewayAnswerResponse(acknowledged=result["acknowledged"], instance_id=instance_id)


@GatewayRouter.post("/{session_handle}/close", response_model=GatewayCloseResponse)
@_limiter.limit("60/minute")
async def gateway_close(
    session_handle: str,
    request: Request,
    db: DbSession,
) -> GatewayCloseResponse:
    """Close the agent instance and end the session."""
    try:
        result = await _handler.close(session_handle=session_handle, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return GatewayCloseResponse(
        closed=result["closed"],
        instance_id=uuid.UUID(result["instance_id"]),
    )
