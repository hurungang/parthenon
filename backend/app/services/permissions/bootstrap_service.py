"""Bootstrap Service — seeds the system_admin role on first startup.

Idempotent: safe to run on every application restart.
"""

import logging
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.identity import Role
from app.db.models.platform_user import PlatformUser
from app.db.models.policy_action import PolicyAction
from app.db.models.policy_resource import PolicyResource
from app.db.models.policy_statement import PolicyEffect, PolicyStatement
from app.db.models.user_role import UserRole

logger = logging.getLogger(__name__)

SYSTEM_ADMIN_ROLE_NAME = "system_admin"


class BootstrapService:
    """Seeds the system_admin role with full-access policies on startup."""

    async def initialize(self, db: AsyncSession) -> None:
        """Run bootstrap checks; create system_admin role if absent.

        Steps:
        1. Ensure the system_admin role exists (is_system=True).
        2. Ensure a full-access policy statement exists for it.
        3. If BOOTSTRAP_ADMIN_EMAIL is set, assign the role to that user when found.
        """
        role = await self._ensure_system_admin_role(db)
        await self._ensure_full_access_policy(db, role)
        await self._try_assign_initial_admin(db, role)
        await db.commit()
        logger.info("Bootstrap complete. system_admin role is ready.")

    # ── private helpers ──────────────────────────────────────────────────────

    async def _ensure_system_admin_role(self, db: AsyncSession) -> Role:
        result = await db.execute(
            select(Role).where(Role.name == SYSTEM_ADMIN_ROLE_NAME, Role.is_system.is_(True))
        )
        role = result.scalar_one_or_none()
        if role is None:
            role = Role(
                name=SYSTEM_ADMIN_ROLE_NAME,
                description="System administrator — full platform access. Immutable.",
                is_system=True,
                is_active=True,
            )
            db.add(role)
            await db.flush()
            logger.info("Created system_admin role id=%s", role.id)
        return role

    async def _ensure_full_access_policy(self, db: AsyncSession, role: Role) -> None:
        """Create a wildcard allow policy for the role if one does not exist."""
        existing = await db.execute(
            select(PolicyStatement).where(
                PolicyStatement.role_id == role.id,
                PolicyStatement.module == "*",
                PolicyStatement.effect == PolicyEffect.allow,
            )
        )
        stmt = existing.scalar_one_or_none()
        if stmt is None:
            stmt = PolicyStatement(
                role_id=role.id,
                effect=PolicyEffect.allow,
                module="*",
            )
            db.add(stmt)
            await db.flush()

            # Wildcard action
            db.add(PolicyAction(policy_statement_id=stmt.id, action="*"))
            # Wildcard resource
            db.add(PolicyResource(policy_statement_id=stmt.id, resource_type="*", resource_id="*"))
            await db.flush()
            logger.info("Created full-access policy statement id=%s for system_admin role", stmt.id)

    async def _try_assign_initial_admin(self, db: AsyncSession, role: Role) -> None:
        """Assign system_admin to BOOTSTRAP_ADMIN_EMAIL user if configured and found."""
        admin_email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip()
        if not admin_email:
            return

        user_result = await db.execute(
            select(PlatformUser).where(PlatformUser.email == admin_email)
        )
        user = user_result.scalar_one_or_none()
        if user is None:
            logger.debug(
                "Bootstrap: BOOTSTRAP_ADMIN_EMAIL=%s not yet in platform_users; skipping assignment.",
                admin_email,
            )
            return

        # Check if already assigned
        existing = await db.execute(
            select(UserRole).where(
                UserRole.user_id == user.id,
                UserRole.role_id == role.id,
            )
        )
        if existing.scalar_one_or_none() is None:
            db.add(UserRole(user_id=user.id, role_id=role.id))
            await db.flush()
            logger.info(
                "Bootstrap: assigned system_admin role to user email=%s id=%s",
                admin_email,
                user.id,
            )
