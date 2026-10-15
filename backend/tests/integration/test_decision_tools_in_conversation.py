"""Decision tools must surface in conversational agents' toolsets.

Regression: decision tools have no ``mcp_tools`` row (skill bindings store
a deterministic uuid5 virtual id), so the skill-binding → tools resolution
INNER JOINs against ``mcp_tools`` silently dropped decision-tool bindings.
These tests verify the resolution now includes ``decision____<name>`` in
allowed_tools and emits OpenAI-style definitions — tenant-strict.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from tests.integration._strict_tenant_utils import (  # noqa: F401
    create_two_tenants,
    db,
    make_module_schema_fixture,
)

_schema = make_module_schema_fixture()


async def _create_decision_tool(db, tenant_id, name: str, enabled: bool = True):
    from app.db.models.agent_data_type import AgentDataType
    from app.db.models.decision_tools import DecisionTool, DecisionToolQuestion

    input_type_id = output_type_id = None
    if enabled:
        # Readiness gate: enabled tools need BOTH data types.
        suffix = uuid.uuid4().hex[:6]
        input_type = AgentDataType(
            tenant_id=tenant_id,
            name=f"{name}-input-{suffix}",
            slug=f"{name}-input-{suffix}",
            fields=[{"name": "situation", "type": "string"}],
        )
        output_type = AgentDataType(
            tenant_id=tenant_id,
            name=f"{name}-output-{suffix}",
            slug=f"{name}-output-{suffix}",
            fields=[{"name": "decision", "type": "string"}],
        )
        db.add_all([input_type, output_type])
        await db.flush()
        input_type_id = input_type.id
        output_type_id = output_type.id

    tool = DecisionTool(
        tenant_id=tenant_id,
        name=name,
        purpose=f"Decide {name}",
        input_data_type_id=input_type_id,
        output_data_type_id=output_type_id,
        enabled=enabled,
    )
    tool.questions.append(
        DecisionToolQuestion(
            question_key="approve",
            question_type="choice",
            instructions="Approve?",
            criteria_options={"yes": "approve", "no": "reject"},
            ordering=0,
        )
    )
    db.add(tool)
    await db.commit()
    await db.refresh(tool)
    return tool


async def _create_skill_with_decision_binding(db, tenant_id, decision_tool):
    from app.db.models.skills import Skill, SkillToolBinding
    from app.services.system_one.decision_tool_service import (
        decision_tool_virtual_tool_id,
    )

    skill = Skill(name=f"skill-{decision_tool.name}-{uuid.uuid4().hex[:6]}")
    if hasattr(Skill, "tenant_id"):
        skill.tenant_id = tenant_id
    db.add(skill)
    await db.flush()
    db.add(
        SkillToolBinding(
            skill_id=skill.id,
            tool_id=decision_tool_virtual_tool_id(decision_tool.id),
        )
    )
    await db.commit()
    await db.refresh(skill)
    return skill


async def _create_agent_with_role_and_skill(db, tenant_id, skill, name: str):
    from app.db.models.agents import (
        AgentInputType,
        AgentOutputType,
        AgentRole,
        AgentRoleSkill,
        AgentType,
    )

    role = AgentRole(name=name, description=name)
    if hasattr(AgentRole, "tenant_id"):
        role.tenant_id = tenant_id
    db.add(role)
    await db.flush()
    db.add(AgentRoleSkill(role_id=role.id, skill_id=skill.id))
    agent_type = AgentType(
        tenant_id=tenant_id,
        name=name,
        role_id=role.id,
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.auto,
    )
    db.add(agent_type)
    await db.commit()
    await db.refresh(agent_type)
    return agent_type


class TestDecisionToolsInAgentContext:
    async def test_decision_binding_included_in_context(self, db):
        """(i) decision tool binding → decision____<name> in allowed_tools
        AND a definition in tool_definitions."""
        from app.api.v1.internal.agent_data import get_agent_context
        from app.db.tenant_scoping import apply_tenant_scope

        tenant, _ = await create_two_tenants(db)
        tool = await _create_decision_tool(db, tenant.id, "approve-loan")
        skill = await _create_skill_with_decision_binding(db, tenant.id, tool)
        agent_type = await _create_agent_with_role_and_skill(
            db, tenant.id, skill, "conv-agent-a"
        )

        apply_tenant_scope(db, tenant.id)
        ctx = await get_agent_context(agent_type_id=agent_type.id, db=db)

        assert "decision____approve-loan" in ctx.allowed_tools
        defs = [d for d in ctx.tool_definitions if "approve" in d["function"]["name"]]
        assert len(defs) == 1
        definition = defs[0]
        assert definition["type"] == "function"
        assert definition["function"]["name"] == "decision__approve_loan" or (
            "approve" in definition["function"]["name"]
        )
        assert definition["function"]["description"]
        assert "Decide approve-loan" in definition["function"]["description"]
        # parameters derive from the questions schema (no input data type)
        params = definition["function"]["parameters"]
        assert params.get("type") == "object"
        # tool_name_map maps the sanitized name back to the canonical name
        assert any(v == "decision____approve-loan" for v in ctx.tool_name_map.values())

    async def test_other_tenants_decision_tool_not_included(self, db):
        """(ii) another tenant's decision tool is NOT included."""
        from app.api.v1.internal.agent_data import get_agent_context
        from app.db.tenant_scoping import apply_tenant_scope

        tenant_a, tenant_b = await create_two_tenants(db)
        tool_b = await _create_decision_tool(db, tenant_b.id, "b-only-tool")
        skill_b = await _create_skill_with_decision_binding(db, tenant_b.id, tool_b)
        agent_type = await _create_agent_with_role_and_skill(
            db, tenant_a.id, skill_b, "conv-agent-cross"
        )

        apply_tenant_scope(db, tenant_a.id)
        ctx = await get_agent_context(agent_type_id=agent_type.id, db=db)

        assert "decision____b-only-tool" not in ctx.allowed_tools
        assert not [
            d
            for d in ctx.tool_definitions
            if "b-only-tool" in d["function"]["name"]
        ]

    async def test_disabled_decision_tool_not_included(self, db):
        """(iii) a disabled decision tool is NOT included."""
        from app.api.v1.internal.agent_data import get_agent_context
        from app.db.tenant_scoping import apply_tenant_scope

        tenant, _ = await create_two_tenants(db)
        tool = await _create_decision_tool(db, tenant.id, "off-tool", enabled=False)
        skill = await _create_skill_with_decision_binding(db, tenant.id, tool)
        agent_type = await _create_agent_with_role_and_skill(
            db, tenant.id, skill, "conv-agent-off"
        )

        apply_tenant_scope(db, tenant.id)
        ctx = await get_agent_context(agent_type_id=agent_type.id, db=db)

        assert "decision____off-tool" not in ctx.allowed_tools
        assert not [
            d for d in ctx.tool_definitions if "off-tool" in d["function"]["name"]
        ]


class TestPermissionManagerResolvesDecisionTools:
    async def test_resolve_tools_from_skills_includes_decision_name(self, db):
        """(iv) permission manager resolves the decision____<name> so the
        per-call permission gate does not deny it."""
        from app.db.tenant_scoping import apply_tenant_scope
        from app.services.agents.permission_manager import AgentPermissionManager

        tenant, _ = await create_two_tenants(db)
        tool = await _create_decision_tool(db, tenant.id, "gate-tool")
        skill = await _create_skill_with_decision_binding(db, tenant.id, tool)

        apply_tenant_scope(db, tenant.id)
        allowed = await AgentPermissionManager()._resolve_tools_from_skills(
            {skill.id}, db
        )

        assert "decision____gate-tool" in allowed

    async def test_other_tenants_decision_tool_not_resolved(self, db):
        from app.db.tenant_scoping import apply_tenant_scope
        from app.services.agents.permission_manager import AgentPermissionManager

        tenant_a, tenant_b = await create_two_tenants(db)
        tool_b = await _create_decision_tool(db, tenant_b.id, "b-gate-tool")
        skill_b = await _create_skill_with_decision_binding(db, tenant_b.id, tool_b)

        apply_tenant_scope(db, tenant_a.id)
        allowed = await AgentPermissionManager()._resolve_tools_from_skills(
            {skill_b.id}, db
        )

        assert "decision____b-gate-tool" not in allowed


class TestRuntimeExecutorDecisionDefinitions:
    async def test_load_tool_definitions_builds_decision_definition(self, db):
        """(v) _load_tool_definitions resolves decision____ names from the DB."""
        from app.db.tenant_scoping import apply_tenant_scope
        from app.services.agents.runtime_executor import AgentRuntimeExecutor

        tenant, _ = await create_two_tenants(db)
        tool = await _create_decision_tool(db, tenant.id, "exec-tool")

        apply_tenant_scope(db, tenant.id)
        executor = AgentRuntimeExecutor(data_client=None)
        defs, name_map = await executor._load_tool_definitions(
            {"decision____exec-tool"}, db, include_all_system_tools=False
        )

        matching = [d for d in defs if d.get("function", {}).get("name", "").startswith("decision")]
        assert len(matching) == 1
        assert "exec-tool" in matching[0]["function"]["name"]
        assert "Decide exec-tool" in matching[0]["function"]["description"]
        assert any(v == "decision____exec-tool" for v in name_map.values())

    async def test_load_tool_definitions_other_tenant_not_resolved(self, db):
        from app.db.tenant_scoping import apply_tenant_scope
        from app.services.agents.runtime_executor import AgentRuntimeExecutor

        tenant_a, tenant_b = await create_two_tenants(db)
        await _create_decision_tool(db, tenant_b.id, "b-exec-tool")

        apply_tenant_scope(db, tenant_a.id)
        executor = AgentRuntimeExecutor(data_client=None)
        defs, _name_map = await executor._load_tool_definitions(
            {"decision____b-exec-tool"}, db, include_all_system_tools=False
        )

        assert not [
            d
            for d in defs
            if d.get("function", {}).get("name", "").startswith("decision")
        ]
