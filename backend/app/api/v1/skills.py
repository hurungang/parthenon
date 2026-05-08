"""Skills API router — CRUD for skills with MCP tool binding validation."""
import json
import uuid
import logging
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.core.resource_types import RT_SKILL
from app.db.session import DbSession
from app.db.models.mcp_hub import McpTool
from app.db.models.skills import Skill, SkillToolBinding
from app.db.models.agents import AgentRoleSkill
from app.schemas.skills import SkillCreate, SkillDetailRead, SkillRead, SkillUpdate

logger = logging.getLogger(__name__)

SkillRouter = APIRouter(prefix="/skills", tags=["Skills"])


@dataclass
class _ToolRecord:
    name: str
    description: str | None
    input_schema: dict | None


def assemble_tool_section(tools: list[_ToolRecord]) -> str:
    """Build a read-only Tool Section markdown block from a list of tool records.

    Returns an empty string when no tools are provided.
    """
    if not tools:
        return ""

    lines: list[str] = ["## Tools"]
    for tool in tools:
        lines.append(f"\n### `{tool.name}`")
        if tool.description:
            lines.append(tool.description)
        if tool.input_schema:
            lines.append("\n**Input Schema:**")
            lines.append("```json")
            lines.append(json.dumps(tool.input_schema, indent=2))
            lines.append("```")
    return "\n".join(lines)


def _build_skill_read(skill: Skill) -> SkillRead:
    """Construct a SkillRead response with computed instructions_with_tools."""
    tool_records = [
        _ToolRecord(
            name=binding.tool.name,
            description=binding.tool.description,
            input_schema=binding.tool.input_schema,
        )
        for binding in sorted(skill.tool_bindings, key=lambda b: b.order)
        if binding.tool is not None
    ]
    tool_section = assemble_tool_section(tool_records)
    if tool_section:
        instructions_with_tools = (skill.instructions or "") + "\n\n" + tool_section
    else:
        instructions_with_tools = skill.instructions

    skill_read = SkillRead.model_validate(skill)
    skill_read.instructions_with_tools = instructions_with_tools
    return skill_read


def _build_skill_detail_read(skill: Skill) -> SkillDetailRead:
    """Construct a SkillDetailRead response with computed instructions_with_tools."""
    tool_records = [
        _ToolRecord(
            name=binding.tool.name,
            description=binding.tool.description,
            input_schema=binding.tool.input_schema,
        )
        for binding in sorted(skill.tool_bindings, key=lambda b: b.order)
        if binding.tool is not None
    ]
    tool_section = assemble_tool_section(tool_records)
    if tool_section:
        instructions_with_tools = (skill.instructions or "") + "\n\n" + tool_section
    else:
        instructions_with_tools = skill.instructions

    skill_detail = SkillDetailRead.model_validate(skill)
    skill_detail.instructions_with_tools = instructions_with_tools
    return skill_detail


_SKILL_LOAD_OPTIONS = [
    selectinload(Skill.tool_bindings).selectinload(SkillToolBinding.tool)
]


@SkillRouter.get("", response_model=list[SkillRead])
async def list_skills(
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "read")),
) -> list[SkillRead]:
    result = await db.execute(
        select(Skill).options(*_SKILL_LOAD_OPTIONS).order_by(Skill.name)
    )
    skills = list(result.scalars().all())
    return [_build_skill_read(s) for s in skills]


@SkillRouter.post("", response_model=SkillDetailRead, status_code=status.HTTP_201_CREATED)
async def create_skill(
    body: SkillCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "create")),
) -> SkillDetailRead:
    # Validate all tool IDs exist
    for tool_id in body.tool_ids:
        tool = await db.get(McpTool, tool_id)
        if not tool:
            raise HTTPException(
                status_code=422,
                detail=f"MCP tool with id {tool_id} not found",
            )

    skill = Skill(
        name=body.name,
        description=body.description,
        instructions=body.instructions,
    )
    db.add(skill)
    await db.flush()

    # Create tool bindings
    for order, tool_id in enumerate(body.tool_ids):
        binding = SkillToolBinding(
            skill_id=skill.id, tool_id=tool_id, order=order
        )
        db.add(binding)

    await db.flush()
    # Reload with eager tool_bindings + tool objects
    result = await db.execute(
        select(Skill).options(*_SKILL_LOAD_OPTIONS).where(Skill.id == skill.id)
    )
    return _build_skill_detail_read(result.scalar_one())


@SkillRouter.get("/{skill_id}", response_model=SkillDetailRead)
async def get_skill(
    skill_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "read")),
) -> SkillDetailRead:
    result = await db.execute(
        select(Skill).options(*_SKILL_LOAD_OPTIONS).where(Skill.id == skill_id)
    )
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return _build_skill_detail_read(skill)


@SkillRouter.put("/{skill_id}", response_model=SkillDetailRead)
async def update_skill(
    skill_id: uuid.UUID,
    body: SkillUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "update")),
) -> SkillDetailRead:
    result = await db.execute(
        select(Skill).options(*_SKILL_LOAD_OPTIONS).where(Skill.id == skill_id)
    )
    skill = result.scalar_one_or_none()
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
        await db.execute(delete(SkillToolBinding).where(SkillToolBinding.skill_id == skill_id))

        # Create new bindings
        for order, tool_id in enumerate(body.tool_ids):
            binding = SkillToolBinding(
                skill_id=skill.id, tool_id=tool_id, order=order
            )
            db.add(binding)

    await db.flush()
    # Reload with eager tool_bindings + tool objects
    result = await db.execute(
        select(Skill).options(*_SKILL_LOAD_OPTIONS).where(Skill.id == skill_id)
    )
    return _build_skill_detail_read(result.scalar_one())


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


@SkillRouter.get("/{skill_id}/roles", response_model=list[uuid.UUID])
async def get_skill_roles(
    skill_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "read")),
) -> list[uuid.UUID]:
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    result = await db.execute(
        select(AgentRoleSkill.role_id).where(AgentRoleSkill.skill_id == skill_id)
    )
    return list(result.scalars().all())


@SkillRouter.put("/{skill_id}/roles", response_model=list[uuid.UUID])
async def set_skill_roles(
    skill_id: uuid.UUID,
    body: dict,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "update")),
) -> list[uuid.UUID]:
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    role_ids: list[uuid.UUID] = [uuid.UUID(str(rid)) for rid in body.get("role_ids", [])]

    # Atomically replace membership
    await db.execute(delete(AgentRoleSkill).where(AgentRoleSkill.skill_id == skill_id))
    for role_id in role_ids:
        db.add(AgentRoleSkill(role_id=role_id, skill_id=skill_id))

    await db.flush()
    return role_ids
