"""Internal API Key Validation endpoint — mTLS-protected, called by Communication Hub.

Validates a hashed API key, resolves the bound agent identity + role, decrypts
the identity token, resolves the full permission set, logs usage, and returns
everything to the Communication Hub.

The identity token is held exclusively by CH — never exposed to external agents.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_service_certificate
from app.db.models.agent_api_key import ApiKeyStatus, ApiKeyUsageAction
from app.db.models.agents import AgentIdentity, AgentRole
from app.db.models.mcp_hub import McpTool
from app.db.models.skills import Skill, SkillToolBinding
from app.db.session import DbSession
from app.schemas.api_key import (
    ApiKeyValidateRequest,
    ApiKeyValidateResponse,
    SkillWithVersion,
    ToolDefinition,
)
from app.services.api_key_service import (
    create_api_key_usage_log,
    resolve_allowed_tools,
    resolve_identity_token,
    update_last_used_at,
    validate_api_key_from_hash,
    get_role_name,
)

logger = logging.getLogger(__name__)

InternalAuthRouter = APIRouter(
    prefix="/internal/auth",
    tags=["internal"],
)


async def _resolve_skills_for_role(
    role_id: uuid.UUID,
    db: DbSession,
    since: uuid.UUID | None = None,
) -> list[SkillWithVersion]:
    """Resolve all accessible skills and their tools for a given role.

    Reuses the existing skill→tool resolution from the skill service.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db.models.agents import AgentRoleSkill

    # Get skill IDs assigned to the role
    result = await db.execute(
        select(AgentRoleSkill.skill_id).where(AgentRoleSkill.role_id == role_id)
    )
    skill_ids = [row[0] for row in result.fetchall()]
    if not skill_ids:
        return []

    # Fetch skill records with tool bindings
    stmt = (
        select(Skill)
        .where(Skill.id.in_(skill_ids), Skill.is_active.is_(True))
        .options(
            selectinload(Skill.tool_bindings).selectinload(SkillToolBinding.tool)
        )
    )

    # Apply since filter if provided
    if since is not None:
        stmt = stmt.where(Skill.updated_at > since)

    result = await db.execute(stmt)
    skills = result.scalars().all()

    skill_versions: list[SkillWithVersion] = []
    for skill in skills:
        tools: list[ToolDefinition] = []
        for binding in skill.tool_bindings:
            tool = binding.tool
            if tool and tool.is_active:
                tools.append(
                    ToolDefinition(
                        tool_id=tool.id,
                        name=tool.name,
                        description=tool.description,
                        input_schema=tool.input_schema if hasattr(tool, 'input_schema') else None,
                        output_schema=tool.output_schema if hasattr(tool, 'output_schema') else None,
                    )
                )

        skill_versions.append(
            SkillWithVersion(
                skill_id=skill.id,
                name=skill.name,
                description=skill.description,
                instructions=skill.instructions,
                is_active=skill.is_active,
                is_system=skill.is_system,
                updated_at=skill.updated_at,
                tools=tools,
            )
        )

    return skill_versions


@InternalAuthRouter.post(
    "/validate-api-key",
    response_model=ApiKeyValidateResponse,
    dependencies=[Depends(require_service_certificate)],
)
async def validate_api_key_internal(
    request: ApiKeyValidateRequest,
    db: DbSession,
) -> ApiKeyValidateResponse:
    """Validate a hashed API key and return resolved identity + permissions.

    Called by Communication Hub over mTLS. The Communication Hub sends the
    SHA-256 hash of the key (never the raw key over the wire). Control Center
    validates the hash, resolves the bound identity → identity token and
    role → permission set, logs usage, and returns everything.

    The identity token is held exclusively by CH and never exposed externally.
    """
    if not request.key_hash:
        raise HTTPException(status_code=400, detail="key_hash is required")

    # 1. Validate the API key (hash lookup + active status check)
    api_key = await validate_api_key_from_hash(request.key_hash, db)
    if api_key is None:
        # Try finding if key exists but is revoked (for better logging)
        from sqlalchemy import select
        from app.db.models.agent_api_key import AgentApiKey
        existing = await db.execute(
            select(AgentApiKey).where(AgentApiKey.key_hash == request.key_hash)
        )
        existing_key = existing.scalar_one_or_none()
        if existing_key and existing_key.status == ApiKeyStatus.revoked:
            await create_api_key_usage_log(
                api_key_id=existing_key.id,
                action=ApiKeyUsageAction.validate,
                db=db,
                success=False,
            )
            await db.commit()
            raise HTTPException(status_code=401, detail="API key has been revoked")

        logger.warning("API key validation failed: hash not found")
        raise HTTPException(status_code=401, detail="Invalid API key")

    # 2. Resolve identity token
    try:
        identity_token = await resolve_identity_token(api_key.agent_identity_id, db)
    except ValueError as exc:
        logger.error(
            "Token resolution failed for API key %s (identity %s): %s",
            api_key.id,
            api_key.agent_identity_id,
            exc,
        )
        await create_api_key_usage_log(
            api_key_id=api_key.id,
            action=ApiKeyUsageAction.validate,
            db=db,
            success=False,
        )
        await db.commit()
        raise HTTPException(status_code=503, detail=f"Identity token resolution failed: {exc}")

    # 3. Resolve permissions from the bound role
    allowed_tools = await resolve_allowed_tools(api_key.agent_role_id, db)
    role_name = await get_role_name(api_key.agent_role_id, db)

    # 4. Resolve skills for the role (with optional since filter)
    skills = await _resolve_skills_for_role(
        api_key.agent_role_id,
        db,
        since=request.since,
    )

    # 5. Log successful usage + update last_used_at
    await create_api_key_usage_log(
        api_key_id=api_key.id,
        action=ApiKeyUsageAction.validate,
        db=db,
        success=True,
    )
    await update_last_used_at(api_key.id, db)
    await db.commit()

    logger.info(
        "API key validated successfully: key_id=%s identity=%s role=%s",
        api_key.id,
        api_key.agent_identity_id,
        api_key.agent_role_id,
    )

    return ApiKeyValidateResponse(
        valid=True,
        agent_identity_id=api_key.agent_identity_id,
        agent_role_id=api_key.agent_role_id,
        agent_role_name=role_name,
        identity_token=identity_token,
        permissions=sorted(allowed_tools),
        skills=skills,
        api_key_name=api_key.name,
    )
