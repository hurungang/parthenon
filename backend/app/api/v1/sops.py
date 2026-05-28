"""SOPs API router — CRUD and step management for Standard Operating Procedures."""
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.core.resource_types import RT_SKILL
from app.db.session import DbSession
from app.db.models.skills import Skill, Sop, SopStep
from app.db.models.agents import AgentRoleSOP, AgentType
from app.schemas.skills import SopCreate, SopDetailRead, SopRead, SopStepCreate, SopStepRead, SopUpdate
from app.schemas.skills import (
    SopWorkflowGenerateRequest,
    SopWorkflowGenerateResponse,
    SopWorkflowPreviewRequest,
    SopWorkflowPreviewResponse,
)
from app.services.agents.workflow_authoring_service import (
    WorkflowAuthoringError,
    build_sop_instruction_file,
    generate_workflow_text,
    resolve_model_config_for_generation,
)
from app.services.agents.workflow_generation_settings import get_workflow_generation_model_id

logger = logging.getLogger(__name__)

SopRouter = APIRouter(prefix="/sops", tags=["SOPs"])


def _require_workflow_model_id() -> str:
    model_id = get_workflow_generation_model_id()
    if not model_id:
        raise HTTPException(
            status_code=422,
            detail="Workflow generation model is not configured. Configure it in system settings.",
        )
    return model_id


@SopRouter.get("", response_model=list[SopRead])
async def list_sops(
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "read")),
) -> list[Sop]:
    # Load steps relationship so SopRead can populate required_skill_ids
    result = await db.execute(select(Sop).options(selectinload(Sop.steps)).order_by(Sop.name))
    return list(result.scalars().all())


@SopRouter.post("", response_model=SopRead, status_code=status.HTTP_201_CREATED)
async def create_sop(
    body: SopCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "create")),
) -> Sop:
    sop = Sop(**body.model_dump())
    db.add(sop)
    await db.flush()
    await db.refresh(sop)
    return sop


@SopRouter.get("/{sop_id}", response_model=SopDetailRead)
async def get_sop(
    sop_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "read")),
) -> Sop:
    result = await db.execute(
        select(Sop).where(Sop.id == sop_id).options(selectinload(Sop.steps))
    )
    sop = result.scalar_one_or_none()
    if not sop:
        raise HTTPException(status_code=404, detail="SOP not found")
    return sop


@SopRouter.put("/{sop_id}", response_model=SopRead)
async def update_sop(
    sop_id: uuid.UUID,
    body: SopUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "update")),
) -> Sop:
    sop = await db.get(Sop, sop_id)
    if not sop:
        raise HTTPException(status_code=404, detail="SOP not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(sop, field, value)

    await db.flush()
    await db.refresh(sop)
    return sop


@SopRouter.post("/workflow/generate", response_model=SopWorkflowGenerateResponse)
async def generate_sop_workflow(
    body: SopWorkflowGenerateRequest,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "update")),
) -> SopWorkflowGenerateResponse:
    if not body.description.strip():
        raise HTTPException(status_code=422, detail="Description is required to generate workflow")
    if not body.steps:
        raise HTTPException(status_code=422, detail="Add at least one SOP step to generate workflow")

    model_id = _require_workflow_model_id()
    try:
        await resolve_model_config_for_generation(model_id, db)

        # Resolve agent and skill names so the AI gets names, not UUIDs
        agent_ids = {s.target_agent_type_id for s in body.steps if s.target_agent_type_id}
        skill_ids = {s.skill_id for s in body.steps if s.skill_id}
        agent_name_map: dict = {}
        skill_name_map: dict = {}
        if agent_ids:
            rows = await db.execute(select(AgentType.id, AgentType.name).where(AgentType.id.in_(agent_ids)))
            agent_name_map = {row.id: row.name for row in rows}
        if skill_ids:
            rows = await db.execute(select(Skill.id, Skill.name).where(Skill.id.in_(skill_ids)))
            skill_name_map = {row.id: row.name for row in rows}

        step_lines: list[str] = []
        for step in sorted(body.steps, key=lambda s: s.order):
            label = step.name or f"Step {step.order + 1}"
            description = (step.description or "No description").strip()
            extra = ""
            if step.target_agent_type_id:
                agent_name = agent_name_map.get(step.target_agent_type_id, str(step.target_agent_type_id))
                extra = f" | agent:{agent_name}"
            if step.skill_id:
                skill_name = skill_name_map.get(step.skill_id, str(step.skill_id))
                extra += f" | skill:{skill_name}"
            step_lines.append(f"- [{step.order + 1}] {label} ({step.step_type}) - {description}{extra}")

        user_prompt = (
            "Business description:\n"
            f"{body.description.strip()}\n\n"
            "Ordered SOP steps:\n"
            f"{'\n'.join(step_lines)}\n\n"
            "Write a concise execution workflow that follows the provided order and preserves delegation semantics."
        )
        workflow = await generate_workflow_text(
            model_id=model_id,
            system_prompt=(
                "You author SOP/Skill workflows for enterprise agents. "
                "When referencing a skill, always write 'use skill <skill-name> to <action>' "
                "(e.g. 'use skill get-project-name to retrieve the project identifier'). "
                "When referencing an agent, always write 'use agent <agent-name> to <action>' "
                "(e.g. 'use agent onboarding-agent to onboard the new user'). "
                "Names are already in slug format. "
                "Each step must be a numbered line that preserves the intent from the provided step description. "
                "Respond with workflow text only. Do not include markdown code fences."
            ),
            user_prompt=user_prompt,
            db=db,
        )
    except (WorkflowAuthoringError, Exception) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return SopWorkflowGenerateResponse(workflow=workflow, model_id=model_id)


@SopRouter.post("/workflow/preview", response_model=SopWorkflowPreviewResponse)
async def preview_sop_workflow(
    body: SopWorkflowPreviewRequest,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "read")),
) -> SopWorkflowPreviewResponse:
    model_id = _require_workflow_model_id()
    try:
        await resolve_model_config_for_generation(model_id, db)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    instruction_file = build_sop_instruction_file(
        workflow=body.workflow,
        steps=[step.model_dump() for step in body.steps],
    )
    return SopWorkflowPreviewResponse(
        instruction_file=instruction_file,
        model_id=model_id,
        steps=body.steps,
    )


@SopRouter.delete("/{sop_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sop(
    sop_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "delete")),
) -> None:
    sop = await db.get(Sop, sop_id)
    if not sop:
        raise HTTPException(status_code=404, detail="SOP not found")
    await db.delete(sop)


@SopRouter.get("/{sop_id}/steps", response_model=list[SopStepRead])
async def list_sop_steps(
    sop_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "read")),
) -> list[SopStep]:
    sop = await db.get(Sop, sop_id)
    if not sop:
        raise HTTPException(status_code=404, detail="SOP not found")
    result = await db.execute(
        select(SopStep).where(SopStep.sop_id == sop_id).order_by(SopStep.order)
    )
    return list(result.scalars().all())


@SopRouter.put("/{sop_id}/steps", response_model=list[SopStepRead])
async def replace_sop_steps(
    sop_id: uuid.UUID,
    body: list[SopStepCreate],
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "update")),
) -> list[SopStep]:
    """Replace the full ordered step list for a SOP."""
    sop = await db.get(Sop, sop_id)
    if not sop:
        raise HTTPException(status_code=404, detail="SOP not found")

    # Validate skill IDs for skill_invocation steps
    for step_data in body:
        if step_data.skill_id:
            skill = await db.get(Skill, step_data.skill_id)
            if not skill:
                raise HTTPException(
                    status_code=422,
                    detail=f"Skill with id {step_data.skill_id} not found",
                )

    # Delete existing steps
    await db.execute(delete(SopStep).where(SopStep.sop_id == sop_id))

    # Create new steps in order
    new_steps: list[SopStep] = []
    for idx, step_data in enumerate(body):
        step = SopStep(
            sop_id=sop_id,
            order=step_data.order if step_data.order is not None else idx,
            step_type=step_data.step_type,
            skill_id=step_data.skill_id,
            target_agent_type_id=step_data.target_agent_type_id,
            step_config=step_data.step_config,
            name=step_data.name,
            description=step_data.description,
        )
        db.add(step)
        new_steps.append(step)

    await db.flush()
    for step in new_steps:
        await db.refresh(step)

    return new_steps


@SopRouter.get("/{sop_id}/roles", response_model=list[uuid.UUID])
async def get_sop_roles(
    sop_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "read")),
) -> list[uuid.UUID]:
    sop = await db.get(Sop, sop_id)
    if not sop:
        raise HTTPException(status_code=404, detail="SOP not found")
    result = await db.execute(
        select(AgentRoleSOP.role_id).where(AgentRoleSOP.sop_id == sop_id)
    )
    return list(result.scalars().all())


@SopRouter.put("/{sop_id}/roles", response_model=list[uuid.UUID])
async def set_sop_roles(
    sop_id: uuid.UUID,
    body: dict,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "update")),
) -> list[uuid.UUID]:
    sop = await db.get(Sop, sop_id)
    if not sop:
        raise HTTPException(status_code=404, detail="SOP not found")

    role_ids: list[uuid.UUID] = [uuid.UUID(str(rid)) for rid in body.get("role_ids", [])]

    # Atomically replace membership
    await db.execute(delete(AgentRoleSOP).where(AgentRoleSOP.sop_id == sop_id))
    for role_id in role_ids:
        db.add(AgentRoleSOP(role_id=role_id, sop_id=sop_id))

    await db.flush()
    return role_ids
