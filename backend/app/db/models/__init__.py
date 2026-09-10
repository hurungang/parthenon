"""DB models package — import all models so Alembic autogenerate detects them."""
from app.db.models.identity import Identity, Permission, Role, RolePermission  # noqa: F401
from app.db.models.identity_provider_config import IdentityProviderConfig  # noqa: F401
from app.db.models.identity_provider_config_audit import IdentityProviderConfigAudit  # noqa: F401
from app.db.models.identity_provider_setup_state import IdentityProviderSetupState  # noqa: F401
from app.db.models.mcp_hub import McpServer, McpSession, McpTool, ToolPermission  # noqa: F401
from app.db.models.skills import Skill, SkillToolBinding, Sop, SopStep  # noqa: F401
from app.db.models.agents import (  # noqa: F401
    AgentIdentity,
    AgentInstance,
    AgentJob,
    AgentPlan,
    AgentPlanStatus,
    AgentRole,
    AgentRoleSkill,
    AgentRoleSOP,
    AgentTokenStatus,
    AgentType,
)
from app.db.models.intervene import (  # noqa: F401
    InterveneRequest,
    InterveneRequestStatus,
    InterveneResponse,
    InterventionType,
)
from app.db.models.agent_security import (  # noqa: F401
    AgentCertificateStatus,
    AgentInstanceCertificate,
    CertificateRevocationEntry,
    CertificateValidationLog,
    CertificateValidationOutcome,
    TokenRefreshLog,
    TokenRefreshOutcome,
)
from app.db.models.conversations import (  # noqa: F401
    ConversationSession,
    ConversationTurn,
    ToolCallRecord,
)
from app.db.models.results import ResultRecord  # noqa: F401
from app.db.models.agent_api_key import (  # noqa: F401
    AgentApiKey,
    ApiKeyUsageLog,
    ApiKeyStatus,
    ApiKeyUsageAction,
)
from app.db.models.agent_data_type import AgentDataType  # noqa: F401
from app.db.models.agent_output import (  # noqa: F401
    AgentOutput,
    AgentOutputValidationStatus,
)
from app.db.models.agent_data import AgentData  # noqa: F401
from app.db.models.scheduling import JobExecution, ScheduledJob  # noqa: F401
from app.db.models.notifications import (  # noqa: F401
    ChannelProperty,
    GroupChannelMapping,
    NotificationChannel,
    NotificationEvent,
    NotificationLog,
    RecipientGroup,
)
from app.services.gateway.registry import GatewayEndpointRegistry  # noqa: F401

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
from app.db.models.model_guardrail_configuration import (  # noqa: F401
    ModelGuardrailConfiguration,
    ModelGuardrailPeriod,
    ModelUsageUnit,
)
from app.db.models.model_availability import (  # noqa: F401
    ModelAvailability,
    ModelAvailabilityDisabledReason,
)
from app.db.models.model_guardrail_evaluation import ModelGuardrailEvaluation  # noqa: F401
from app.db.models.model_usage_posture import ModelUsagePosture  # noqa: F401
from app.db.models.guardrail_threshold_event import GuardrailThresholdEvent  # noqa: F401
from app.db.models.agent_run_relationship import AgentRunRelationship  # noqa: F401
from app.db.models.tool_calls import (  # noqa: F401
    RuntimeToolCall,
    RuntimeToolCallRouteType,
    RuntimeToolCallSessionKind,
    RuntimeToolCallStatus,
)
from app.db.models.termination_request import TerminationRequest  # noqa: F401
from app.db.models.termination_cascade_outcome import TerminationCascadeOutcome  # noqa: F401
from app.db.models.sop_recursion_validation_check import SopRecursionValidationCheck  # noqa: F401
from app.db.models.sop_recursion_validation_finding import SopRecursionValidationFinding  # noqa: F401
