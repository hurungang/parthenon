"""Agent Client Admin CRUD endpoints — JWT-protected, admin-facing.

A client is an access grant bound to one agent type (input-interface only),
distinct from an API key (identity credential). Provides:
- List clients (optionally filtered by agent type)
- Create a client (secret or publishable; clear-text credential shown once)
- Rotate a client's credential
- Revoke a client (idempotent)
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.core.resource_types import RT_AGENT
from app.core.tenant_context import get_tenant_context
from app.db.models.agent_client import (
    AgentClient,
    AgentClientKeyType,
    AgentClientRateLimitWindow,
    AgentClientStatus,
)
from app.db.models.agents import AgentType
from app.db.session import DbSession
from app.schemas.agent_client import (
    AgentClientCreate,
    AgentClientCredentialResponse,
    AgentClientRead,
    AgentClientRevokeResponse,
    AgentClientStatusUpdate,
    AgentClientUpdate,
)
from app.services.agent_client_service import (
    check_duplicate_name,
    check_duplicate_slug,
    generate_client_key,
    slugify,
)

logger = logging.getLogger(__name__)

AdminAgentClientRouter = APIRouter(prefix="/clients", tags=["Agent Clients"])

_PERMISSION = require_permission(RT_AGENT, "manage")


def _to_read(client: AgentClient) -> AgentClientRead:
    return AgentClientRead(
        id=client.id,
        name=client.name,
        slug=client.slug,
        agent_type_id=client.agent_type_id,
        agent_type_name=client.agent_type.name if client.agent_type else None,
        key_type=client.key_type.value,
        key_prefix=client.key_prefix,
        status=client.status.value,
        tenant_slug=client.tenant.slug if client.tenant else None,
        white_label_theme=client.white_label_theme,
        allowed_origins=client.allowed_origins,
        rate_limit=client.rate_limit,
        rate_limit_window=client.rate_limit_window.value if client.rate_limit_window else None,
        created_at=client.created_at,
        last_used_at=client.last_used_at,
        expires_at=client.expires_at,
    )


def _credential_response(
    client: AgentClient, raw_key: str, agent_type_name: str
) -> AgentClientCredentialResponse:
    return AgentClientCredentialResponse(
        id=client.id,
        name=client.name,
        key_type=client.key_type.value,
        key_prefix=client.key_prefix,
        client_key=raw_key,
        agent_type_id=client.agent_type_id,
        agent_type_name=agent_type_name,
        created_at=client.created_at,
    )


@AdminAgentClientRouter.get(
    "",
    response_model=list[AgentClientRead],
    dependencies=[Depends(_PERMISSION)],
)
async def list_clients(
    db: DbSession,
    agent_type_id: uuid.UUID | None = Query(None, description="Filter by agent type"),
) -> list[AgentClientRead]:
    """List clients (metadata only — never the credential)."""
    stmt = (
        select(AgentClient)
        .options(selectinload(AgentClient.agent_type), selectinload(AgentClient.tenant))
        .order_by(AgentClient.created_at.desc())
    )
    if agent_type_id is not None:
        stmt = stmt.where(AgentClient.agent_type_id == agent_type_id)
    result = await db.execute(stmt)
    return [_to_read(c) for c in result.scalars().unique().all()]


@AdminAgentClientRouter.post(
    "",
    response_model=AgentClientCredentialResponse,
    status_code=201,
    dependencies=[Depends(_PERMISSION)],
)
async def create_client(
    body: AgentClientCreate,
    request: Request,
    db: DbSession,
) -> AgentClientCredentialResponse:
    """Create a client bound to one agent type.

    The clear-text credential is returned once and never stored. A
    ``publishable`` client is safe to embed in a browser (it only grants access
    to the agent type's input interface). The caller (frontend) is responsible
    for surfacing the soft "this exposes the agent type publicly" warning.
    """
    agent_type = await db.get(AgentType, body.agent_type_id)
    if agent_type is None:
        raise HTTPException(status_code=404, detail="Agent type not found")

    try:
        key_type = AgentClientKeyType(body.key_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="key_type must be 'secret' or 'publishable'")

    # Publishable (browser-facing) credentials must have an origin allowlist —
    # an empty allowlist would let anyone call the agent from anywhere.
    if key_type == AgentClientKeyType.publishable and not body.allowed_origins:
        raise HTTPException(
            status_code=400,
            detail="Publishable clients require at least one allowed origin.",
        )

    rate_window: AgentClientRateLimitWindow | None = None
    if body.rate_limit_window:
        try:
            rate_window = AgentClientRateLimitWindow(body.rate_limit_window)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="rate_limit_window must be per_minute, per_hour, or per_day",
            )

    tenant_context = get_tenant_context(request)
    tenant_id = tenant_context.tenant_id if tenant_context.is_set else None

    if await check_duplicate_name(body.name, db, tenant_id=tenant_id):
        raise HTTPException(
            status_code=409,
            detail="A client with this name already exists. Choose a different name.",
        )

    slug = body.slug or slugify(body.name)
    if await check_duplicate_slug(slug, db, tenant_id=tenant_id):
        raise HTTPException(
            status_code=409,
            detail="A client with this slug already exists. Choose a different slug.",
        )

    raw_key, key_hash, key_prefix = generate_client_key(key_type)

    client = AgentClient(
        tenant_id=tenant_id,
        name=body.name,
        slug=slug,
        agent_type_id=body.agent_type_id,
        key_type=key_type,
        key_hash=key_hash,
        key_prefix=key_prefix,
        status=AgentClientStatus.active,
        white_label_theme=body.white_label_theme,
        allowed_origins=body.allowed_origins,
        rate_limit=body.rate_limit,
        rate_limit_window=rate_window,
        expires_at=body.expires_at,
    )
    db.add(client)
    await db.commit()
    await db.refresh(client)

    logger.info(
        "Client created: id=%s name=%s key_type=%s agent_type=%s",
        client.id,
        client.name,
        client.key_type.value,
        client.agent_type_id,
    )
    return _credential_response(client, raw_key, agent_type.name)


@AdminAgentClientRouter.post(
    "/{client_id}/credential",
    response_model=AgentClientCredentialResponse,
    dependencies=[Depends(_PERMISSION)],
)
async def rotate_client_credential(
    client_id: uuid.UUID,
    db: DbSession,
) -> AgentClientCredentialResponse:
    """Rotate a client's credential (same key_type). Clear-text shown once."""
    client = await db.get(AgentClient, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    if client.status == AgentClientStatus.revoked:
        raise HTTPException(status_code=400, detail="Cannot rotate the credential of a revoked client")

    agent_type = await db.get(AgentType, client.agent_type_id)
    raw_key, key_hash, key_prefix = generate_client_key(client.key_type)
    client.key_hash = key_hash
    client.key_prefix = key_prefix
    await db.commit()
    await db.refresh(client)

    logger.info("Client credential rotated: id=%s name=%s", client.id, client.name)
    return _credential_response(client, raw_key, agent_type.name if agent_type else "")


@AdminAgentClientRouter.patch(
    "/{client_id}",
    response_model=AgentClientRead,
    dependencies=[Depends(_PERMISSION)],
)
async def update_client(
    client_id: uuid.UUID,
    body: AgentClientUpdate,
    db: DbSession,
) -> AgentClientRead:
    """Edit a client's allowed origins and rate limit (only these fields are mutable)."""
    client = await db.get(AgentClient, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    data = body.model_dump(exclude_unset=True)
    if "allowed_origins" in data:
        new_origins = data["allowed_origins"]
        if client.key_type == AgentClientKeyType.publishable and not new_origins:
            raise HTTPException(
                status_code=400,
                detail="Publishable clients require at least one allowed origin.",
            )
        client.allowed_origins = new_origins
    if "rate_limit" in data:
        client.rate_limit = data["rate_limit"]
    if "rate_limit_window" in data:
        window = data["rate_limit_window"]
        client.rate_limit_window = AgentClientRateLimitWindow(window) if window else None

    await db.commit()

    refreshed = (
        await db.execute(
            select(AgentClient)
            .options(selectinload(AgentClient.agent_type), selectinload(AgentClient.tenant))
            .where(AgentClient.id == client_id)
        )
    ).scalar_one()
    logger.info("Client updated (origins/rate): id=%s", client_id)
    return _to_read(refreshed)


@AdminAgentClientRouter.patch(
    "/{client_id}/status",
    response_model=AgentClientRead,
    dependencies=[Depends(_PERMISSION)],
)
async def update_client_status(
    client_id: uuid.UUID,
    body: AgentClientStatusUpdate,
    db: DbSession,
) -> AgentClientRead:
    """Activate or deactivate a client (reversible). Revoked clients cannot change."""
    result = await db.execute(
        select(AgentClient)
        .options(selectinload(AgentClient.agent_type), selectinload(AgentClient.tenant))
        .where(AgentClient.id == client_id)
    )
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    if client.status == AgentClientStatus.revoked:
        raise HTTPException(status_code=400, detail="Cannot change the status of a revoked client")

    client.status = AgentClientStatus(body.status)
    await db.commit()

    refreshed = (
        await db.execute(
            select(AgentClient)
            .options(selectinload(AgentClient.agent_type), selectinload(AgentClient.tenant))
            .where(AgentClient.id == client_id)
        )
    ).scalar_one()
    logger.info("Client status updated: id=%s status=%s", client_id, body.status)
    return _to_read(refreshed)


@AdminAgentClientRouter.delete(
    "/{client_id}",
    response_model=AgentClientRevokeResponse,
    dependencies=[Depends(_PERMISSION)],
)
async def delete_client(
    client_id: uuid.UUID,
    db: DbSession,
) -> AgentClientRevokeResponse:
    """Permanently remove a client (and its usage logs, cascade)."""
    client = await db.get(AgentClient, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    await db.delete(client)
    await db.commit()

    logger.info("Client deleted: id=%s name=%s", client_id, client.name)
    return AgentClientRevokeResponse(id=client_id, status="deleted", message="Client deleted")
