"""DB models package — import all models so Alembic autogenerate detects them."""
from app.db.models.identity import Identity, Permission, Role, RolePermission  # noqa: F401
from app.db.models.identity_provider_config import IdentityProviderConfig  # noqa: F401
from app.db.models.identity_provider_setup_state import IdentityProviderSetupState  # noqa: F401
from app.db.models.mcp_hub import McpServer, McpSession, McpTool, ToolPermission  # noqa: F401
from app.db.models.skills import Skill, SkillToolBinding, Sop, SopStep  # noqa: F401
from app.db.models.agents import (  # noqa: F401
    AgentIdentity,
    AgentInstance,
    AgentJob,
    AgentRole,
    AgentRoleSkill,
    AgentRoleSOP,
    AgentType,
)
from app.db.models.conversations import (  # noqa: F401
    ConversationSession,
    ConversationTurn,
    ToolCallRecord,
)
from app.db.models.results import ResultRecord  # noqa: F401
from app.db.models.scheduling import JobExecution, ScheduledJob  # noqa: F401
from app.db.models.notifications import NotificationChannel, NotificationEvent  # noqa: F401
from app.services.gateway.registry import GatewayRoute  # noqa: F401

# User Permission Management models
from app.db.models.tag_definition import TagDefinition  # noqa: F401
from app.db.models.tag_value import TagValue  # noqa: F401
# Role is imported from identity.py only
from app.db.models.policy_statement import PolicyStatement  # noqa: F401
from app.db.models.policy_action import PolicyAction  # noqa: F401
from app.db.models.policy_resource import PolicyResource  # noqa: F401
from app.db.models.policy_tag_condition import PolicyTagCondition  # noqa: F401
from app.db.models.platform_user import PlatformUser  # noqa: F401
from app.db.models.user_role import UserRole  # noqa: F401
from app.db.models.group import Group  # noqa: F401
from app.db.models.group_role import GroupRole  # noqa: F401
from app.db.models.user_group import UserGroup  # noqa: F401
from app.db.models.access_request_batch import AccessRequestBatch  # noqa: F401
from app.db.models.access_request import AccessRequest  # noqa: F401
from app.db.models.session_logs import ExecutionLogEntry  # noqa: F401
