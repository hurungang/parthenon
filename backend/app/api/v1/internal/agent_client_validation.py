"""Internal Agent Client Validation endpoint — mTLS-protected, called by Communication Hub.

Validates a hashed client credential, resolves the target agent type + config,
logs usage, and returns everything to the Communication Hub.

A client is NOT an identity: the response carries NO agent identity token. The
agent type runs with its own identity + role exactly as configured.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import require_service_certificate
from app.db.models.agent_client import AgentClientAction, AgentClientStatus
from app.db.models.agents import AgentInputType, AgentType
from app.db.models.tenant import Tenant
from app.db.session import DbSession
from app.schemas.agent_client import ClientValidateRequest, ClientValidateResponse
from app.services.agent_client_service import (
    create_client_usage_log,
    is_client_expired,
    update_last_used_at,
    validate_client_from_hash,
)

logger = logging.getLogger(__name__)

InternalAgentClientRouter = APIRouter(prefix="/internal/clients", tags=["internal"])


@InternalAgentClientRouter.post(
    "/validate",
    response_model=ClientValidateResponse,
    dependencies=[Depends(require_service_certificate)],
)
async def validate_client_internal(
    request: ClientValidateRequest,
    db: DbSession,
) -> ClientValidateResponse:
    """Validate a hashed client credential and return the resolved agent type + config.

    Called by Communication Hub over mTLS. CH sends the SHA-256 hash of the
    client credential (never the raw value). CC validates, resolves the target
    agent type + exposure config, audits the attempt, and returns the context.
    """
    if not request.key_hash:
        raise HTTPException(status_code=400, detail="key_hash is required")

    client = await validate_client_from_hash(request.key_hash, db)
    if client is None:
        existing = await db.execute(
            select(AgentClient).where(AgentClient.key_hash == request.key_hash)
        )
        existing_client = existing.scalar_one_or_none()
        if existing_client and existing_client.status == AgentClientStatus.revoked:
            await create_client_usage_log(
                client_id=existing_client.id,
                action=AgentClientAction.submit_request,
                db=db,
                success=False,
            )
            await db.commit()
            raise HTTPException(status_code=401, detail="Client credential has been revoked")
        logger.warning("Client validation failed: hash not found")
        raise HTTPException(status_code=401, detail="Invalid client credential")

    if is_client_expired(client):
        await create_client_usage_log(
            client_id=client.id,
            action=AgentClientAction.submit_request,
            db=db,
            success=False,
        )
        await db.commit()
        raise HTTPException(status_code=401, detail="Client credential has expired")

    agent_type = await db.get(AgentType, client.agent_type_id)
    if agent_type is None:
        raise HTTPException(status_code=401, detail="Target agent type not found")

    # Audit the invocation. The action is derived from the agent type's input
    # mode (a client can only ever invoke one surface of one agent type).
    action = (
        AgentClientAction.conversation_turn
        if agent_type.input_type == AgentInputType.conversation
        else AgentClientAction.submit_request
    )
    await create_client_usage_log(
        client_id=client.id, action=action, db=db, success=True
    )
    await update_last_used_at(client.id, db)
    await db.commit()

    # Multi-tenancy: sign the client's tenant context so CH can forward it
    # verbatim (never re-signed) on this invocation's internal CC calls.
    tenant_id = client.tenant_id
    tenant_headers: dict[str, str] | None = None
    tenant_slug: str | None = None
    tenant_name: str | None = None
    if tenant_id is not None:
        tenant_row = (
            await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if tenant_row is not None:
            from app.core.tenant_context import TenantContext
            from app.core.tenant_signature import build_tenant_signature_headers

            tenant_slug = tenant_row.slug
            tenant_name = tenant_row.name
            tenant_headers = build_tenant_signature_headers(
                TenantContext(
                    tenant_id=tenant_row.id,
                    slug=tenant_row.slug,
                    name=tenant_row.name,
                    is_system_tenant=tenant_row.is_system_tenant,
                )
            )

    logger.info(
        "Client validated: client_id=%s name=%s agent_type=%s key_type=%s",
        client.id,
        client.name,
        client.agent_type_id,
        client.key_type.value,
    )

    return ClientValidateResponse(
        valid=True,
        client_id=client.id,
        client_name=client.name,
        agent_type_id=client.agent_type_id,
        agent_type_name=agent_type.name,
        agent_type_input_type=agent_type.input_type.value,
        agent_type_input_schema=agent_type.input_schema,
        key_type=client.key_type.value,
        white_label_theme=client.white_label_theme,
        allowed_origins=client.allowed_origins,
        rate_limit=client.rate_limit,
        rate_limit_window=(
            client.rate_limit_window.value if client.rate_limit_window else None
        ),
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        tenant_name=tenant_name,
        tenant_headers=tenant_headers,
    )
