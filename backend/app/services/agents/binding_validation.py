"""BindingValidationService — validates SOP/Skill bindings against role permissions."""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentRoleSOP, AgentRoleSkill
from app.schemas.agent_type_bindings import (
    BindingError,
    BindingResourceType,
    BindingRule,
    SopBindingCreate,
    SkillBindingCreate,
)

logger = logging.getLogger(__name__)


async def validate_bindings(
    db: AsyncSession,
    role_id: uuid.UUID,
    sop_bindings: list[SopBindingCreate],
    skill_bindings: list[SkillBindingCreate],
) -> list[BindingError]:
    """Validate binding entries against the role's permitted SOPs and skills.

    Checks:
    1. Each bound SOP is accessible through the role.
    2. Each bound skill is accessible through the role.
    3. No duplicate SOP entries.
    4. No duplicate skill entries.

    Returns:
        A list of structured binding errors (empty list = valid). Each error
        carries the failing resource (type + id), the rule that failed, and a
        human-readable message.
    """
    errors: list[BindingError] = []

    if not role_id:
        if sop_bindings or skill_bindings:
            errors.append(
                BindingError(
                    resource_type=BindingResourceType.ROLE,
                    resource_id=None,
                    rule=BindingRule.ROLE_REQUIRED,
                    message=(
                        "Cannot set bindings without assigning a role to the agent type."
                    ),
                )
            )
        return errors

    # Query the role's permitted SOP IDs
    sop_result = await db.execute(
        select(AgentRoleSOP.sop_id).where(AgentRoleSOP.role_id == role_id)
    )
    permitted_sop_ids: set[uuid.UUID] = {row[0] for row in sop_result.fetchall()}

    # Query the role's permitted skill IDs
    skill_result = await db.execute(
        select(AgentRoleSkill.skill_id).where(AgentRoleSkill.role_id == role_id)
    )
    permitted_skill_ids: set[uuid.UUID] = {row[0] for row in skill_result.fetchall()}

    # Check SOP bindings
    seen_sop_ids: set[uuid.UUID] = set()
    for binding in sop_bindings:
        if binding.sop_id in seen_sop_ids:
            errors.append(
                BindingError(
                    resource_type=BindingResourceType.SOP,
                    resource_id=binding.sop_id,
                    rule=BindingRule.DUPLICATE,
                    message=(
                        f"Duplicate SOP binding: sop_id={binding.sop_id} appears more than once."
                    ),
                )
            )
        seen_sop_ids.add(binding.sop_id)

        if binding.sop_id not in permitted_sop_ids:
            errors.append(
                BindingError(
                    resource_type=BindingResourceType.SOP,
                    resource_id=binding.sop_id,
                    rule=BindingRule.ROLE_ACCESS,
                    message=(
                        f"SOP {binding.sop_id} is not accessible through the assigned role."
                    ),
                )
            )

    # Check Skill bindings
    seen_skill_ids: set[uuid.UUID] = set()
    for binding in skill_bindings:
        if binding.skill_id in seen_skill_ids:
            errors.append(
                BindingError(
                    resource_type=BindingResourceType.SKILL,
                    resource_id=binding.skill_id,
                    rule=BindingRule.DUPLICATE,
                    message=(
                        f"Duplicate Skill binding: skill_id={binding.skill_id} appears more than once."
                    ),
                )
            )
        seen_skill_ids.add(binding.skill_id)

        if binding.skill_id not in permitted_skill_ids:
            errors.append(
                BindingError(
                    resource_type=BindingResourceType.SKILL,
                    resource_id=binding.skill_id,
                    rule=BindingRule.ROLE_ACCESS,
                    message=(
                        f"Skill {binding.skill_id} is not accessible through the assigned role."
                    ),
                )
            )

    if errors:
        # Log every individual failure — a bare count hides which binding and
        # which rule failed, making support triage impossible.
        for error in errors:
            logger.warning(
                "Binding validation error for role_id=%s: resource_type=%s resource_id=%s rule=%s: %s",
                role_id,
                error.resource_type.value,
                error.resource_id,
                error.rule.value,
                error.message,
            )
        logger.warning(
            "Binding validation failed for role_id=%s: %d error(s)",
            role_id,
            len(errors),
        )

    return errors
