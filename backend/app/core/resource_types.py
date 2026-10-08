"""Resource type manifest for the Parthenon platform.

Defines all known resource types and their allowed action sets.
Routers and the Permission Engine import constants from this module
to avoid hardcoding string literals.
"""
from typing import Final

# ── Resource type identifier constants (module::submodule) ──────────────────────

# Agents module
RT_AGENT: Final[str] = "agent"
RT_AGENT_ROLES: Final[str] = "agent::roles"
RT_AGENT_IDENTITIES: Final[str] = "agent::identities"
RT_AGENT_MANAGEMENT: Final[str] = "agent::management"
RT_AGENT_RUNTIME_CONTROL: Final[str] = "agent::runtime_control"
RT_AGENT_SKILLS: Final[str] = "agent::skills"
RT_AGENT_SOPS: Final[str] = "agent::sops"
RT_AGENT_MODEL_CONFIGS: Final[str] = "agent::model_configs"
RT_AGENT_SCHEDULES: Final[str] = "agent::schedules"
RT_AGENT_TRAILS: Final[str] = "agent::trails"
RT_AGENT_HUMAN_INTERVENTION: Final[str] = "agent::human_intervention"
RT_AGENT_DATA_TYPES: Final[str] = "agent::data_types"
RT_AGENT_DATA: Final[str] = "agent::data"
RT_AGENT_OUTPUTS: Final[str] = "agent::outputs"

# Integrations module
RT_INTEGRATION_MCP_HUB: Final[str] = "integration::mcp_hub"
RT_INTEGRATION_NOTIFICATIONS: Final[str] = "integration::notifications"

# API Keys — bound to agent identities for external MCP hub access
RT_API_KEYS: Final[str] = "agent::api_keys"

# System module
RT_SYSTEM_OBSERVABILITY: Final[str] = "system::observability"
RT_SYSTEM_PERMISSIONS: Final[str] = "system::permissions"
RT_SYSTEM_CONFIG: Final[str] = "system::system_config"
RT_SYSTEM_SYSTEM_ONE: Final[str] = "system::system_one"
RT_SYSTEM_DECISION_TOOLS: Final[str] = "system::decision_tools"

# Platform module — platform admin console.  These surfaces expose tenant
# METADATA only (never tenant business data) and are hosted at the base
# domain; guarded by platform-admin memberships.
RT_PLATFORM_TENANTS: Final[str] = "platform::tenants"
RT_PLATFORM_SETTINGS: Final[str] = "platform::settings"
RT_PLATFORM_AUDIT: Final[str] = "platform::audit"

# Tenant module — tenant workspace self-service (tenant admins).
RT_TENANT_SETTINGS: Final[str] = "tenant::settings"
RT_TENANT_MEMBERS: Final[str] = "tenant::members"

# ── Manifest ──────────────────────────────────────────────────────────────────

ResourceTypeManifest: Final[dict[str, dict[str, list[str]]]] = {
    RT_API_KEYS: {
        "actions": ["read", "manage"],
    },
    # Bare "agent" gates the agent-type CRUD / session surfaces in
    # agents.py (create/update/delete/execute) — the declared action set
    # mirrors that real usage so presets validated against the manifest
    # can grant it.  (Frontend mirrors only namespaced types.)
    RT_AGENT: {
        "actions": ["create", "read", "update", "delete", "execute"],
    },
    RT_AGENT_ROLES: {
        "actions": ["read", "manage"],
    },
    RT_AGENT_IDENTITIES: {
        "actions": ["read", "manage"],
    },
    RT_AGENT_MANAGEMENT: {
        "actions": ["create", "read", "update", "delete", "execute"],
    },
    RT_AGENT_RUNTIME_CONTROL: {
        "actions": ["read", "execute"],
    },
    RT_AGENT_SKILLS: {
        "actions": ["create", "read", "update", "delete", "execute"],
    },
    RT_AGENT_SOPS: {
        "actions": ["read", "manage"],
    },
    RT_AGENT_MODEL_CONFIGS: {
        "actions": ["read", "manage"],
    },
    RT_AGENT_SCHEDULES: {
        "actions": ["create", "read", "update", "delete"],
    },
    RT_AGENT_TRAILS: {
        "actions": ["create", "read", "update", "delete"],
    },
    RT_AGENT_HUMAN_INTERVENTION: {
        "actions": ["view", "respond"],
    },
    RT_AGENT_DATA_TYPES: {
        "actions": ["create", "read", "update", "delete", "manage"],
    },
    RT_AGENT_DATA: {
        "actions": ["read"],
    },
    RT_AGENT_OUTPUTS: {
        "actions": ["read"],
    },
    RT_INTEGRATION_MCP_HUB: {
        "actions": ["create", "read", "update", "delete", "execute", "manage"],
    },
    RT_INTEGRATION_NOTIFICATIONS: {
        "actions": ["read", "manage"],
    },
    RT_SYSTEM_OBSERVABILITY: {
        "actions": ["read"],
    },
    RT_SYSTEM_PERMISSIONS: {
        "actions": ["create", "read", "update", "delete", "manage", "approve", "reject"],
    },
    RT_SYSTEM_CONFIG: {
        "actions": ["read", "manage"],
    },
    RT_SYSTEM_SYSTEM_ONE: {
        "actions": ["read", "manage"],
    },
    RT_SYSTEM_DECISION_TOOLS: {
        "actions": ["create", "read", "update", "delete", "manage"],
    },
    RT_PLATFORM_TENANTS: {
        "actions": ["create", "read", "update", "delete", "manage"],
    },
    RT_PLATFORM_SETTINGS: {
        "actions": ["read", "manage"],
    },
    RT_PLATFORM_AUDIT: {
        "actions": ["read"],
    },
    RT_TENANT_SETTINGS: {
        "actions": ["read", "manage"],
    },
    RT_TENANT_MEMBERS: {
        "actions": ["create", "read", "update", "delete", "manage"],
    },
}

# ── Module groups ─────────────────────────────────────────────────────────────

MODULE_GROUPS: Final[dict[str, list[str]]] = {
    "agent": [
        RT_API_KEYS,
        RT_AGENT_ROLES,
        RT_AGENT_IDENTITIES,
        RT_AGENT_MANAGEMENT,
        RT_AGENT_RUNTIME_CONTROL,
        RT_AGENT_SKILLS,
        RT_AGENT_SOPS,
        RT_AGENT_MODEL_CONFIGS,
        RT_AGENT_SCHEDULES,
        RT_AGENT_TRAILS,
        RT_AGENT_HUMAN_INTERVENTION,
        RT_AGENT_DATA_TYPES,
        RT_AGENT_DATA,
        RT_AGENT_OUTPUTS,
    ],
    "integration": [
        RT_INTEGRATION_MCP_HUB,
        RT_INTEGRATION_NOTIFICATIONS,
    ],
    "system": [
        RT_SYSTEM_OBSERVABILITY,
        RT_SYSTEM_PERMISSIONS,
        RT_SYSTEM_CONFIG,
        RT_SYSTEM_SYSTEM_ONE,
        RT_SYSTEM_DECISION_TOOLS,
    ],
    "platform": [
        RT_PLATFORM_TENANTS,
        RT_PLATFORM_SETTINGS,
        RT_PLATFORM_AUDIT,
    ],
    "tenant": [
        RT_TENANT_SETTINGS,
        RT_TENANT_MEMBERS,
    ],
}

# ── Helpers ───────────────────────────────────────────────────────────────────


def get_module_from_resource_type(rt: str) -> str | None:
    """Extract the module prefix from a namespaced resource type.

    Returns the portion before ``::``, or ``None`` if the string does not
    contain the delimiter.
    """
    if "::" not in rt:
        return None
    return rt.split("::", 1)[0]


def is_valid_wildcard(value: str) -> bool:
    """Return True if *value* is a valid namespace wildcard.

    Accepts:
        ``*::*`` — match all modules and submodules
        ``agent::*``, ``integration::*``, ``system::*`` — match all submodules
            within a known module
    """
    if value == "*::*":
        return True
    if value.count("::") == 1 and value.endswith("::*"):
        module = value.split("::", 1)[0]
        return module in MODULE_GROUPS
    return False
