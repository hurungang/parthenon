"""API Key Admin CRUD endpoints — JWT-protected, admin-facing.

Provides:
- List all API keys with optional status filter
- Create a new API key (clear-text key shown once)
- Revoke an API key (idempotent)
- List agent identities with their available roles (for dropdowns)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.db.models.agent_api_key import AgentApiKey, ApiKeyStatus
from app.db.models.agents import AgentIdentity, AgentIdentityStatus, AgentRole, AgentRoleIdentity
from app.db.session import DbSession
from app.schemas.api_key import (
    ApiKeyCreate,
    ApiKeyCreateResponse,
    ApiKeyDeleteResponse,
    ApiKeyListItem,
    ApiKeyRevokeResponse,
    IdentityWithRoles,
    RoleItem,
)
from app.services.api_key_service import (
    check_duplicate_name,
    generate_api_key,
    get_identity_name,
    get_role_name,
)

logger = logging.getLogger(__name__)

AdminApiKeyRouter = APIRouter(
    prefix="/api-keys",
    tags=["API Keys"],
)

_ADMIN_PERMISSION = require_permission("agent::api_keys", "manage")


@AdminApiKeyRouter.get(
    "",
    response_model=list[ApiKeyListItem],
    dependencies=[Depends(_ADMIN_PERMISSION)],
)
async def list_api_keys(
    db: DbSession,
    status: str | None = Query(None, description="Filter by status: active or revoked"),
    search: str | None = Query(None, description="Search by name or identity name"),
) -> list[ApiKeyListItem]:
    """List all API keys with optional status filter and search.

    Returns key metadata only — never the key secret.
    """
    stmt = (
        select(AgentApiKey)
        .options(
            selectinload(AgentApiKey.identity),
            selectinload(AgentApiKey.role),
        )
    )

    if status:
        try:
            key_status = ApiKeyStatus(status)
            stmt = stmt.where(AgentApiKey.status == key_status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status filter: '{status}'. Must be 'active' or 'revoked'.",
            )

    result = await db.execute(stmt.order_by(AgentApiKey.created_at.desc()))
    keys = result.scalars().unique().all()

    identity_names: dict[uuid.UUID, str] = {}
    role_names: dict[uuid.UUID, str] = {}
    for key in keys:
        if key.agent_identity_id not in identity_names:
            identity_names[key.agent_identity_id] = (
                key.identity.name if key.identity else "unknown"
            )
        if key.agent_role_id not in role_names:
            role_names[key.agent_role_id] = (
                key.role.name if key.role else "unknown"
            )

    items: list[ApiKeyListItem] = []
    for key in keys:
        # Client-side search filter
        if search:
            search_lower = search.lower()
            name_match = search_lower in key.name.lower()
            identity_match = search_lower in identity_names.get(key.agent_identity_id, "").lower()
            role_match = search_lower in role_names.get(key.agent_role_id, "").lower()
            if not (name_match or identity_match or role_match):
                continue

        items.append(
            ApiKeyListItem(
                id=key.id,
                name=key.name,
                key_prefix=key.key_prefix,
                agent_identity_id=key.agent_identity_id,
                agent_identity_name=identity_names.get(key.agent_identity_id, "unknown"),
                agent_role_id=key.agent_role_id,
                agent_role_name=role_names.get(key.agent_role_id, "unknown"),
                status=key.status.value,
                created_at=key.created_at,
                last_used_at=key.last_used_at,
                expires_at=key.expires_at,
            )
        )

    return items


@AdminApiKeyRouter.post(
    "",
    response_model=ApiKeyCreateResponse,
    status_code=201,
    dependencies=[Depends(_ADMIN_PERMISSION)],
)
async def create_api_key(
    body: ApiKeyCreate,
    db: DbSession,
) -> ApiKeyCreateResponse:
    """Create a new API key bound to an agent identity and role.

    The clear-text key is returned once in the response — it is never stored
    and cannot be retrieved afterward.

    Enforces unique key names (any number of keys per identity-role pair).
    """
    # Validate agent identity exists and is active
    identity = await db.get(AgentIdentity, body.agent_identity_id)
    if not identity or identity.status != AgentIdentityStatus.active:
        raise HTTPException(
            status_code=404,
            detail="Agent identity not found or not active",
        )

    # Validate agent role exists
    role = await db.get(AgentRole, body.agent_role_id)
    if not role:
        raise HTTPException(
            status_code=404,
            detail="Agent role not found",
        )

    # Validate identity is assigned to the role
    result = await db.execute(
        select(AgentRoleIdentity).where(
            AgentRoleIdentity.identity_id == body.agent_identity_id,
            AgentRoleIdentity.role_id == body.agent_role_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="The selected identity is not assigned to the selected role. Assign the identity to the role first.",
        )

    # Enforce unique key names (any number of keys per identity-role pair)
    is_duplicate = await check_duplicate_name(body.name, db)
    if is_duplicate:
        raise HTTPException(
            status_code=409,
            detail="An API key with this name already exists. Choose a different name.",
        )

    # Generate key
    raw_key, key_hash, key_prefix = generate_api_key()

    # Create key record
    api_key = AgentApiKey(
        name=body.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        agent_identity_id=body.agent_identity_id,
        agent_role_id=body.agent_role_id,
        status=ApiKeyStatus.active,
        expires_at=body.expires_at,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    logger.info(
        "API key created: id=%s name=%s identity=%s role=%s",
        api_key.id,
        api_key.name,
        body.agent_identity_id,
        body.agent_role_id,
    )

    return ApiKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=key_prefix,
        api_key=raw_key,
        agent_identity_id=body.agent_identity_id,
        agent_identity_name=identity.name,
        agent_role_id=body.agent_role_id,
        agent_role_name=role.name,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
    )


@AdminApiKeyRouter.post(
    "/{key_id}/revoke",
    response_model=ApiKeyRevokeResponse,
    dependencies=[Depends(_ADMIN_PERMISSION)],
)
async def revoke_api_key(
    key_id: uuid.UUID,
    db: DbSession,
) -> ApiKeyRevokeResponse:
    """Revoke an API key.

    Idempotent — revoking an already-revoked key is a no-op success.
    Revoked keys immediately become unusable for authentication.
    """
    api_key = await db.get(AgentApiKey, key_id)
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    if api_key.status == ApiKeyStatus.revoked:
        logger.info("API key %s already revoked — idempotent no-op", key_id)
        return ApiKeyRevokeResponse(
            id=api_key.id,
            status="revoked",
            message="API key was already revoked",
        )

    api_key.status = ApiKeyStatus.revoked
    await db.commit()

    logger.info("API key revoked: id=%s name=%s", api_key.id, api_key.name)

    return ApiKeyRevokeResponse(
        id=api_key.id,
        status="revoked",
        message="API key revoked successfully",
    )


@AdminApiKeyRouter.delete(
    "/{key_id}",
    response_model=ApiKeyDeleteResponse,
    dependencies=[Depends(_ADMIN_PERMISSION)],
)
async def delete_api_key(
    key_id: uuid.UUID,
    db: DbSession,
) -> ApiKeyDeleteResponse:
    """Permanently delete an API key and its usage logs.

    Unlike revocation (which preserves the key and audit trail), deletion
    removes the key record entirely. Any usage logs cascade with the key.
    """
    api_key = await db.get(AgentApiKey, key_id)
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    await db.delete(api_key)
    await db.commit()

    logger.info("API key deleted: id=%s name=%s", key_id, api_key.name)

    return ApiKeyDeleteResponse(
        id=key_id,
        message="API key deleted successfully",
    )


@AdminApiKeyRouter.get(
    "/identities-with-roles",
    response_model=list[IdentityWithRoles],
    dependencies=[Depends(_ADMIN_PERMISSION)],
)
async def list_identities_with_roles(
    db: DbSession,
) -> list[IdentityWithRoles]:
    """List all agent identities with their available roles for dropdowns.

    Used by the frontend Create API Key dialog to populate identity and role
    selection dropdowns.
    """
    from sqlalchemy.orm import selectinload

    # Fetch active identities with their role assignments
    result = await db.execute(
        select(AgentIdentity)
        .where(AgentIdentity.status == AgentIdentityStatus.active)
        .options(selectinload(AgentIdentity.role_assignments))
        .order_by(AgentIdentity.name)
    )
    identities = result.scalars().unique().all()

    # Fetch all roles for name lookup
    all_roles_result = await db.execute(select(AgentRole).order_by(AgentRole.name))
    all_roles = {r.id: r for r in all_roles_result.scalars().all()}

    items: list[IdentityWithRoles] = []
    for identity in identities:
        roles: list[RoleItem] = []
        for assignment in identity.role_assignments:
            role = all_roles.get(assignment.role_id)
            if role:
                roles.append(RoleItem(role_id=role.id, role_name=role.name))

        items.append(
            IdentityWithRoles(
                identity_id=identity.id,
                identity_name=identity.name,
                roles=roles,
            )
        )

    return items
