"""Gateway Lifecycle Handler — orchestrates the gateway state machine.

Extended in the Agent Runtime with Gateway change to route inbound agent launch
requests through AgentSessionService.enqueue and return session IDs synchronously.
The legacy synchronous execution path is retained for backward compatibility but
all new agent launches use the asynchronous session queue.

OAuth middleware (Phase 5.6a): validates agent identity access tokens on launch.
Role-based tool exposure (Phase 5.6b): exposes only role-permitted tools with no
descriptions or schemas, so agents rely fully on skill instructions.
"""
import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentInstanceStatus
from app.services.agents.identity_service import AgentIdentityService, AgentOAuthError
from app.services.agents.instance_manager import AgentInstanceManager, InstanceLimitError
from app.services.agents.permission_manager import AgentPermissionManager
from app.services.agents.session_service import AgentSessionService

logger = logging.getLogger(__name__)

# In-memory store for pending questions per session handle
# In production this would be backed by Redis
_pending_questions: dict[str, asyncio.Queue] = {}
_pending_answers: dict[str, asyncio.Queue] = {}


class AgentAuthError(Exception):
    """Raised when agent identity token validation fails."""


class GatewayLifecycleHandler:
    """
    Orchestrates the gateway state machine.

    New path (Phase 5): launch → validate identity token → enqueue session → return session_id.
    Role-based tool exposure: tools are returned without descriptions/schemas.
    Legacy path: init → request (question → answer) → close (retained for compatibility).
    """

    def __init__(self) -> None:
        self._instance_manager = AgentInstanceManager()
        self._session_service = AgentSessionService()
        self._permission_manager = AgentPermissionManager()
        self._identity_service = AgentIdentityService()

    # ── OAuth identity token validation ───────────────────────────────────────

    async def validate_agent_identity_token(
        self,
        agent_type_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        """
        Validate that the AgentType's identity has a valid (non-expired) access token
        and that the identity type is permitted by the assigned role.

        Raises AgentAuthError if validation fails.
        """
        from sqlalchemy import select
        from app.db.models.agents import AgentType, AgentIdentity, AgentRole
        from datetime import datetime, UTC

        result = await db.execute(
            select(AgentType).where(AgentType.id == agent_type_id)
        )
        agent_type = result.scalar_one_or_none()
        if not agent_type:
            raise AgentAuthError(f"AgentType {agent_type_id} not found")

        if not agent_type.identity_id:
            logger.debug(
                "AgentType %s has no identity — skipping OAuth token validation", agent_type_id
            )
            return

        identity = await db.get(AgentIdentity, agent_type.identity_id)
        if not identity:
            raise AgentAuthError(
                f"AgentIdentity {agent_type.identity_id} not found for AgentType {agent_type_id}"
            )

        # Check token is present and not expired
        if not identity.access_token:
            raise AgentAuthError(
                f"AgentIdentity '{identity.name}' has no access token — "
                "complete the OAuth sign-in flow first"
            )
        
        # Auto-refresh if access token is expired and refresh token is available
        if identity.token_expires_at and identity.token_expires_at < datetime.now(UTC):
            if identity.refresh_token:
                try:
                    logger.info(
                        "Access token expired for identity '%s' — attempting auto-refresh",
                        identity.name,
                    )
                    await self._identity_service.refresh_token(identity.id, db)
                    # Re-fetch identity after refresh to get updated token
                    await db.refresh(identity)
                    logger.info(
                        "Successfully auto-refreshed token for identity '%s'", identity.name
                    )
                except AgentOAuthError as e:
                    raise AgentAuthError(
                        f"AgentIdentity '{identity.name}' access token has expired and "
                        f"auto-refresh failed: {e}"
                    )
            else:
                raise AgentAuthError(
                    f"AgentIdentity '{identity.name}' access token has expired and "
                    "no refresh token available — re-authentication required"
                )

        # Validate identity is explicitly assigned to the role
        if agent_type.role_id:
            from sqlalchemy import select
            from app.db.models.agents import AgentRoleIdentity
            
            result = await db.execute(
                select(AgentRoleIdentity).where(
                    AgentRoleIdentity.role_id == agent_type.role_id,
                    AgentRoleIdentity.identity_id == identity.id,
                )
            )
            assignment = result.scalar_one_or_none()
            
            if not assignment:
                role = await db.get(AgentRole, agent_type.role_id)
                role_name = role.name if role else str(agent_type.role_id)
                raise AgentAuthError(
                    f"AgentIdentity '{identity.name}' is not assigned to role '{role_name}' — "
                    f"identity must be explicitly assigned to the role before launching agents"
                )

        logger.debug(
            "AgentIdentity '%s' token validated for AgentType %s", identity.name, agent_type_id
        )

    # ── Role-based tool exposure ───────────────────────────────────────────────

    async def get_role_tools_for_agent(
        self,
        agent_type_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """
        Return the list of tool stubs allowed for the AgentType's role.

        Tools are exposed **without descriptions or input schemas** so that agents
        rely fully on skill instructions rather than tool introspection.
        Only the tool name (mcp_slug/tool_name) is returned.

        Always includes the save_result system tool.
        """
        from sqlalchemy import select
        from app.db.models.agents import AgentType

        result = await db.execute(
            select(AgentType).where(AgentType.id == agent_type_id)
        )
        agent_type = result.scalar_one_or_none()
        if not agent_type or not agent_type.role_id:
            # No role — only the save_result pseudo-tool is exposed
            return [{"name": "save_result"}]

        allowed_tools = await self._permission_manager.calculate_allowed_tools(
            agent_type.role_id, db
        )

        # Expose tool names only — no descriptions or schemas
        tool_stubs = [{"name": t} for t in sorted(allowed_tools)]
        logger.info(
            "Role-based tool exposure for AgentType %s: %d tools (no descriptions/schemas)",
            agent_type_id,
            len(tool_stubs),
        )
        return tool_stubs

    # ── New async launch path ──────────────────────────────────────────────────

    async def launch(
        self,
        agent_type_id: uuid.UUID,
        input_data: dict[str, Any] | None,
        user_id: uuid.UUID | None,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        Validate agent identity OAuth token, enqueue an agent session, and return the
        session ID synchronously. The actual execution is asynchronous.

        Returns:
            {"session_id": "<uuid>"}

        Raises:
            AgentAuthError: if the agent identity token is missing, expired, or
                the identity type is not permitted by the role.
        """
        await self.validate_agent_identity_token(agent_type_id, db)

        job = await self._session_service.enqueue(
            agent_type_id=agent_type_id,
            input_data=input_data,
            user_id=user_id,
            db=db,
        )
        logger.info(
            "Gateway launch: enqueued session %s for type %s", job.id, agent_type_id
        )
        return {"session_id": str(job.id)}

    # ── Legacy init/request/close path ────────────────────────────────────────

    async def init(
        self,
        agent_type_id: Any,
        initiator_subject: str | None,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Initialize a legacy agent instance and return the session handle."""
        try:
            instance = await self._instance_manager.spawn(
                agent_type_id=agent_type_id,
                initiator_subject=initiator_subject,
                db=db,
            )
            instance = await self._instance_manager.activate(instance.id, db)
        except InstanceLimitError as exc:
            raise ValueError(str(exc))

        _pending_questions[instance.session_handle] = asyncio.Queue()
        _pending_answers[instance.session_handle] = asyncio.Queue()

        logger.info("Gateway init: instance %s, handle=%s", instance.id, instance.session_handle)
        return {
            "session_handle": instance.session_handle,
            "instance_id": str(instance.id),
            "agent_type_id": str(agent_type_id),
        }

    async def request(
        self,
        session_handle: str,
        prompt: str,
        context: dict[str, Any] | None,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Forward a prompt to the legacy agent instance."""
        instance = await self._instance_manager.get_by_handle(session_handle, db)
        if not instance:
            raise ValueError(f"Session handle not found: {session_handle}")
        if instance.status != AgentInstanceStatus.active:
            raise ValueError(f"Instance is not active (status={instance.status})")

        # NOTE: Legacy synchronous execution path. New agents use the async job queue.
        return {
            "response": (
                "This agent type uses the legacy gateway path. "
                "Use POST /api/v1/agents/sessions to launch agents via the async queue."
            ),
            "instance_id": str(instance.id),
            "session_handle": session_handle,
            "has_question": False,
        }

    async def get_question(
        self, session_handle: str, timeout: float = 5.0
    ) -> dict[str, Any]:
        """Long-poll for a pending agent question."""
        queue = _pending_questions.get(session_handle)
        if not queue:
            raise ValueError(f"Session handle not found: {session_handle}")

        try:
            question = await asyncio.wait_for(queue.get(), timeout=timeout)
            return {"question": question, "pending": True}
        except asyncio.TimeoutError:
            return {"question": None, "pending": False}

    async def answer(
        self, session_handle: str, answer_text: str
    ) -> dict[str, Any]:
        """Provide an answer to a pending agent question."""
        queue = _pending_answers.get(session_handle)
        if not queue:
            raise ValueError(f"Session handle not found: {session_handle}")

        await queue.put(answer_text)
        return {"acknowledged": True}

    async def close(
        self, session_handle: str, db: AsyncSession
    ) -> dict[str, Any]:
        """Close the legacy agent instance and clean up the session."""
        instance = await self._instance_manager.get_by_handle(session_handle, db)
        if not instance:
            raise ValueError(f"Session handle not found: {session_handle}")

        await self._instance_manager.close(instance.id, db)

        _pending_questions.pop(session_handle, None)
        _pending_answers.pop(session_handle, None)

        logger.info("Gateway closed session %s (instance %s)", session_handle, instance.id)
        return {"closed": True, "instance_id": str(instance.id)}
