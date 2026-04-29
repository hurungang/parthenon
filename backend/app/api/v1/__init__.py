"""API v1 root router — aggregates all domain routers."""
from fastapi import APIRouter

from app.api.v1.user_access_requests import AccessRequestsRouter
from app.api.v1.agents import AgentInstanceRouter, AgentTypeRouter
from app.api.v1.conversations import ConversationRouter
from app.api.v1.user_groups import GroupsRouter
from app.api.v1.identity import IdentityRouter, PermissionRouter, RoleRouter
from app.api.v1.mcp_hub import McpServerRouter, McpSessionRouter, McpToolRouter
from app.api.v1.notifications import NotificationRouter
from app.api.v1.platform_users import PlatformUsersRouter
from app.api.v1.results import ResultRouter
from app.api.v1.user_roles import RolesRouter
from app.api.v1.scheduling import ScheduleRouter
from app.api.v1.setup import SetupRouter
from app.api.v1.skills import SkillRouter
from app.api.v1.sops import SopRouter
from app.api.v1.user_tags import TagsRouter
from app.api.v1.telemetry import TelemetryRouter

router = APIRouter()

# Public endpoints
router.include_router(SetupRouter)

# Identity & auth
router.include_router(RoleRouter)
router.include_router(PermissionRouter)
router.include_router(IdentityRouter)

# MCP Hub
router.include_router(McpServerRouter)
router.include_router(McpSessionRouter)
router.include_router(McpToolRouter)

# Skills & SOPs
router.include_router(SkillRouter)
router.include_router(SopRouter)

# Agents
router.include_router(AgentTypeRouter)
router.include_router(AgentInstanceRouter)

# Supporting modules
router.include_router(ScheduleRouter)
router.include_router(ConversationRouter)
router.include_router(ResultRouter)
router.include_router(NotificationRouter)

# Permission management
router.include_router(TagsRouter)
router.include_router(RolesRouter)
router.include_router(GroupsRouter)
router.include_router(PlatformUsersRouter)
router.include_router(AccessRequestsRouter)

# Telemetry
router.include_router(TelemetryRouter)


@router.get("/ping")
async def ping() -> dict[str, str]:
    """Simple ping endpoint for API v1 liveness check."""
    return {"ping": "pong"}
