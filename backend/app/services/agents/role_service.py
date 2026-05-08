"""AgentRole CRUD service — manages AgentRole with SOP/Skill assignments."""
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.agents import AgentIdentity, AgentRole, AgentRoleIdentity, AgentRoleMcpSession, AgentRoleSOP, AgentRoleSkill, AgentType

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

    Identity assignments are managed via assign_identities/remove_identity/list_identities.
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
        role = AgentRole(
            name=name,
            description=description,
        )
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

    # ── Identity Assignment Methods ────────────────────────────────────────────

    async def assign_identities(
        self,
        role_id: uuid.UUID,
        identity_ids: list[uuid.UUID],
        db: AsyncSession,
    ) -> None:
        """Bulk-assign identities to a role. Skips duplicates via INSERT OR IGNORE semantics."""
        await self.get_role(role_id, db)  # Validates role exists

        for identity_id in identity_ids:
            # Check if already assigned (avoid duplicate unique constraint error)
            existing = await db.execute(
                select(AgentRoleIdentity).where(
                    AgentRoleIdentity.role_id == role_id,
                    AgentRoleIdentity.identity_id == identity_id,
                )
            )
            if existing.scalar_one_or_none() is None:
                db.add(AgentRoleIdentity(role_id=role_id, identity_id=identity_id))

        await db.flush()
        logger.info("Assigned %d identity/identities to role %s", len(identity_ids), role_id)

    async def remove_identity(
        self,
        role_id: uuid.UUID,
        identity_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        """Remove a specific identity assignment from a role."""
        await self.get_role(role_id, db)  # Validates role exists

        result = await db.execute(
            select(AgentRoleIdentity).where(
                AgentRoleIdentity.role_id == role_id,
                AgentRoleIdentity.identity_id == identity_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is not None:
            await db.delete(row)
            await db.flush()
        logger.info("Removed identity %s from role %s", identity_id, role_id)

    async def list_identities(
        self,
        role_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[AgentIdentity]:
        """List all AgentIdentity records assigned to a role."""
        await self.get_role(role_id, db)  # Validates role exists

        result = await db.execute(
            select(AgentIdentity)
            .join(AgentRoleIdentity, AgentRoleIdentity.identity_id == AgentIdentity.id)
            .where(AgentRoleIdentity.role_id == role_id)
            .order_by(AgentIdentity.name)
        )
        return list(result.scalars().all())

    async def is_identity_assigned(
        self,
        role_id: uuid.UUID,
        identity_id: uuid.UUID,
        db: AsyncSession,
    ) -> bool:
        """Check if an identity is assigned to a role via agent_role_identities table."""
        result = await db.execute(
            select(AgentRoleIdentity).where(
                AgentRoleIdentity.role_id == role_id,
                AgentRoleIdentity.identity_id == identity_id,
            )
        )
        return result.scalar_one_or_none() is not None

    # ── MCP Session Management ─────────────────────────────────────────────────

    async def assign_mcp_session(
        self,
        role_id: uuid.UUID,
        mcp_session_id: uuid.UUID,
        assigned_by: uuid.UUID | None,
        db: AsyncSession,
    ) -> None:
        """Assign an MCP session to a role.
        
        Enforces the constraint that each role can have at most one session per MCP server.
        The server_id is extracted from the mcp_session to enforce the unique constraint.
        
        Args:
            role_id: The agent role ID
            mcp_session_id: The MCP session ID to assign
            assigned_by: User ID who performed the assignment
            db: Database session
            
        Raises:
            AgentRoleNotFoundError: If role doesn't exist
            ValueError: If MCP session doesn't exist or if role already has a session for this server
        """
        from app.db.models.mcp_hub import McpSession
        
        # Verify role exists
        await self.get_role(role_id, db)
        
        # Get MCP session to extract server_id
        session_result = await db.execute(
            select(McpSession).where(McpSession.id == mcp_session_id)
        )
        mcp_session = session_result.scalar_one_or_none()
        if not mcp_session:
            raise ValueError(f"MCP session {mcp_session_id} not found")
        
        # Check if role already has a session for this server
        existing = await db.execute(
            select(AgentRoleMcpSession).where(
                AgentRoleMcpSession.role_id == role_id,
                AgentRoleMcpSession.server_id == mcp_session.server_id,
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError(
                f"Role {role_id} already has an MCP session assigned for server {mcp_session.server_id}"
            )
        
        # Create assignment
        assignment = AgentRoleMcpSession(
            role_id=role_id,
            mcp_session_id=mcp_session_id,
            server_id=mcp_session.server_id,
            assigned_by=assigned_by,
        )
        db.add(assignment)
        await db.flush()
        
        logger.info(
            "Assigned MCP session %s (server %s) to role %s",
            mcp_session_id,
            mcp_session.server_id,
            role_id,
        )

    async def remove_mcp_session(
        self,
        role_id: uuid.UUID,
        mcp_session_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        """Remove an MCP session assignment from a role."""
        result = await db.execute(
            select(AgentRoleMcpSession).where(
                AgentRoleMcpSession.role_id == role_id,
                AgentRoleMcpSession.mcp_session_id == mcp_session_id,
            )
        )
        assignment = result.scalar_one_or_none()
        if assignment:
            await db.delete(assignment)
            await db.flush()
            logger.info("Removed MCP session %s from role %s", mcp_session_id, role_id)

    async def list_mcp_sessions(
        self,
        role_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """List all MCP sessions assigned to a role with server details.
        
        Returns:
            List of dicts with keys: id, name, server_id, server_name, server_slug, assigned_at
        """
        from app.db.models.mcp_hub import McpServer, McpSession
        
        result = await db.execute(
            select(McpSession, McpServer, AgentRoleMcpSession.assigned_at)
            .join(AgentRoleMcpSession, AgentRoleMcpSession.mcp_session_id == McpSession.id)
            .join(McpServer, McpServer.id == McpSession.server_id)
            .where(AgentRoleMcpSession.role_id == role_id)
            .order_by(McpServer.name, McpSession.name)
        )
        
        sessions = []
        for session, server, assigned_at in result.all():
            sessions.append({
                "id": str(session.id),
                "name": session.name,
                "server_id": str(server.id),
                "server_name": server.name,
                "server_slug": server.slug,
                "assigned_at": assigned_at.isoformat() if assigned_at else None,
            })
        
        return sessions

    async def get_available_mcp_sessions(
        self,
        role_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Get MCP sessions available for assignment to a role.
        
        Filters to show only sessions from MCP servers whose tools are used by the role's
        SOPs/Skills. This ensures roles only get sessions for MCP servers they actually need.
        
        Returns:
            List of dicts with keys: id, name, server_id, server_name, server_slug
        """
        from app.db.models.mcp_hub import McpServer, McpSession, McpTool
        from app.db.models.skills import Skill, SkillToolBinding, Sop, SopStep
        
        # Get all MCP tool names used by role's skills (both direct and via SOPs)
        # First, get direct skill assignments
        skill_result = await db.execute(
            select(Skill.id)
            .join(AgentRoleSkill, AgentRoleSkill.skill_id == Skill.id)
            .where(AgentRoleSkill.role_id == role_id)
        )
        skill_ids = [row[0] for row in skill_result.all()]
        
        # Get skills from SOPs (through SopSteps)
        sop_skill_result = await db.execute(
            select(SopStep.skill_id)
            .join(Sop, Sop.id == SopStep.sop_id)
            .join(AgentRoleSOP, AgentRoleSOP.sop_id == Sop.id)
            .where(
                AgentRoleSOP.role_id == role_id,
                SopStep.skill_id.is_not(None)
            )
        )
        skill_ids.extend([row[0] for row in sop_skill_result.all()])
        
        if not skill_ids:
            # No skills assigned, return empty list
            return []
        
        # Get unique MCP tool names from these skills
        tool_result = await db.execute(
            select(McpTool.name)
            .join(SkillToolBinding, SkillToolBinding.tool_id == McpTool.id)
            .where(SkillToolBinding.skill_id.in_(skill_ids))
            .distinct()
        )
        tool_names = [row[0] for row in tool_result.all()]
        
        if not tool_names:
            # No MCP tools needed, return empty list
            return []
        
        # Extract server slugs from tool names (format: "server_slug/tool_name")
        server_slugs = list(set(name.split("/")[0] for name in tool_names if "/" in name))
        
        if not server_slugs:
            return []
        
        # Get MCP sessions from these servers
        result = await db.execute(
            select(McpSession, McpServer)
            .join(McpServer, McpServer.id == McpSession.server_id)
            .where(
                McpServer.slug.in_(server_slugs),
                McpSession.is_active.is_(True),
            )
            .order_by(McpServer.name, McpSession.name)
        )
        
        sessions = []
        for session, server in result.all():
            sessions.append({
                "id": str(session.id),
                "name": session.name,
                "server_id": str(server.id),
                "server_name": server.name,
                "server_slug": server.slug,
            })
        
        return sessions

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

