"""AgentRole CRUD service — manages AgentRole with SOP/Skill assignments."""
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.agents import AgentRole, AgentRoleSOP, AgentRoleSkill, AgentType

logger = logging.getLogger(__name__)


class AgentRoleNotFoundError(Exception):
    """Raised when an AgentRole is not found."""


class AgentRoleConflictError(Exception):
    """Raised when deletion is blocked by a referencing AgentType."""


class AgentRoleService:
    """
    Provides async CRUD operations for AgentRole.

    SOP and Skill assignments are managed as join records within the same
    database transaction as the role create/update.

    Also exposes invalidate_cache(role_id) for use by AgentPermissionManager.
    """

    # Injected by AgentPermissionManager after construction to break the circular dep.
    _permission_manager: Any | None = None

    async def create_role(
        self,
        name: str,
        description: str | None,
        sop_ids: list[uuid.UUID],
        skill_ids: list[uuid.UUID],
        db: AsyncSession,
    ) -> AgentRole:
        """Create a new AgentRole with the supplied SOP/Skill assignments."""
        role = AgentRole(name=name, description=description)
        db.add(role)
        await db.flush()

        await self._set_assignments(role.id, sop_ids, skill_ids, db)

        await db.refresh(role, ["sop_assignments", "skill_assignments"])
        logger.info("Created AgentRole %s (%s)", role.id, name)
        return role

    async def list_roles(self, db: AsyncSession) -> list[AgentRole]:
        """Return all AgentRoles with their SOP/Skill assignments loaded."""
        result = await db.execute(
            select(AgentRole)
            .options(
                selectinload(AgentRole.sop_assignments),
                selectinload(AgentRole.skill_assignments),
            )
            .order_by(AgentRole.name)
        )
        return list(result.scalars().all())

    async def get_role(self, role_id: uuid.UUID, db: AsyncSession) -> AgentRole:
        """Fetch a single AgentRole by ID with assignments loaded."""
        result = await db.execute(
            select(AgentRole)
            .where(AgentRole.id == role_id)
            .options(
                selectinload(AgentRole.sop_assignments),
                selectinload(AgentRole.skill_assignments),
            )
        )
        role = result.scalar_one_or_none()
        if not role:
            raise AgentRoleNotFoundError(f"AgentRole {role_id} not found")
        return role

    async def update_role(
        self,
        role_id: uuid.UUID,
        name: str | None,
        description: str | None,
        sop_ids: list[uuid.UUID] | None,
        skill_ids: list[uuid.UUID] | None,
        db: AsyncSession,
    ) -> AgentRole:
        """Update an AgentRole. Replaces SOP/Skill assignments when provided."""
        role = await self.get_role(role_id, db)

        if name is not None:
            role.name = name
        if description is not None:
            role.description = description

        # Replace assignments when explicitly provided
        if sop_ids is not None or skill_ids is not None:
            await self._set_assignments(
                role_id,
                sop_ids if sop_ids is not None else [a.sop_id for a in role.sop_assignments],
                skill_ids if skill_ids is not None else [a.skill_id for a in role.skill_assignments],
                db,
            )

        await db.flush()
        await db.refresh(role, ["sop_assignments", "skill_assignments"])

        # Invalidate permission cache for this role
        if self._permission_manager is not None:
            self._permission_manager.invalidate(role_id)

        logger.info("Updated AgentRole %s", role_id)
        return role

    async def delete_role(self, role_id: uuid.UUID, db: AsyncSession) -> None:
        """Delete an AgentRole. Fails if any AgentType references it."""
        role = await self.get_role(role_id, db)

        # Referential integrity guard
        ref_check = await db.execute(
            select(AgentType.id).where(AgentType.role_id == role_id).limit(1)
        )
        if ref_check.scalar_one_or_none() is not None:
            raise AgentRoleConflictError(
                f"AgentRole {role_id} is referenced by one or more AgentTypes and cannot be deleted"
            )

        await db.delete(role)
        await db.flush()

        # Invalidate permission cache for this role
        if self._permission_manager is not None:
            self._permission_manager.invalidate(role_id)

        logger.info("Deleted AgentRole %s", role_id)

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _set_assignments(
        self,
        role_id: uuid.UUID,
        sop_ids: list[uuid.UUID],
        skill_ids: list[uuid.UUID],
        db: AsyncSession,
    ) -> None:
        """Replace all SOP and Skill join records for the given role atomically."""
        # Delete existing assignments
        existing_sops = await db.execute(
            select(AgentRoleSOP).where(AgentRoleSOP.role_id == role_id)
        )
        for row in existing_sops.scalars().all():
            await db.delete(row)

        existing_skills = await db.execute(
            select(AgentRoleSkill).where(AgentRoleSkill.role_id == role_id)
        )
        for row in existing_skills.scalars().all():
            await db.delete(row)

        await db.flush()

        # Insert fresh assignments
        for sop_id in sop_ids:
            db.add(AgentRoleSOP(role_id=role_id, sop_id=sop_id))
        for skill_id in skill_ids:
            db.add(AgentRoleSkill(role_id=role_id, skill_id=skill_id))

        await db.flush()
