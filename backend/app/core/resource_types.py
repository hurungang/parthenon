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

# System module
RT_SYSTEM_OBSERVABILITY: Final[str] = "system::observability"
RT_SYSTEM_PERMISSIONS: Final[str] = "system::permissions"
RT_SYSTEM_CONFIG: Final[str] = "system::system_config"

# ── Manifest ──────────────────────────────────────────────────────────────────

ResourceTypeManifest: Final[dict[str, dict[str, list[str]]]] = {
    RT_AGENT: {
        "actions": ["read"],
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
}

# ── Module groups ─────────────────────────────────────────────────────────────

MODULE_GROUPS: Final[dict[str, list[str]]] = {
    "agent": [
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
