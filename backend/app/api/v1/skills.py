"""Skills API router — CRUD for skills with MCP tool binding validation."""
import json
import uuid
import logging
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.api.v1.mcp_hub import (
    SYSTEM_TOOL_IDS,
)
from app.core.resource_types import RT_AGENT_SKILLS
from app.db.session import DbSession
from app.db.models.mcp_hub import McpTool
from app.db.models.skills import Skill, SkillToolBinding
from app.schemas.skills import SkillCreate, SkillDetailRead, SkillRead, SkillUpdate
from app.db.models.agents import AgentRoleSkill
from app.schemas.skills import SkillCreate, SkillDetailRead, SkillRead, SkillUpdate
from app.schemas.skills import (
    SkillWorkflowGenerateRequest,
    SkillWorkflowGenerateResponse,
    SkillWorkflowPreviewRequest,
    SkillWorkflowPreviewResponse,
)
from app.services.agents.workflow_authoring_service import (
    WorkflowAuthoringError,
    build_skill_instruction_file,
    generate_workflow_text,
    resolve_model_config_for_generation,
)
from app.services.agents.workflow_generation_settings import get_workflow_generation_model_id
from app.services.agents.tool_naming import build_tool_name, parse_tool_name

logger = logging.getLogger(__name__)

SkillRouter = APIRouter(prefix="/skills", tags=["Skills"])


@dataclass
class _ToolRecord:
    name: str
    description: str | None
    input_schema: dict | None


def _get_system_tool_record(tool_id: uuid.UUID) -> _ToolRecord | None:
    """Return a _ToolRecord for a system tool ID, or None if not a system tool.

    Data is derived from SystemToolRegistry — no hardcoded tool data here.
    """
    from app.services.agents.system_tool_registry import SystemToolRegistry
    for entry in SystemToolRegistry.get_mcp_hub_entries():
        if entry["id"] == tool_id:
            return _ToolRecord(
                name=entry["name"],
                description=entry["description"],
                input_schema=entry["input_schema"],
            )
    return None


def _canonicalize_mcp_tool_name(name: str, server_slug: str | None, original_name: str | None) -> str:
    """Return canonical ``server____tool`` for MCP tool identifiers."""
    if server_slug and isinstance(original_name, str) and original_name:
        return build_tool_name(server_slug, original_name)

    try:
        parsed_server, parsed_tool = parse_tool_name(name)
        return build_tool_name(parsed_server, parsed_tool)
    except ValueError:
        if "/" in name:
            parsed_server, parsed_tool = name.split("/", 1)
            return build_tool_name(parsed_server, parsed_tool)
        return name


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
    tool_records: list[_ToolRecord] = []
    for binding in sorted(skill.tool_bindings, key=lambda b: b.order):
        # Prefer canonical system tool definitions so generated references always
        # include full schemas, even if DB-seeded rows have partial metadata.
        system_tool = _get_system_tool_record(binding.tool_id)
        if system_tool:
            tool_records.append(system_tool)
        elif binding.tool is not None:
            # Regular MCP tool from database
            tool_records.append(
                _ToolRecord(
                    name=_canonicalize_mcp_tool_name(
                        binding.tool.name,
                        None,
                        binding.tool.original_name,
                    ),
                    description=binding.tool.description,
                    input_schema=binding.tool.input_schema,
                )
            )
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
    tool_records: list[_ToolRecord] = []
    for binding in sorted(skill.tool_bindings, key=lambda b: b.order):
        # Prefer canonical system tool definitions so generated references always
        # include full schemas, even if DB-seeded rows have partial metadata.
        system_tool = _get_system_tool_record(binding.tool_id)
        if system_tool:
            tool_records.append(system_tool)
        elif binding.tool is not None:
            # Regular MCP tool from database
            tool_records.append(
                _ToolRecord(
                    name=_canonicalize_mcp_tool_name(
                        binding.tool.name,
                        None,
                        binding.tool.original_name,
                    ),
                    description=binding.tool.description,
                    input_schema=binding.tool.input_schema,
                )
            )
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


def _require_workflow_model_id() -> str:
    model_id = get_workflow_generation_model_id()
    if not model_id:
        raise HTTPException(
            status_code=422,
            detail="Workflow generation model is not configured. Configure it in system settings.",
        )
    return model_id


@SkillRouter.get("", response_model=list[SkillRead])
async def list_skills(
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SKILLS, "read")),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[SkillRead]:
    result = await db.execute(
        select(Skill)
        .options(*_SKILL_LOAD_OPTIONS)
        .order_by(Skill.name)
        .offset(offset)
        .limit(limit)
    )
    skills = list(result.scalars().all())
    return [_build_skill_read(s) for s in skills]


@SkillRouter.post("", response_model=SkillDetailRead, status_code=status.HTTP_201_CREATED)
async def create_skill(
    body: SkillCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SKILLS, "create")),
) -> SkillDetailRead:
    # Validate all tool IDs exist (skip system tools)
    for tool_id in body.tool_ids:
        # System tools are virtual and don't exist in database
        if tool_id in SYSTEM_TOOL_IDS:
            continue
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
    _: dict = Depends(require_permission(RT_AGENT_SKILLS, "read")),
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
    _: dict = Depends(require_permission(RT_AGENT_SKILLS, "update")),
) -> SkillDetailRead:
    result = await db.execute(
        select(Skill).options(*_SKILL_LOAD_OPTIONS).where(Skill.id == skill_id)
    )
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.is_system:
        raise HTTPException(status_code=403, detail="System skills cannot be modified")

    for field, value in body.model_dump(exclude_unset=True, exclude={"tool_ids"}).items():
        setattr(skill, field, value)

    if body.tool_ids is not None:
        # Validate new tool IDs (skip system tools)
        for tool_id in body.tool_ids:
            # System tools are virtual and don't exist in database
            if tool_id in SYSTEM_TOOL_IDS:
                continue
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


@SkillRouter.post("/workflow/generate", response_model=SkillWorkflowGenerateResponse)
async def generate_skill_workflow(
    body: SkillWorkflowGenerateRequest,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SKILLS, "update")),
) -> SkillWorkflowGenerateResponse:
    if not body.description.strip():
        raise HTTPException(status_code=422, detail="Description is required to generate workflow")
    if not body.selected_tools:
        raise HTTPException(status_code=422, detail="Select at least one tool to generate workflow")

    model_id = _require_workflow_model_id()
    try:
        # Ensure the selected model points to a valid configured provider.
        await resolve_model_config_for_generation(model_id, db)

        tool_lines = [
            f"- {tool.name}: {(tool.description or 'No description').strip()}"
            for tool in body.selected_tools
        ]
        nl = "\n"
        user_prompt = (
            "Business description:\n"
            f"{body.description.strip()}\n\n"
            "Selected tools:\n"
            f"{nl.join(tool_lines)}\n\n"
            "Write a concise execution workflow that references the selected tools."
        )
        workflow = await generate_workflow_text(
            model_id=model_id,
            system_prompt=(
                "You author SOP/Skill workflows for enterprise agents. "
                "When referencing skills, use their name directly (e.g. my-skill-name). Skill names are already in slug format. "
                "Respond with workflow text only. Do not include markdown code fences."
            ),
            user_prompt=user_prompt,
            db=db,
        )
    except (WorkflowAuthoringError, Exception) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return SkillWorkflowGenerateResponse(workflow=workflow, model_id=model_id)


@SkillRouter.post("/workflow/preview", response_model=SkillWorkflowPreviewResponse)
async def preview_skill_workflow(
    body: SkillWorkflowPreviewRequest,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SKILLS, "read")),
) -> SkillWorkflowPreviewResponse:
    model_id = _require_workflow_model_id()

    # Validate model selection is resolvable and not stale.
    try:
        await resolve_model_config_for_generation(model_id, db)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    selected_tools = [tool.model_dump() for tool in body.selected_tools]
    instruction_file = build_skill_instruction_file(
        workflow=body.workflow,
        tools=selected_tools,
    )
    return SkillWorkflowPreviewResponse(
        instruction_file=instruction_file,
        model_id=model_id,
        selected_tools=body.selected_tools,
    )


@SkillRouter.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    skill_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SKILLS, "delete")),
) -> None:
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.is_system:
        raise HTTPException(status_code=403, detail="System skills cannot be deleted")
    await db.delete(skill)


@SkillRouter.get("/{skill_id}/roles", response_model=list[uuid.UUID])
async def get_skill_roles(
    skill_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SKILLS, "read")),
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
    _: dict = Depends(require_permission(RT_AGENT_SKILLS, "update")),
) -> list[uuid.UUID]:
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.is_system:
        raise HTTPException(status_code=403, detail="System skills cannot be modified")

    role_ids: list[uuid.UUID] = [uuid.UUID(str(rid)) for rid in body.get("role_ids", [])]

    # Atomically replace membership
    await db.execute(delete(AgentRoleSkill).where(AgentRoleSkill.skill_id == skill_id))
    for role_id in role_ids:
        db.add(AgentRoleSkill(role_id=role_id, skill_id=skill_id))

    await db.flush()
    return role_ids
