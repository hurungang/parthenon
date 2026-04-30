"""Resource type manifest for the Parthenon platform.

Defines all known resource types and their allowed action sets.
Routers and the Permission Engine import constants from this module
to avoid hardcoding string literals.
"""
from typing import Final

# ── Resource type identifier constants ────────────────────────────────────────

RT_AGENT: Final[str] = "agent"
RT_MCP_SERVER: Final[str] = "mcp_server"
RT_CONVERSATION: Final[str] = "conversation"
RT_GROUP: Final[str] = "group"
RT_USER: Final[str] = "user"
RT_TAG: Final[str] = "tag"
RT_ROLE: Final[str] = "role"
RT_ACCESS_REQUEST: Final[str] = "access_request"
RT_PERMISSIONS: Final[str] = "permissions"
RT_SKILL: Final[str] = "skill"
RT_SCHEDULING: Final[str] = "scheduling"
RT_NOTIFICATION: Final[str] = "notification"

# ── Manifest ──────────────────────────────────────────────────────────────────

ResourceTypeManifest: Final[dict[str, dict[str, list[str]]]] = {
    RT_AGENT: {
        "actions": ["create", "read", "update", "delete", "execute"],
    },
    RT_MCP_SERVER: {
        "actions": ["create", "read", "update", "delete", "execute"],
    },
    RT_CONVERSATION: {
        "actions": ["create", "read", "update", "delete"],
    },
    RT_GROUP: {
        "actions": ["create", "read", "update", "delete", "manage"],
    },
    RT_USER: {
        "actions": ["create", "read", "update", "delete", "manage"],
    },
    RT_TAG: {
        "actions": ["read", "manage"],
    },
    RT_ROLE: {
        "actions": ["read", "manage"],
    },
    RT_ACCESS_REQUEST: {
        "actions": ["create", "read", "approve", "reject"],
    },
    RT_PERMISSIONS: {
        "actions": ["read", "manage"],
    },
    RT_SKILL: {
        "actions": ["create", "read", "update", "delete", "execute"],
    },
    RT_SCHEDULING: {
        "actions": ["create", "read", "update", "delete"],
    },
    RT_NOTIFICATION: {
        "actions": ["read", "manage"],
    },
}
