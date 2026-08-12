"""API v1 root router — aggregates all domain routers."""
from fastapi import APIRouter

from app.api.v1.api_keys import AdminApiKeyRouter
from app.api.v1.agents import (
    AgentIdentityRouter,
    AgentInstanceRouter,
    AgentJobRouter,
    AgentOAuthRouter,
    AgentRoleRouter,
    AgentTypeRouter,
    ModelAvailabilityRouter,
    ModelConfigRouter,
    ModelUsageGuardrailRouter,
    RuntimeControlRouter,
)
from app.api.v1.certificates import CertificatesRouter
from app.api.v1.conversations import ConversationRouter
from app.api.v1.dashboard import DashboardRouter
from app.api.v1.identity import IdentityRouter, PermissionRouter, RoleRouter
from app.api.v1.internal.agent_data import InternalAgentDataRouter
from app.api.v1.internal.authorization import InternalAuthorizationRouter
from app.api.v1.internal.validate_api_key import InternalAuthRouter
from app.api.v1.internal.bootstrap import InternalBootstrapRouter
from app.api.v1.internal.certificates import InternalCertificatesRouter
from app.api.v1.internal.mcp_proxy import InternalMcpProxyRouter
from app.api.v1.internal.outputs import InternalOutputsRouter
from app.api.v1.internal.session_data import InternalSessionDataRouter
from app.api.v1.internal.system_tools import router as InternalSystemToolsRouter
from app.api.v1.intervene import InterveneRouter
from app.api.v1.mcp_hub import McpOAuthRouter, McpServerRouter, McpSessionRouter, McpToolRouter
from app.api.v1.notifications import NotificationRouter
from app.api.v1.platform_users import PlatformUsersRouter
from app.api.v1.policy import PolicyRouter
from app.api.v1.agent_outputs import OutputRouter
from app.api.v1.agent_data import AgentDataRouter
from app.api.v1.data_types import DataTypeRouter
from app.api.v1.results import ResultRouter
from app.api.v1.scheduling import ScheduleRouter
from app.api.v1.setup import SetupRouter
from app.api.v1.system_config import AuthRouter, SystemConfigRouter
from app.api.v1.skills import SkillRouter
from app.api.v1.sops import SopRouter
from app.api.v1.telemetry import TelemetryRouter
from app.api.v1.user_access_requests import AccessRequestsRouter
from app.api.v1.user_groups import GroupsRouter
from app.api.v1.user_roles import RolesRouter
from app.api.v1.user_tags import TagsRouter

router = APIRouter()

# Public endpoints
router.include_router(SetupRouter)

# Auth endpoints
router.include_router(AuthRouter)

# System Config (identity providers, super admin management)
router.include_router(SystemConfigRouter)

# Dashboard
router.include_router(DashboardRouter)

# Certificate Authority (public CA cert endpoint + admin issue/revoke)
router.include_router(CertificatesRouter)

# Internal service-to-service endpoints (should be network-isolated in production)
router.include_router(InternalAuthRouter)
router.include_router(InternalBootstrapRouter)
router.include_router(InternalCertificatesRouter)
router.include_router(InternalAuthorizationRouter)
router.include_router(InternalAgentDataRouter)
router.include_router(InternalSessionDataRouter)
router.include_router(InternalSystemToolsRouter)
router.include_router(InternalOutputsRouter)
router.include_router(InternalMcpProxyRouter)

# Identity & auth
router.include_router(RoleRouter)
router.include_router(PermissionRouter)
router.include_router(IdentityRouter)

# MCP Hub
router.include_router(McpServerRouter)
router.include_router(McpSessionRouter)
router.include_router(McpOAuthRouter)
router.include_router(McpToolRouter)

# Skills & SOPs
router.include_router(SkillRouter)
router.include_router(SopRouter)

# Agents
router.include_router(AgentRoleRouter)
router.include_router(AgentIdentityRouter)
router.include_router(AgentOAuthRouter)
router.include_router(AgentJobRouter)
router.include_router(AgentTypeRouter)
router.include_router(AgentInstanceRouter)
router.include_router(ModelConfigRouter)
router.include_router(ModelUsageGuardrailRouter)
router.include_router(ModelAvailabilityRouter)
router.include_router(RuntimeControlRouter)

# API Keys
router.include_router(AdminApiKeyRouter)

# Data Types, Agent Data & Agent Outputs
router.include_router(DataTypeRouter)
router.include_router(AgentDataRouter)
router.include_router(OutputRouter)

# Supporting modules
router.include_router(ScheduleRouter)
router.include_router(ConversationRouter)
router.include_router(InterveneRouter)
router.include_router(ResultRouter)
router.include_router(NotificationRouter)

# Permission management
router.include_router(TagsRouter)
router.include_router(RolesRouter)
router.include_router(PolicyRouter)
router.include_router(GroupsRouter)
router.include_router(PlatformUsersRouter)
router.include_router(AccessRequestsRouter)

# Telemetry
router.include_router(TelemetryRouter)


@router.get("/ping")
async def ping() -> dict[str, str]:
    """Simple ping endpoint for API v1 liveness check."""
    return {"ping": "pong"}
