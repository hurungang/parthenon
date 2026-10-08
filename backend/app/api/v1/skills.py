"""Skills API router — CRUD for skills with MCP tool binding validation."""
import json
import uuid
import logging
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.api.v1.mcp_hub import (
    SYSTEM_TOOL_IDS,
)
from app.core.resource_types import RT_AGENT_SKILLS
from app.core.tenant_context import get_tenant_context
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


def _tenant_id_from(request: Request) -> uuid.UUID | None:
    """Tenant of the caller (None when tenancy is unset/disabled)."""
    context = get_tenant_context(request)
    return context.tenant_id if context.is_set else None


async def _get_decision_tool_record(
    db, tool_id: uuid.UUID, tenant_id: uuid.UUID | None
) -> _ToolRecord | None:
    """Return a _ToolRecord for a virtual decision tool id, or None.

    Mirrors ``_get_system_tool_record`` — decision tools are virtual
    (no ``mcp_tools`` row) and surface canonically as ``decision____<name>``.
    """
    from app.services.system_one.decision_tool_service import (
        build_input_schema,
        resolve_virtual_tool_id,
    )

    tool = await resolve_virtual_tool_id(db, tool_id, tenant_id)
    if tool is None:
        return None
    return _ToolRecord(
        name=build_tool_name("decision", tool.name),
        description=tool.description,
        input_schema=build_input_schema(tool),
    )


async def _build_tool_records(db, skill: Skill, tenant_id: uuid.UUID | None) -> list[_ToolRecord]:
    """Resolve a skill's bindings to tool records in binding order."""
    tool_records: list[_ToolRecord] = []
    for binding in sorted(skill.tool_bindings, key=lambda b: b.order):
        # Prefer canonical system tool definitions so generated references always
        # include full schemas, even if DB-seeded rows have partial metadata.
        system_tool = _get_system_tool_record(binding.tool_id)
        if system_tool:
            tool_records.append(system_tool)
            continue
        # Virtual decision tools (no mcp_tools row)
        decision_tool = await _get_decision_tool_record(db, binding.tool_id, tenant_id)
        if decision_tool:
            tool_records.append(decision_tool)
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
    return tool_records


def _instructions_with_tools(skill: Skill, tool_records: list[_ToolRecord]) -> str | None:
    tool_section = assemble_tool_section(tool_records)
    if tool_section:
        return (skill.instructions or "") + "\n\n" + tool_section
    return skill.instructions


async def _build_skill_read(db, skill: Skill, tenant_id: uuid.UUID | None) -> SkillRead:
    """Construct a SkillRead response with computed instructions_with_tools."""
    tool_records = await _build_tool_records(db, skill, tenant_id)
    skill_read = SkillRead.model_validate(skill)
    skill_read.instructions_with_tools = _instructions_with_tools(skill, tool_records)
    return skill_read


async def _build_skill_detail_read(
    db, skill: Skill, tenant_id: uuid.UUID | None
) -> SkillDetailRead:
    """Construct a SkillDetailRead response with computed instructions_with_tools."""
    tool_records = await _build_tool_records(db, skill, tenant_id)
    skill_detail = SkillDetailRead.model_validate(skill)
    skill_detail.instructions_with_tools = _instructions_with_tools(skill, tool_records)
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
    request: Request,
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
    tenant_id = _tenant_id_from(request)
    return [await _build_skill_read(db, s, tenant_id) for s in skills]


async def _validate_tool_ids(
    db, tool_ids: list[uuid.UUID], tenant_id: uuid.UUID | None
) -> None:
    """Validate every tool id bound to a skill.

    - System tools are virtual registry entries (no DB row).
    - Decision tools are virtual tenant-scoped uuid5 entries resolved via
      ``resolve_virtual_tool_id`` (must exist AND be enabled in the
      caller's tenant — a foreign tenant's decision id 422s).
    - Everything else must be an existing McpTool row.
    """
    from app.services.system_one.decision_tool_service import resolve_virtual_tool_id

    for tool_id in tool_ids:
        if tool_id in SYSTEM_TOOL_IDS:
            continue
        decision_tool = await resolve_virtual_tool_id(db, tool_id, tenant_id)
        if decision_tool is not None:
            continue
        tool = await db.get(McpTool, tool_id)
        if not tool:
            raise HTTPException(
                status_code=422,
                detail=f"MCP tool with id {tool_id} not found",
            )


@SkillRouter.post("", response_model=SkillDetailRead, status_code=status.HTTP_201_CREATED)
async def create_skill(
    body: SkillCreate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SKILLS, "create")),
) -> SkillDetailRead:
    tenant_id = _tenant_id_from(request)
    await _validate_tool_ids(db, body.tool_ids, tenant_id)
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
    return await _build_skill_detail_read(db, result.scalar_one(), tenant_id)


@SkillRouter.get("/{skill_id}", response_model=SkillDetailRead)
async def get_skill(
    skill_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SKILLS, "read")),
) -> SkillDetailRead:
    result = await db.execute(
        select(Skill).options(*_SKILL_LOAD_OPTIONS).where(Skill.id == skill_id)
    )
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return await _build_skill_detail_read(db, skill, _tenant_id_from(request))


@SkillRouter.put("/{skill_id}", response_model=SkillDetailRead)
async def update_skill(
    skill_id: uuid.UUID,
    body: SkillUpdate,
    request: Request,
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

    tenant_id = _tenant_id_from(request)

    for field, value in body.model_dump(exclude_unset=True, exclude={"tool_ids"}).items():
        setattr(skill, field, value)

    if body.tool_ids is not None:
        # Validate new tool IDs (system + virtual decision tools included)
        await _validate_tool_ids(db, body.tool_ids, tenant_id)
        # Remove old bindings
        await db.execute(delete(SkillToolBinding).where(SkillToolBinding.skill_id == skill_id))
        # The identity map caches the eagerly-loaded collection — expire it so
        # the response below reflects the NEW bindings, not the stale ones.
        db.expire(skill, ["tool_bindings"])

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
    return await _build_skill_detail_read(db, result.scalar_one(), tenant_id)


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
