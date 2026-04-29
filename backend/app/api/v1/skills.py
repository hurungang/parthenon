"""Skills API router — CRUD for skills with MCP tool binding validation."""
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.core.resource_types import RT_SKILL
from app.db.session import DbSession
from app.db.models.mcp_hub import McpTool
from app.db.models.skills import Skill, SkillToolBinding
from app.schemas.skills import SkillCreate, SkillRead, SkillUpdate

logger = logging.getLogger(__name__)

SkillRouter = APIRouter(prefix="/skills", tags=["Skills"])


@SkillRouter.get("", response_model=list[SkillRead])
async def list_skills(
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "read")),
) -> list[Skill]:
    result = await db.execute(select(Skill).order_by(Skill.name))
    return list(result.scalars().all())


@SkillRouter.post("", response_model=SkillRead, status_code=status.HTTP_201_CREATED)
async def create_skill(
    body: SkillCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "create")),
) -> Skill:
    # Validate all tool IDs exist
    for tool_id in body.tool_ids:
        tool = await db.get(McpTool, tool_id)
        if not tool:
            raise HTTPException(
                status_code=422,
                detail=f"MCP tool with id {tool_id} not found",
            )

    skill = Skill(name=body.name, description=body.description)
    db.add(skill)
    await db.flush()

    # Create tool bindings
    for order, tool_id in enumerate(body.tool_ids):
        binding = SkillToolBinding(
            skill_id=skill.id, tool_id=tool_id, order=order
        )
        db.add(binding)

    await db.flush()
    await db.refresh(skill)
    return skill


@SkillRouter.get("/{skill_id}", response_model=SkillRead)
async def get_skill(
    skill_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "read")),
) -> Skill:
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


@SkillRouter.put("/{skill_id}", response_model=SkillRead)
async def update_skill(
    skill_id: uuid.UUID,
    body: SkillUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "update")),
) -> Skill:
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    for field, value in body.model_dump(exclude_unset=True, exclude={"tool_ids"}).items():
        setattr(skill, field, value)

    if body.tool_ids is not None:
        # Validate new tool IDs
        for tool_id in body.tool_ids:
            tool = await db.get(McpTool, tool_id)
            if not tool:
                raise HTTPException(
                    status_code=422,
                    detail=f"MCP tool with id {tool_id} not found",
                )

        # Remove old bindings
        existing_bindings = await db.execute(
            select(SkillToolBinding).where(SkillToolBinding.skill_id == skill_id)
        )
        for binding in existing_bindings.scalars().all():
            await db.delete(binding)

        # Create new bindings
        for order, tool_id in enumerate(body.tool_ids):
            binding = SkillToolBinding(
                skill_id=skill.id, tool_id=tool_id, order=order
            )
            db.add(binding)

    await db.flush()
    await db.refresh(skill)
    return skill


@SkillRouter.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    skill_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "delete")),
) -> None:
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    await db.delete(skill)
