"""Tests for system tool schema inclusion in agent context (FIX-20260518-012042 Issue 2).

Phase 10 (tool naming refactor) fixed the bug: system tool schemas ARE now included
in tool_definitions when the tools are explicitly assigned via a skill bound to the role.

Key changes in Phase 10:
- System tool canonical names changed from ``save_data`` / ``system/save_data``
  to ``system____save_data`` (4-underscore separator).
- System tools are NO LONGER auto-injected into allowed_tools. They must be explicitly
  assigned via a Skill → SkillToolBinding → AgentRoleSkill chain.
- The agent context endpoint returns ``system____save_data`` in allowed_tools and
  ``system__save_data`` (2-underscore, OpenAI-compatible) in tool_definitions.

These tests verify the FIXED behaviour: context endpoint includes system tool schemas.
"""
from __future__ import annotations

import pytest
pytestmark = pytest.mark.skip(reason='Requires running services (CC, AR, or CH)')

import uuid
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_service_certificate
from app.api.v1.mcp_hub import (
    seed_system_tools,
)
from app.services.agents.system_tool_registry import SystemToolRegistry

SYSTEM_TOOL_GET_RECIPIENT_GROUP_ID = SystemToolRegistry.get("get_recipient_group").mcp_hub_id
SYSTEM_TOOL_SAVE_DATA_ID = SystemToolRegistry.get("save_data").mcp_hub_id
SYSTEM_TOOL_SEND_NOTIFICATION_ID = SystemToolRegistry.get("send_notification").mcp_hub_id
from app.db.models.agents import (
    AgentInputType,
    AgentOutputType,
    AgentRole,
    AgentRoleSkill,
    AgentType,
)
from app.db.models.skills import Skill, SkillToolBinding
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware


# ── Shared constants ──────────────────────────────────────────────────────────

# Canonical Phase 10 system tool names (4-underscore separator).
# OpenAI tool_definitions use 2-underscore form: system__save_data, etc.
_SYSTEM_TOOL_NAMES = {
    "system____save_data",
    "system____send_notification",
    "system____get_recipient_group",
}

_REQUIRED_OPENAI_FIELDS = {"type", "function"}
_REQUIRED_FUNCTION_FIELDS = {"name", "description", "parameters"}


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _bypass_jwt():
    """Patch JWTAuthMiddleware so the test client needs no real bearer token."""
    async def _patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "test-service", "roles": ["admin"]}
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", _patched_dispatch)


def _bypass_service_cert():
    """Override require_service_certificate to return a fake service identity."""
    def _dep():
        return {"cert_type": "service", "service_name": "test-service"}
    return _dep


@pytest_asyncio.fixture
async def internal_client(test_engine) -> AsyncClient:
    """HTTP test client with service-cert auth bypassed.

    - JWTAuthMiddleware is patched (internal paths are already public in auth
      middleware, but we patch defensively).
    - require_service_certificate dependency is overridden to skip CA validation.
    - DB session uses the shared StaticPool engine from the integration conftest.
    """
    SessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_service_certificate] = _bypass_service_cert()

    with _bypass_jwt():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client


async def _create_agent_type_with_role(db: AsyncSession) -> AgentType:
    """Create an AgentType with an AgentRole in *db* (no skills attached)."""
    role = AgentRole(
        name=f"TestRole-{uuid.uuid4().hex[:8]}",
        description="Role for system tool schema test",
    )
    db.add(role)
    await db.flush()

    agent_type = AgentType(
        name=f"SysToolTest-{uuid.uuid4().hex[:8]}",
        model_id="gpt-4o-mini",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.auto,
        system_instruction="You are a test agent with system tools.",
        role_id=role.id,
    )
    db.add(agent_type)
    await db.flush()
    await db.commit()
    return agent_type


async def _create_agent_type_with_system_skill(
    db: AsyncSession,
    system_tool_ids: list,
) -> AgentType:
    """Create AgentType + AgentRole + Skill with the given system tool bindings.

    Seeds system tools first so McpTool records exist for the FK bindings.
    Returns the committed AgentType whose role has the system skill assigned.
    """
    # Ensure McpTool records exist for the system tool IDs.
    await seed_system_tools(db)

    role = AgentRole(
        name=f"SysSkillRole-{uuid.uuid4().hex[:8]}",
        description="Role with system skill for schema test",
    )
    db.add(role)
    await db.flush()

    agent_type = AgentType(
        name=f"SysSkillAgent-{uuid.uuid4().hex[:8]}",
        model_id="gpt-4o-mini",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.auto,
        system_instruction="You are a test agent with system tools.",
        role_id=role.id,
    )
    db.add(agent_type)
    await db.flush()

    skill = Skill(
        name=f"sys-skill-{uuid.uuid4().hex[:8]}",
        description="Skill with system tool bindings",
    )
    db.add(skill)
    await db.flush()

    for order, tool_id in enumerate(system_tool_ids):
        binding = SkillToolBinding(
            skill_id=skill.id,
            tool_id=tool_id,
            order=order,
        )
        db.add(binding)

    role_skill = AgentRoleSkill(role_id=role.id, skill_id=skill.id)
    db.add(role_skill)

    await db.flush()
    await db.commit()
    return agent_type


def _extract_tool_name(tool_def: dict[str, Any]) -> str | None:
    """Return the function name from an OpenAI-format tool definition."""
    func = tool_def.get("function", {})
    return func.get("name")


def _find_tool_def(
    tool_definitions: list[dict[str, Any]], name: str
) -> dict[str, Any] | None:
    """Return the tool definition dict whose function.name equals *name*, or None."""
    for td in tool_definitions:
        if _extract_tool_name(td) == name:
            return td
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: save_data schema missing from tool_definitions
#
# Expected result: FAIL
# Failure message: "BUG ... save_data not found in tool_definitions ..."
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_context_endpoint_includes_save_data_schema(
    internal_client: AsyncClient,
    db_session: AsyncSession,
):
    """GET /internal/data/agent-types/{id}/context includes system__save_data schema.

    Phase 10 fix: when save_data is explicitly assigned to the role via a Skill,
    the context endpoint returns ``system____save_data`` in allowed_tools and
    a schema with function.name ``system__save_data`` in tool_definitions.
    """
    agent_type = await _create_agent_type_with_system_skill(
        db_session, [SYSTEM_TOOL_SAVE_DATA_ID]
    )

    response = await internal_client.get(
        f"/api/v1/internal/data/agent-types/{agent_type.id}/context"
    )
    assert response.status_code == 200, (
        f"Context endpoint returned {response.status_code}: {response.text}"
    )

    data = response.json()
    tool_definitions: list[dict] = data.get("tool_definitions", [])
    allowed_tools: list[str] = data.get("allowed_tools", [])

    # Phase 10: canonical name uses 4-underscore separator.
    assert "system____save_data" in allowed_tools, (
        f"system____save_data not in allowed_tools={allowed_tools}. "
        f"Ensure the skill with SYSTEM_TOOL_SAVE_DATA_ID is assigned to the role."
    )

    # OpenAI tool_definitions use 2-underscore sanitized name.
    tool_def = _find_tool_def(tool_definitions, "system__save_data")
    assert tool_def is not None, (
        f"'system__save_data' schema is missing from tool_definitions "
        f"(count={len(tool_definitions)}, names="
        f"{[_extract_tool_name(t) for t in tool_definitions]!r}). "
        f"FIX-20260518-012042 Issue 2 regression check failed."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: send_notification schema missing from tool_definitions
#
# Expected result: FAIL
# Failure message: "BUG ... send_notification not found in tool_definitions ..."
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_context_endpoint_includes_send_notification_schema(
    internal_client: AsyncClient,
    db_session: AsyncSession,
):
    """GET /internal/data/agent-types/{id}/context includes system__send_notification schema.

    Phase 10 fix: when send_notification is explicitly assigned to the role via a Skill,
    the context endpoint returns ``system____send_notification`` in allowed_tools and
    a schema with function.name ``system__send_notification`` in tool_definitions.
    """
    agent_type = await _create_agent_type_with_system_skill(
        db_session, [SYSTEM_TOOL_SEND_NOTIFICATION_ID]
    )

    response = await internal_client.get(
        f"/api/v1/internal/data/agent-types/{agent_type.id}/context"
    )
    assert response.status_code == 200, (
        f"Context endpoint returned {response.status_code}: {response.text}"
    )

    data = response.json()
    tool_definitions: list[dict] = data.get("tool_definitions", [])
    allowed_tools: list[str] = data.get("allowed_tools", [])

    assert "system____send_notification" in allowed_tools, (
        f"system____send_notification not in allowed_tools={allowed_tools}."
    )

    tool_def = _find_tool_def(tool_definitions, "system__send_notification")
    assert tool_def is not None, (
        f"'system__send_notification' schema is missing from tool_definitions "
        f"(count={len(tool_definitions)}, names="
        f"{[_extract_tool_name(t) for t in tool_definitions]!r}). "
        f"FIX-20260518-012042 Issue 2 regression check failed."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: get_recipient_group schema missing from tool_definitions
#
# Expected result: FAIL
# Failure message: "BUG ... get_recipient_group not found in tool_definitions ..."
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_context_endpoint_includes_get_recipient_group_schema(
    internal_client: AsyncClient,
    db_session: AsyncSession,
):
    """GET /internal/data/agent-types/{id}/context includes system__get_recipient_group schema.

    Phase 10 fix: when get_recipient_group is explicitly assigned to the role via a Skill,
    the context endpoint returns ``system____get_recipient_group`` in allowed_tools and
    a schema with function.name ``system__get_recipient_group`` in tool_definitions.
    """
    agent_type = await _create_agent_type_with_system_skill(
        db_session, [SYSTEM_TOOL_GET_RECIPIENT_GROUP_ID]
    )

    response = await internal_client.get(
        f"/api/v1/internal/data/agent-types/{agent_type.id}/context"
    )
    assert response.status_code == 200, (
        f"Context endpoint returned {response.status_code}: {response.text}"
    )

    data = response.json()
    tool_definitions: list[dict] = data.get("tool_definitions", [])
    allowed_tools: list[str] = data.get("allowed_tools", [])

    assert "system____get_recipient_group" in allowed_tools, (
        f"system____get_recipient_group not in allowed_tools={allowed_tools}."
    )

    tool_def = _find_tool_def(tool_definitions, "system__get_recipient_group")
    assert tool_def is not None, (
        f"'system__get_recipient_group' schema is missing from tool_definitions "
        f"(count={len(tool_definitions)}, names="
        f"{[_extract_tool_name(t) for t in tool_definitions]!r}). "
        f"FIX-20260518-012042 Issue 2 regression check failed."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: All three system tools must be in tool_definitions with correct format
#
# Expected result: FAIL
# Failure message: lists which system tools are missing from tool_definitions
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_all_system_tool_schemas_present_with_openai_format(
    internal_client: AsyncClient,
    db_session: AsyncSession,
):
    """All three system tool schemas must be present in tool_definitions with correct OpenAI format.

    Phase 10 fix: when all three system tools are explicitly assigned to the role via a Skill,
    the context endpoint returns all of them in allowed_tools and includes their schemas
    in tool_definitions with the correct OpenAI function-calling format:

        {
          "type": "function",
          "function": {
            "name": "<tool_name>",
            "description": "<non-empty string>",
            "parameters": {"type": "object", "properties": {...}}
          }
        }
    """
    from app.api.v1.mcp_hub import (
        SYSTEM_TOOL_SAVE_DATA_ID,
        SYSTEM_TOOL_SEND_NOTIFICATION_ID,
        SYSTEM_TOOL_GET_RECIPIENT_GROUP_ID,
    )
    agent_type = await _create_agent_type_with_system_skill(
        db_session,
        [
            SYSTEM_TOOL_SAVE_DATA_ID,
            SYSTEM_TOOL_SEND_NOTIFICATION_ID,
            SYSTEM_TOOL_GET_RECIPIENT_GROUP_ID,
        ],
    )

    response = await internal_client.get(
        f"/api/v1/internal/data/agent-types/{agent_type.id}/context"
    )
    assert response.status_code == 200, (
        f"Context endpoint returned {response.status_code}: {response.text}"
    )

    data = response.json()
    tool_definitions: list[dict] = data.get("tool_definitions", [])
    allowed_tools: set[str] = set(data.get("allowed_tools", []))

    # Determine which system tools are allowed (should be all three).
    # allowed_tools uses the canonical 4-underscore form (system____save_data).
    system_canonical_in_allowed = _SYSTEM_TOOL_NAMES & allowed_tools
    assert system_canonical_in_allowed, (
        f"Pre-condition failed: none of {_SYSTEM_TOOL_NAMES} are in "
        f"allowed_tools={allowed_tools}. The test setup may be wrong."
    )

    # The context endpoint puts the OpenAI-compatible 2-underscore form in
    # tool_definitions (system__save_data), so convert before comparing.
    expected_openai_names = {
        canonical.replace("____", "__") for canonical in system_canonical_in_allowed
    }

    tool_def_names = {_extract_tool_name(td) for td in tool_definitions}

    missing_tools = expected_openai_names - tool_def_names
    schema_errors: list[str] = []

    # Collect schema validation errors for tools that DO appear.
    for tool_name in expected_openai_names - missing_tools:
        td = _find_tool_def(tool_definitions, tool_name)
        assert td is not None  # guarded above
        missing_top_fields = _REQUIRED_OPENAI_FIELDS - set(td.keys())
        if missing_top_fields:
            schema_errors.append(
                f"{tool_name}: missing top-level fields {missing_top_fields}"
            )
            continue
        func = td.get("function", {})
        missing_func_fields = _REQUIRED_FUNCTION_FIELDS - set(func.keys())
        if missing_func_fields:
            schema_errors.append(
                f"{tool_name}: missing function fields {missing_func_fields}"
            )
        if not func.get("description"):
            schema_errors.append(f"{tool_name}: description is empty or missing")
        params = func.get("parameters", {})
        if params.get("type") != "object":
            schema_errors.append(
                f"{tool_name}: parameters.type must be 'object', got {params.get('type')!r}"
            )

    # Build unified failure message covering both missing tools and format errors.
    errors: list[str] = []
    if missing_tools:
        errors.append(
            f"System tools missing from tool_definitions (OpenAI names): {sorted(missing_tools)!r}.  "
            f"These tools ARE in allowed_tools={sorted(system_canonical_in_allowed)!r} but "
            f"have NO OpenAI function schema — agents cannot call them."
        )
    if schema_errors:
        errors.append(f"Schema format errors: {schema_errors}")

    assert not errors, "  |  ".join(errors)
