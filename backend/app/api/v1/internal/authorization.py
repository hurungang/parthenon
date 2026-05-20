"""Internal authorization endpoint — service-to-service only.

Called by the Communication Hub to authorize tool calls and obtain the
identity token to use for tool execution.

Authentication: Internal service-to-service call.  In production this endpoint
should be network-isolated (not exposed to the public internet).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.api.deps import require_service_certificate
from app.db.session import DbSession
from app.schemas.certificates import (
    AuthorizeToolCallRequest,
    AuthorizeToolCallResponse,
)
from app.services.permission_resolution import PermissionResolutionService

logger = logging.getLogger(__name__)

InternalAuthorizationRouter = APIRouter(
    prefix="/internal/authorize",
    tags=["internal"],
)

_permission_service = PermissionResolutionService()


@InternalAuthorizationRouter.post(
    "/tool-call",
    response_model=AuthorizeToolCallResponse,
    dependencies=[Depends(require_service_certificate)],
)
async def authorize_tool_call_internal(
    request: AuthorizeToolCallRequest,
    db: DbSession,
) -> AuthorizeToolCallResponse:
    """Authorize a tool call and return identity token (internal service-to-service call).

    The Communication Hub calls this endpoint after certificate validation to:
    1. Check the agent has permission to call the requested tool
    2. Retrieve/refresh the agent identity token
    3. Return the token for use in the tool call

    Identity tokens returned here are NEVER forwarded to the Agent Runtime;
    they are used only within the Communication Hub for tool execution.
    """
    result = await _permission_service.resolve_permissions(
        certificate_serial_number=request.certificate_serial_number,
        tool_name=request.tool_name,
        db=db,
    )
    await db.commit()  # Persist any token refresh writes

    return AuthorizeToolCallResponse(
        authorized=result.authorized,
        identity_token=result.identity_token,
        identity_id=result.identity_id,
        agent_type_id=result.agent_type_id,
        reason=result.reason,
        required_permission=result.required_permission,
        agent_type=result.agent_type_name,
    )
