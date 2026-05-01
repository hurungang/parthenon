"""SOPs API router — CRUD and step management for Standard Operating Procedures."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select

from app.api.deps import require_permission
from app.core.resource_types import RT_SKILL
from app.db.models.skills import Skill, Sop, SopStep
from app.db.session import DbSession
from app.schemas.skills import (
    SopCreate,
    SopDetailRead,
    SopRead,
    SopStepCreate,
    SopStepRead,
    SopUpdate,
)

logger = logging.getLogger(__name__)

SopRouter = APIRouter(prefix="/sops", tags=["SOPs"])


@SopRouter.get("", response_model=list[SopRead])
async def list_sops(
    db: DbSession,
    _: dict = Depends(require_permission(RT_SKILL, "read")),
) -> list[Sop]:
    result = await db.execute(select(Sop).order_by(Sop.name))
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
    result = await db.execute(select(Sop).where(Sop.id == sop_id))
    sop = result.scalar_one_or_none()
    if not sop:
        raise HTTPException(status_code=404, detail="SOP not found")
    # Load steps
    steps_result = await db.execute(
        select(SopStep).where(SopStep.sop_id == sop_id).order_by(SopStep.order)
    )
    sop.steps = list(steps_result.scalars().all())
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

    # Validate skill IDs for skill steps
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
            delegate_agent_type_id=step_data.delegate_agent_type_id,
            name=step_data.name,
            description=step_data.description,
        )
        db.add(step)
        new_steps.append(step)

    await db.flush()
    for step in new_steps:
        await db.refresh(step)

    return new_steps
