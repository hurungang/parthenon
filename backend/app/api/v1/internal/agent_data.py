"""Internal data API for Agent Runtime — serves agent configuration data.

All endpoints require a service certificate (via ``require_service_certificate``).
Agent-instance certificates are blocked by Phase 4 enforcement.

Agent Runtime calls these endpoints to fetch all data it needs to execute
agent sessions without any direct database access.

Routes (all under /internal/data):
  GET /agent-types/{agent_type_id}/plan      — active plan record
  GET /agent-types/{agent_type_id}/context   — full execution context (fat endpoint)
  GET /model-configs/{model_config_id}       — model config with decrypted credentials
"""
from __future__ import annotations

import json
import logging
import uuid
from copy import deepcopy
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import require_service_certificate
from app.db.models.agents import AgentType
from app.db.models.mcp_hub import McpSessionAuthType
from app.db.session import DbSession
from app.services.agents.tool_naming import build_tool_name, parse_tool_name, is_system_tool

logger = logging.getLogger(__name__)

# ── System tool schemas (OpenAI function-calling format) ──────────────────────
# These are always available to agents regardless of role permissions.

_SYSTEM_TOOLS = {
    "system____save_result",
    "system____send_notification",
    "system____get_recipient_group",
}

_SYSTEM_TOOL_SCHEMAS: dict[str, dict] = {
    "save_result": {
        "type": "function",
        "function": {
            "name": "save_result",
            "description": "Save the final result of agent execution to be retrieved later",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The result content to save"},
                    "title": {"type": "string", "description": "Optional title for the result"},
                },
                "required": ["content"],
            },
        },
    },
    "send_notification": {
        "type": "function",
        "function": {
            "name": "send_notification",
            "description": "Send a notification to a recipient group via configured channels",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient_group_id": {
                        "type": "string",
                        "description": "UUID of the recipient group",
                    },
                    "message": {
                        "type": "string",
                        "description": "Notification message content",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "normal", "high"],
                        "description": "Notification priority level",
                    },
                },
                "required": ["recipient_group_id", "message"],
            },
        },
    },
    "get_recipient_group": {
        "type": "function",
        "function": {
            "name": "get_recipient_group",
            "description": "Get information about a notification recipient group",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient_group_id": {
                        "type": "string",
                        "description": "UUID of the recipient group to query",
                    },
                },
                "required": ["recipient_group_id"],
            },
        },
    },
}

InternalAgentDataRouter = APIRouter(
    prefix="/internal/data",
    tags=["internal"],
)


# ── Response schemas ──────────────────────────────────────────────────────────


class AgentPlanResponse(BaseModel):
    """Active plan record for an agent type."""

    agent_type_id: uuid.UUID
    plan_id: uuid.UUID
    plan_steps: list[dict] | None
    topology: dict | None
    generation_status: str
    generated_at: datetime | None


class SopSummary(BaseModel):
    id: uuid.UUID
    name: str


class SkillSummary(BaseModel):
    id: uuid.UUID
    name: str


class AgentContextResponse(BaseModel):
    """Full execution context pre-computed by Control Center.

    Contains everything Agent Runtime needs to execute a session without
    additional database calls.  Identity tokens are never included.
    """

    agent_type_id: uuid.UUID
    system_instruction: str | None
    model_id: str | None
    model_config_id: uuid.UUID | None  # resolved from model_id string
    role_id: uuid.UUID | None
    role_name: str | None
    identity_name: str | None  # name only — never includes tokens
    input_type: str
    output_type: str
    output_schema: dict | None
    primary_sop_id: uuid.UUID | None
    is_active: bool
    identity_role_valid: bool  # False → execution should be refused

    # Pre-computed execution data
    allowed_tools: list[str]
    sop_content: str | None  # formatted SOP text for system instruction
    mcp_session_context: str | None  # formatted MCP context for system instruction
    tool_definitions: list[dict]  # OpenAI-format schemas for allowed tools
    tool_name_map: dict[str, str]  # sanitized_name → original MCP tool name
    role_mcp_sessions: dict[str, dict[str, str]]  # server_id → {session_id, auth_type}
    allowed_agent_types: list[str]  # delegated agent slugs permitted by SOP steps

    # Summaries for execution logging
    sops: list[SopSummary]
    skills: list[SkillSummary]


class ModelConfigResponse(BaseModel):
    """Model configuration with decrypted API credentials.

    ``api_key`` is decrypted at request time.  Use immediately; do not cache.
    """

    id: uuid.UUID
    display_name: str
    provider_type: str
    api_base_url: str | None
    api_key: str | None  # decrypted at call time
    enabled_models: list[str]


class McpSessionResponse(BaseModel):
    """MCP session data for Communication Hub tool routing.
    
    Contains MCP server base URL and authentication headers for calling MCP tools.
    """
    
    session_id: uuid.UUID
    server_id: uuid.UUID
    server_base_url: str
    auth_headers: dict[str, str] = Field(default_factory=dict)
    auth_type: str


def _build_agent_delegation_tool_definition(
    target_agent_type_slug: str,
    target_description: str | None,
    target_input_type: str,
    target_input_schema: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    """Build dynamic delegation tool schema for a specific target agent type."""
    canonical_name = build_tool_name("agent", target_agent_type_slug)
    sanitized_name = canonical_name.replace("____", "__")

    description_parts = [f"Delegate work to agent type '{target_agent_type_slug}'."]
    if target_description:
        description_parts.append(target_description.strip())
    description_parts.append(f"Target input type: {target_input_type}.")

    session_link_property = {
        "session_link_id": {
            "type": "string",
            "description": "Optional existing A2A session link for continuation",
        }
    }

    if target_input_type == "typed":
        if (
            isinstance(target_input_schema, dict)
            and target_input_schema.get("type") == "object"
        ):
            parameters = deepcopy(target_input_schema)
            properties = parameters.setdefault("properties", {})
            if isinstance(properties, dict):
                properties.update(session_link_property)
            else:
                parameters["properties"] = session_link_property
        elif isinstance(target_input_schema, dict) and target_input_schema:
            parameters = {
                "type": "object",
                "properties": {
                    "request_payload": target_input_schema,
                    **session_link_property,
                },
                "required": ["request_payload"],
            }
        else:
            parameters = {
                "type": "object",
                "properties": {
                    "request_payload": {
                        "type": "object",
                        "description": "Payload expected by the delegated typed agent",
                    },
                    **session_link_property,
                },
                "required": ["request_payload"],
            }
    elif target_input_type == "conversation":
        parameters = {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Conversation message to send to the delegated agent",
                },
                **session_link_property,
            },
            "required": ["message"],
        }
    else:
        parameters = {
            "type": "object",
            "properties": {**session_link_property},
        }

    return (
        canonical_name,
        {
            "type": "function",
            "function": {
                "name": sanitized_name,
                "description": " ".join(description_parts),
                "parameters": parameters,
            },
        },
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@InternalAgentDataRouter.get(
    "/agent-types/{agent_type_id}/plan",
    response_model=AgentPlanResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Return the active plan for an agent type",
)
async def get_agent_plan(
    agent_type_id: uuid.UUID,
    db: DbSession,
) -> AgentPlanResponse:
    """Return the successful plan for the given agent type.

    Raises 404 if no successful plan exists.
    """
    from sqlalchemy import select

    from app.db.models.agents import AgentPlan, AgentPlanStatus

    result = await db.execute(
        select(AgentPlan).where(
            AgentPlan.agent_type_id == agent_type_id,
            AgentPlan.generation_status == AgentPlanStatus.success,
        )
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(
            status_code=404,
            detail=f"No successful plan found for agent_type {agent_type_id}",
        )

    return AgentPlanResponse(
        agent_type_id=plan.agent_type_id,
        plan_id=plan.id,
        plan_steps=plan.plan_steps,
        topology=plan.topology,
        generation_status=plan.generation_status.value,
        generated_at=plan.generated_at,
    )


@InternalAgentDataRouter.get(
    "/agent-types/{agent_type_id}/context",
    response_model=AgentContextResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Return full execution context for an agent type",
)
async def get_agent_context(
    agent_type_id: uuid.UUID,
    db: DbSession,
) -> AgentContextResponse:
    """Return the full execution context for an agent type.

    Pre-computes allowed tools, SOP content, MCP session context, tool
    definitions, and role MCP session map so Agent Runtime needs no direct
    database access during execution.

    Identity tokens are never returned.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db.models.agents import (
        AgentIdentity,
        AgentInputType,
        AgentRole,
        AgentRoleIdentity,
        AgentRoleMcpSession,
        AgentRoleSOP,
        AgentRoleSkill,
        AgentType,
        ModelConfig,
    )
    from app.db.models.mcp_hub import McpSession, McpTool
    from app.db.models.skills import Skill, SkillToolBinding, Sop, SopStep, SopStepType

    agent_type = await db.get(AgentType, agent_type_id)
    if agent_type is None:
        raise HTTPException(
            status_code=404, detail=f"AgentType {agent_type_id} not found"
        )

    # ── Identity and role info ────────────────────────────────────────────────
    identity_name: str | None = None
    role_name: str | None = None
    identity_role_valid: bool = True

    if agent_type.identity_id:
        identity = await db.get(AgentIdentity, agent_type.identity_id)
        identity_name = identity.name if identity else None

    if agent_type.role_id:
        role = await db.get(AgentRole, agent_type.role_id)
        role_name = role.name if role else None

    if agent_type.identity_id and agent_type.role_id:
        check = await db.execute(
            select(AgentRoleIdentity).where(
                AgentRoleIdentity.role_id == agent_type.role_id,
                AgentRoleIdentity.identity_id == agent_type.identity_id,
            )
        )
        identity_role_valid = check.scalar_one_or_none() is not None

    # ── Resolve allowed tools ─────────────────────────────────────────────────
    allowed_tools: set[str] = set()
    resolved_tool_names_raw: set[str] = set()
    skill_ids: set[uuid.UUID] = set()
    sops_summary: list[SopSummary] = []
    skills_summary: list[SkillSummary] = []
    allowed_agent_types: set[str] = set()
    delegated_agent_type_metadata: dict[str, dict[str, Any]] = {}

    if agent_type.role_id:
        role_id = agent_type.role_id

        # Directly assigned skills
        direct_rows = await db.execute(
            select(AgentRoleSkill.skill_id, Skill.name)
            .join(Skill, AgentRoleSkill.skill_id == Skill.id)
            .where(AgentRoleSkill.role_id == role_id)
        )
        for skill_id, skill_name in direct_rows.fetchall():
            skill_ids.add(skill_id)
            skills_summary.append(SkillSummary(id=skill_id, name=skill_name))

        # SOPs and their step-referenced skills
        sop_rows = await db.execute(
            select(AgentRoleSOP.sop_id, Sop.name)
            .join(Sop, AgentRoleSOP.sop_id == Sop.id)
            .where(AgentRoleSOP.role_id == role_id)
        )
        sop_ids: list[uuid.UUID] = []
        for sop_id, sop_name in sop_rows.fetchall():
            sop_ids.append(sop_id)
            sops_summary.append(SopSummary(id=sop_id, name=sop_name))

        if sop_ids:
            step_rows = await db.execute(
                select(SopStep.skill_id, Skill.name)
                .join(Skill, SopStep.skill_id == Skill.id)
                .where(
                    SopStep.sop_id.in_(sop_ids),
                    SopStep.step_type == SopStepType.skill_invocation,
                    SopStep.skill_id.isnot(None),
                )
            )
            for skill_id, skill_name in step_rows.fetchall():
                if skill_id not in skill_ids:
                    skill_ids.add(skill_id)
                    skills_summary.append(SkillSummary(id=skill_id, name=skill_name))

            delegation_rows = await db.execute(
                select(
                    AgentType.name,
                    AgentType.description,
                    AgentType.input_type,
                    AgentType.input_schema,
                )
                .select_from(SopStep)
                .join(AgentType, AgentType.id == SopStep.target_agent_type_id)
                .where(
                    SopStep.sop_id.in_(sop_ids),
                    SopStep.step_type == SopStepType.agent_delegation,
                    SopStep.target_agent_type_id.isnot(None),
                    AgentType.is_active.is_(True),
                )
            )
            for (
                agent_type_name,
                agent_type_description,
                agent_input_type,
                agent_input_schema,
            ) in delegation_rows.fetchall():
                if agent_type_name:
                    allowed_agent_types.add(agent_type_name)
                    delegated_agent_type_metadata[agent_type_name] = {
                        "description": agent_type_description,
                        "input_type": (
                            agent_input_type.value
                            if isinstance(agent_input_type, AgentInputType)
                            else str(agent_input_type)
                        ),
                        "input_schema": agent_input_schema,
                    }

        # Tool identifiers from skill → tool bindings
        if skill_ids:
            tool_rows = await db.execute(
                select(McpTool.name)
                .join(SkillToolBinding, SkillToolBinding.tool_id == McpTool.id)
                .where(
                    SkillToolBinding.skill_id.in_(skill_ids),
                    McpTool.is_active.is_(True),
                )
            )
            for (tool_name,) in tool_rows.fetchall():
                resolved_tool_names_raw.add(tool_name)
                allowed_tools.add(_canonicalize_tool_identifier(tool_name))

    # ── Tool definitions (OpenAI format) ─────────────────────────────────────
    tool_definitions: list[dict[str, Any]] = []
    tool_name_map: dict[str, str] = {}

    mcp_tool_names = sorted(resolved_tool_names_raw)
    if mcp_tool_names:
        mcp_rows = await db.execute(
            select(McpTool).where(
                McpTool.name.in_(mcp_tool_names),
                McpTool.is_active.is_(True),
            )
        )
        for tool in mcp_rows.scalars().all():
            canonical_tool_name = _canonicalize_tool_identifier(tool.name)
            sanitized = canonical_tool_name.replace("____", "__")
            tool_name_map[sanitized] = canonical_tool_name
            tool_definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": sanitized,
                        "description": tool.description or f"Tool: {tool.name}",
                        "parameters": tool.input_schema or {"type": "object", "properties": {}},
                    },
                }
            )

    # Add system tool schemas only when they are explicitly present in allowed_tools.
    for tool_name in sorted(allowed_tools):
        try:
            server, bare_tool = parse_tool_name(tool_name)
        except ValueError:
            continue
        if server != "system":
            continue
        if bare_tool in _SYSTEM_TOOL_SCHEMAS:
            tool_definitions.append(_SYSTEM_TOOL_SCHEMAS[bare_tool])

    if allowed_agent_types:
        for target_slug in sorted(allowed_agent_types):
            target_meta = delegated_agent_type_metadata.get(target_slug, {})
            canonical_tool_name, definition = _build_agent_delegation_tool_definition(
                target_agent_type_slug=target_slug,
                target_description=target_meta.get("description"),
                target_input_type=str(target_meta.get("input_type") or "typed"),
                target_input_schema=target_meta.get("input_schema"),
            )
            allowed_tools.add(canonical_tool_name)
            sanitized = canonical_tool_name.replace("____", "__")
            tool_name_map[sanitized] = canonical_tool_name
            tool_definitions.append(definition)

    # ── SOP content (pre-formatted for system instruction) ───────────────────
    sop_content: str | None = None
    if agent_type.primary_sop_id:
        sop_content = await _build_sop_content(agent_type.primary_sop_id, db)

    # ── MCP session context (pre-formatted for system instruction) ───────────
    mcp_session_context: str | None = None
    if agent_type.role_id:
        mcp_session_context = await _build_mcp_session_context(agent_type.role_id, db)

    # ── Role MCP session map (for tool dispatch) ─────────────────────────────
    role_mcp_sessions: dict[str, dict[str, str]] = {}
    if agent_type.role_id:
        session_rows = await db.execute(
            select(McpSession.id, McpSession.server_id, McpSession.auth_type)
            .join(AgentRoleMcpSession, AgentRoleMcpSession.mcp_session_id == McpSession.id)
            .where(
                AgentRoleMcpSession.role_id == agent_type.role_id,
                McpSession.is_active.is_(True),
            )
        )
        for row in session_rows.all():
            role_mcp_sessions[str(row.server_id)] = {
                "session_id": str(row.id),
                "auth_type": row.auth_type.value,
            }

    # ── Resolve model_config_id from model_id string ─────────────────────────
    model_config_id: uuid.UUID | None = None
    if agent_type.model_id:
        mc_rows = await db.execute(select(ModelConfig))
        for mc in mc_rows.scalars().all():
            if agent_type.model_id in (mc.enabled_models or []):
                model_config_id = mc.id
                break

    return AgentContextResponse(
        agent_type_id=agent_type.id,
        system_instruction=agent_type.system_instruction,
        model_id=agent_type.model_id,
        model_config_id=model_config_id,
        role_id=agent_type.role_id,
        role_name=role_name,
        identity_name=identity_name,
        input_type=agent_type.input_type.value,
        output_type=agent_type.output_type.value,
        output_schema=agent_type.output_schema,
        primary_sop_id=agent_type.primary_sop_id,
        is_active=agent_type.is_active,
        identity_role_valid=identity_role_valid,
        allowed_tools=sorted(allowed_tools),
        sop_content=sop_content,
        mcp_session_context=mcp_session_context,
        tool_definitions=tool_definitions,
        tool_name_map=tool_name_map,
        role_mcp_sessions=role_mcp_sessions,
        allowed_agent_types=sorted(allowed_agent_types),
        sops=sops_summary,
        skills=skills_summary,
    )


def _canonicalize_tool_identifier(tool_identifier: str) -> str:
    """Normalize legacy and display formats to canonical ``server____tool`` form."""
    if tool_identifier.startswith("system____"):
        return tool_identifier

    if tool_identifier.startswith("system__"):
        return build_tool_name("system", tool_identifier[len("system__"):])

    if tool_identifier.startswith("system/"):
        return build_tool_name("system", tool_identifier[len("system/"):])

    if is_system_tool(tool_identifier):
        try:
            server, tool = parse_tool_name(tool_identifier)
            return build_tool_name(server, tool)
        except ValueError:
            return build_tool_name("system", tool_identifier)

    try:
        server, tool = parse_tool_name(tool_identifier)
        return build_tool_name(server, tool)
    except ValueError:
        if "/" in tool_identifier:
            server, tool = tool_identifier.split("/", 1)
            return build_tool_name(server, tool)
        return tool_identifier


@InternalAgentDataRouter.get(
    "/model-configs/{model_config_id}",
    response_model=ModelConfigResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Return model configuration with decrypted credentials",
)
async def get_model_config(
    model_config_id: uuid.UUID,
    db: DbSession,
) -> ModelConfigResponse:
    """Return model configuration with decrypted API credentials.

    Credentials are decrypted at request time. Callers must use the key
    immediately and must not cache or log it.
    """
    from app.core.credential_vault import get_vault
    from app.db.models.agents import ModelConfig

    config = await db.get(ModelConfig, model_config_id)
    if config is None:
        raise HTTPException(
            status_code=404, detail=f"ModelConfig {model_config_id} not found"
        )

    api_key: str | None = None
    if config.encrypted_api_key:
        try:
            vault = get_vault()
            decrypted = vault.decrypt(config.encrypted_api_key)
            parsed = json.loads(decrypted)
            api_key = parsed.get("api_key")
        except Exception as exc:
            logger.error(
                "Failed to decrypt api_key for ModelConfig %s: %s", model_config_id, exc
            )
            raise HTTPException(
                status_code=500, detail="Failed to decrypt model credentials"
            )

    return ModelConfigResponse(
        id=config.id,
        display_name=config.display_name,
        provider_type=config.provider_type.value,
        api_base_url=config.api_base_url,
        api_key=api_key,
        enabled_models=config.enabled_models or [],
    )


async def _get_agent_identity_jwt(
    agent_type: "AgentType", db: DbSession
) -> str | None:
    """Retrieve the decrypted access token for the agent identity bound to an AgentType.
    
    Automatically refreshes the token if it is expired or expiring within 5 minutes.
    Returns None if the identity has no token, refresh fails, or decryption fails.
    """
    from datetime import datetime, timezone
    from app.db.models.agents import AgentIdentity
    from app.core.credential_vault import get_vault
    from app.services.token_refresh import (
        check_token_expiration,
        refresh_oauth_token,
        TokenRefreshError,
    )
    
    if not agent_type.identity_id:
        logger.debug("AgentType %s has no identity_id", agent_type.id)
        return None

    identity = await db.get(AgentIdentity, agent_type.identity_id)
    if not identity:
        logger.debug("AgentIdentity %s not found", agent_type.identity_id)
        return None

    # Check if token needs refresh BEFORE decrypting
    try:
        if await check_token_expiration(identity.id, db):
            logger.info(
                "Agent identity %s token expired or expiring soon, refreshing...",
                identity.id,
            )
            try:
                await refresh_oauth_token(identity.id, db)
                await db.commit()
                await db.refresh(identity)
            except TokenRefreshError as exc:
                logger.error(
                    "Token refresh failed for agent identity %s: %s",
                    identity.id,
                    exc,
                )
                return None
    except Exception as exc:
        logger.warning("Failed to check token expiration: %s", exc)
        # Continue anyway - try to use existing token

    if not identity.access_token:
        logger.debug("Identity %s has no access_token", identity.id)
        return None

    try:
        vault = get_vault()
        decrypted = vault.decrypt(identity.access_token)
        return decrypted
    except Exception as exc:
        logger.warning("Failed to decrypt agent identity token: %s", exc)
        return None


@InternalAgentDataRouter.get(
    "/mcp-sessions/{server_slug}",
    response_model=McpSessionResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Return MCP session data for Communication Hub tool routing",
)
async def get_mcp_session_for_tool_routing(
    server_slug: str,
    agent_type_id: uuid.UUID,
    session_id: uuid.UUID,
    db: DbSession,
) -> McpSessionResponse:
    """Return MCP session details for Communication Hub to route tool calls.
    
    MCP sessions are associated with Agent Roles, not users. The flow is:
    AgentJob → AgentType → AgentRole → AgentRoleMcpSession → McpSession
    
    Args:
        server_slug: MCP server slug (e.g., "supabase", "hello-world")
        agent_type_id: Agent type ID to find the role
        session_id: Agent job session ID for validation
        db: Database session
        
    Returns:
        MCP session data with server URL and auth headers for the agent role
        
    Raises:
        HTTPException: 404 if server, agent type, role, or MCP session not found
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    
    from app.db.models.agents import AgentJob, AgentType, AgentRoleMcpSession
    from app.db.models.mcp_hub import McpServer, McpSession
    from app.core.credential_vault import get_vault
    
    # 1. Validate that the session exists (for logging/debugging)
    agent_job = await db.get(AgentJob, session_id)
    if agent_job is None:
        raise HTTPException(
            status_code=404, 
            detail=f"Agent session {session_id} not found"
        )
    
    # 2. Get the agent type to find its role
    agent_type = await db.get(AgentType, agent_type_id)
    if agent_type is None:
        raise HTTPException(
            status_code=404,
            detail=f"AgentType {agent_type_id} not found"
        )
    
    if agent_type.role_id is None:
        raise HTTPException(
            status_code=400,
            detail=f"AgentType '{agent_type.name}' has no associated role"
        )
    
    if agent_type.role_id is None:
        raise HTTPException(
            status_code=400,
            detail=f"AgentType '{agent_type.name}' has no associated role"
        )
    
    role_id = agent_type.role_id
    
    # 3. Find MCP server by slug
    result = await db.execute(
        select(McpServer)
        .where(McpServer.slug == server_slug)
    )
    server = result.scalar_one_or_none()
    
    if server is None:
        raise HTTPException(
            status_code=404,
            detail=f"MCP server '{server_slug}' not found"
        )
    
    # 4. Find the MCP session assigned to this role for this server
    result = await db.execute(
        select(AgentRoleMcpSession)
        .where(AgentRoleMcpSession.role_id == role_id)
        .where(AgentRoleMcpSession.server_id == server.id)
        .options(selectinload(AgentRoleMcpSession.mcp_session))
    )
    role_mcp_session = result.scalar_one_or_none()
    
    if role_mcp_session is None:
        raise HTTPException(
            status_code=404,
            detail=f"No MCP session assigned to role {role_id} for server '{server_slug}'"
        )
    
    mcp_session = role_mcp_session.mcp_session
    
    mcp_session = role_mcp_session.mcp_session
    
    # 5. Build response with server URL and auth headers
    server_base_url = server.base_url or f"http://localhost:3000/{server_slug}"
    auth_headers: dict[str, str] = {}
    
    # Handle passthrough sessions: use agent identity JWT
    if mcp_session.auth_type == McpSessionAuthType.passthrough:
        logger.info(
            "Passthrough session detected for server '%s', attempting to get agent identity JWT...",
            server_slug,
        )
        # Get agent identity JWT for passthrough sessions
        agent_jwt = await _get_agent_identity_jwt(agent_type, db)
        if agent_jwt:
            auth_headers["Authorization"] = f"Bearer {agent_jwt}"
            token_preview = f"{agent_jwt[:30]}...{agent_jwt[-10:]}" if len(agent_jwt) > 50 else f"{agent_jwt[:40]}..."
            logger.info(
                "Passthrough session for server '%s': using agent identity JWT (preview: %s)",
                server_slug,
                token_preview,
            )
        else:
            logger.warning(
                "Passthrough session for server '%s' but no agent identity JWT available (identity_id=%s)",
                server_slug,
                agent_type.identity_id,
            )
    # Decrypt credentials if present (for non-passthrough sessions)
    elif mcp_session.encrypted_credentials:
        try:
            vault = get_vault()
            decrypted_creds = vault.decrypt(mcp_session.encrypted_credentials)
            creds_dict = json.loads(decrypted_creds)
            
            # Build auth headers based on auth_type
            if mcp_session.auth_type.value == "api_key":
                # Assume API key in Authorization header
                api_key = creds_dict.get("api_key", "")
                if api_key:
                    auth_headers["Authorization"] = f"Bearer {api_key}"
            elif mcp_session.auth_type.value == "basic_auth":
                import base64
                username = creds_dict.get("username", "")
                password = creds_dict.get("password", "")
                credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
                auth_headers["Authorization"] = f"Basic {credentials}"
            elif mcp_session.auth_type.value == "oauth2":
                # OAuth2: use access_token from stored credentials
                access_token = creds_dict.get("access_token", "")
                logger.info(
                    "OAuth2 credentials for server '%s': has_access_token=%s",
                    server_slug,
                    bool(access_token),
                )
                if access_token:
                    auth_headers["Authorization"] = f"Bearer {access_token}"
                else:
                    logger.warning(
                        "OAuth2 session for server '%s' has no access_token in credentials",
                        server_slug,
                    )
            # passthrough auth type: no credentials needed, auth_headers remains empty
            
        except Exception as exc:
            logger.error(
                "Failed to decrypt credentials for MCP session %s: %s",
                mcp_session.id,
                exc
            )
            # Continue without credentials - some sessions may not need them
    
    # Log what we're returning for debugging
    auth_header_preview = ""
    if "Authorization" in auth_headers:
        auth_value = auth_headers["Authorization"]
        # Mask sensitive token data
        if len(auth_value) > 50:
            auth_header_preview = f"{auth_value[:30]}...{auth_value[-10:]}"
        else:
            auth_header_preview = f"{auth_value[:20]}..."
    
    logger.info(
        "MCP session data for server '%s': session_id=%s auth_type=%s has_auth_header=%s auth_preview=%s",
        server_slug,
        mcp_session.id,
        mcp_session.auth_type.value,
        "Authorization" in auth_headers,
        auth_header_preview if auth_headers else "N/A",
    )
    
    return McpSessionResponse(
        session_id=mcp_session.id,
        server_id=server.id,
        server_base_url=server_base_url,
        auth_headers=auth_headers,
        auth_type=mcp_session.auth_type.value,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────


async def _build_sop_content(primary_sop_id: uuid.UUID, db: Any) -> str | None:
    """Load a SOP and format its steps as instruction text."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db.models.skills import Sop

    try:
        result = await db.execute(
            select(Sop)
            .where(Sop.id == primary_sop_id)
            .options(selectinload(Sop.steps))
        )
        sop = result.scalar_one_or_none()
        if not sop:
            return None

        lines: list[str] = [f"Follow this SOP to complete the task: {sop.name}"]
        if sop.description:
            lines.append(f"\nDescription: {sop.description}")
        if sop.instructions:
            lines.append(f"\nInstructions: {sop.instructions}")

        steps = sorted(sop.steps, key=lambda s: s.order)
        if steps:
            lines.append("\nSteps:")
            for step in steps:
                step_num = step.order + 1
                step_text = f"{step_num}."
                if step.name:
                    step_text += f" {step.name}"
                if step.description:
                    step_text += f": {step.description}"
                lines.append(step_text)

        return "\n".join(lines)
    except Exception as exc:
        logger.warning("Failed to build SOP content for %s: %s", primary_sop_id, exc)
        return None


async def _build_mcp_session_context(role_id: uuid.UUID, db: Any) -> str | None:
    """Load MCP sessions for a role and format as context text."""
    from sqlalchemy import select

    from app.db.models.agents import AgentRoleMcpSession
    from app.db.models.mcp_hub import McpServer, McpSession

    try:
        result = await db.execute(
            select(McpSession, McpServer)
            .join(AgentRoleMcpSession, AgentRoleMcpSession.mcp_session_id == McpSession.id)
            .join(McpServer, McpServer.id == McpSession.server_id)
            .where(AgentRoleMcpSession.role_id == role_id)
            .where(McpSession.is_active.is_(True))
            .order_by(McpServer.name, McpSession.name)
        )
        pairs = list(result.all())
        if not pairs:
            return None

        lines: list[str] = [
            "## Available MCP Resources",
            "",
            "You have access to the following MCP connectors with pre-configured sessions:",
            "",
        ]
        for session, server in pairs:
            lines.append(f"### {server.name} ({server.slug})")
            if session.description:
                lines.append(f"Description: {session.description}")
            if session.credential_config:
                cfg = session.credential_config
                if isinstance(cfg, dict) and cfg.get("parameters"):
                    lines.append("Pre-configured parameters:")
                    for k, v in cfg["parameters"].items():
                        lines.append(f"  - {k}: {v}")
            if session.identity_binding:
                binding = session.identity_binding
                if isinstance(binding, dict):
                    if binding.get("project_id"):
                        lines.append(f"Project ID: {binding['project_id']}")
                    if binding.get("region"):
                        lines.append(f"Region: {binding['region']}")
                    if binding.get("environment"):
                        lines.append(f"Environment: {binding['environment']}")
            lines.append(f"Authentication: {session.auth_type.value}")
            lines.append(f"Status: Active")
            lines.append("")

        lines.append(
            "**Note:** You have valid authentication for these connectors. "
            "Use the associated tools directly - credentials are handled automatically."
        )
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("Failed to build MCP session context for role %s: %s", role_id, exc)
        return None
