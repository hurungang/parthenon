"""Agent management API routers: AgentType and AgentInstance."""
import json
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import require_permission
from app.core.credential_vault import get_vault
from app.core.resource_types import RT_AGENT
from app.db.session import DbSession
from app.db.models.agents import (
    AgentInstance,
    AgentInstanceStatus,
    AgentMode,
    AgentSkillAssignment,
    AgentType,
)
from app.db.models.skills import Skill, Sop
from app.schemas.agents import AgentInstanceRead, AgentTypeCreate, AgentTypeRead, AgentTypeUpdate
from app.services.agents.instance_manager import AgentInstanceManager

logger = logging.getLogger(__name__)

AgentTypeRouter = APIRouter(prefix="/agents/types", tags=["Agents"])
AgentInstanceRouter = APIRouter(prefix="/agents/instances", tags=["Agents"])


# ── Agent Type Endpoints ───────────────────────────────────────────────────────

@AgentTypeRouter.get("", response_model=list[AgentTypeRead])
async def list_agent_types(
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[AgentType]:
    result = await db.execute(select(AgentType).order_by(AgentType.name))
    return list(result.scalars().all())


@AgentTypeRouter.post("", response_model=AgentTypeRead, status_code=status.HTTP_201_CREATED)
async def create_agent_type(
    body: AgentTypeCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "create")),
) -> AgentType:
    # Validate: sop-agent must have sop_id
    if body.mode == AgentMode.sop_agent and not body.sop_id:
        raise HTTPException(
            status_code=422, detail="sop-agent type requires a sop_id"
        )

    # Validate SOP exists
    if body.sop_id:
        sop = await db.get(Sop, body.sop_id)
        if not sop:
            raise HTTPException(status_code=422, detail=f"SOP {body.sop_id} not found")

    # Validate skill IDs (for skillful-agent)
    if body.skill_ids:
        for skill_id in body.skill_ids:
            skill = await db.get(Skill, skill_id)
            if not skill:
                raise HTTPException(
                    status_code=422, detail=f"Skill {skill_id} not found"
                )

    # Encrypt LLM credentials if provided
    encrypted_creds = None
    if body.llm_api_key:
        vault = get_vault()
        encrypted_creds = vault.encrypt(json.dumps({"api_key": body.llm_api_key}))

    agent_type = AgentType(
        name=body.name,
        description=body.description,
        mode=body.mode,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
        encrypted_llm_credentials=encrypted_creds,
        sop_id=body.sop_id,
        max_instances=body.max_instances,
        system_prompt=body.system_prompt,
    )
    db.add(agent_type)
    await db.flush()

    # Create skill assignments
    for skill_id in (body.skill_ids or []):
        assignment = AgentSkillAssignment(
            agent_type_id=agent_type.id, skill_id=skill_id
        )
        db.add(assignment)

    await db.flush()
    await db.refresh(agent_type)
    return agent_type


@AgentTypeRouter.get("/{type_id}", response_model=AgentTypeRead)
async def get_agent_type(
    type_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> AgentType:
    agent_type = await db.get(AgentType, type_id)
    if not agent_type:
        raise HTTPException(status_code=404, detail="Agent type not found")
    return agent_type


@AgentTypeRouter.put("/{type_id}", response_model=AgentTypeRead)
async def update_agent_type(
    type_id: uuid.UUID,
    body: AgentTypeUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> AgentType:
    agent_type = await db.get(AgentType, type_id)
    if not agent_type:
        raise HTTPException(status_code=404, detail="Agent type not found")

    update_data = body.model_dump(exclude_unset=True, exclude={"llm_api_key", "skill_ids"})
    for field, value in update_data.items():
        setattr(agent_type, field, value)

    if body.llm_api_key is not None:
        vault = get_vault()
        agent_type.encrypted_llm_credentials = vault.encrypt(
            json.dumps({"api_key": body.llm_api_key})
        )

    if body.skill_ids is not None:
        # Remove existing assignments
        existing = await db.execute(
            select(AgentSkillAssignment).where(
                AgentSkillAssignment.agent_type_id == type_id
            )
        )
        for assignment in existing.scalars().all():
            await db.delete(assignment)

        # Create new assignments
        for skill_id in body.skill_ids:
            skill = await db.get(Skill, skill_id)
            if not skill:
                raise HTTPException(status_code=422, detail=f"Skill {skill_id} not found")
            db.add(AgentSkillAssignment(agent_type_id=type_id, skill_id=skill_id))

    await db.flush()
    await db.refresh(agent_type)
    return agent_type


@AgentTypeRouter.delete("/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_type(
    type_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "delete")),
) -> None:
    agent_type = await db.get(AgentType, type_id)
    if not agent_type:
        raise HTTPException(status_code=404, detail="Agent type not found")
    await db.delete(agent_type)


@AgentTypeRouter.get("/{type_id}/instances", response_model=list[AgentInstanceRead])
async def list_agent_instances(
    type_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[AgentInstance]:
    result = await db.execute(
        select(AgentInstance)
        .where(AgentInstance.agent_type_id == type_id)
        .order_by(AgentInstance.created_at.desc())
    )
    return list(result.scalars().all())


# ── Agent Instance Endpoints ───────────────────────────────────────────────────

@AgentInstanceRouter.delete("/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def terminate_agent_instance(
    instance_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "execute")),
) -> None:
    manager = AgentInstanceManager()
    try:
        await manager.close(instance_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
