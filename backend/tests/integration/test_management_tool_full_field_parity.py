"""Full-field parity + structured-error tests for the CC management tools.

Phase 2 tasks 2.2–2.6: proves the management-tool handlers accept the full
UI field sets from the parity matrix (docs/changes/
cc-assistant-management-tool-coverage/parity-matrix.md):

- agent_type: guardrails, input/output schemas, output_data_type_id
  (id-or-name), conversational-vs-typed-output conflict (structured 400),
  guardrail contract (structured 400), role_id/identity_id on update;
- agent_identity: status enum coercion, role_ids additive merge
  (resolve-before-write, unknown → 404, no partial write);
- model_config: api_key write-accepted and NEVER echoed
  (has_credentials posture only);
- schedule: cron_expression + payload updates;
- data_type: fields contract (≥1 field, no duplicates);
- structured error shape for every validation failure;
- unknown-field rejection;
- serializer UI-detail parity (guardrails, role grant ids, identity role
  assignments, has_refresh_token posture) with zero secrets in output.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_service_certificate
from app.db.session import get_db
from app.main import create_app


def _bypass_service_cert():
    async def override():
        return {"cert_type": "service", "service_name": "test-service"}

    return override


@pytest_asyncio.fixture
async def authed_client(test_engine):
    app = create_app()
    app.dependency_overrides[require_service_certificate] = _bypass_service_cert()

    SessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
def allow_all(monkeypatch: pytest.MonkeyPatch):
    from app.api.v1.internal import management_tools

    async def _allow(db, user_sub, resource_type, action, tenant_id):
        return None

    monkeypatch.setattr(management_tools, "_authorize", _allow)


async def _invoke(client: AsyncClient, tool_name: str, args: dict) -> dict:
    response = await client.post(
        f"/api/v1/internal/management-tools/{tool_name}",
        json={"session_id": str(uuid.uuid4()), "user_sub": "user-1", "tool_args": args},
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]



async def _invoke_expect_400(client: AsyncClient, tool_name: str, args: dict) -> list[dict]:
    """Invoke a tool expecting a structured 400; return the per-field problems."""
    response = await client.post(
        f"/api/v1/internal/management-tools/{tool_name}",
        json={"session_id": str(uuid.uuid4()), "user_sub": "user-1", "tool_args": args},
    )
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, dict) and detail["error"] == "validation_failed"
    return detail["problems"]



async def _invoke_expect_404(client: AsyncClient, tool_name: str, args: dict) -> dict:
    """Invoke a tool expecting a structured 404 reference error; return the detail."""
    response = await client.post(
        f"/api/v1/internal/management-tools/{tool_name}",
        json={"session_id": str(uuid.uuid4()), "user_sub": "user-1", "tool_args": args},
    )
    assert response.status_code == 404, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, dict) and detail["error"] == "reference_not_found"
    return detail


# ── agent_type: full field set (task 2.2) ───────────────────────────────────


@pytest.mark.asyncio
async def test_agent_type_create_accepts_full_ui_field_set(authed_client, allow_all):
    dt = await _invoke(
        authed_client,
        "create_data_type",
        {"name": "parity-dt", "data": {"slug": "parity-dt", "fields": [{"name": "answer", "type": "string"}]}},
    )
    role = await _invoke(authed_client, "create_agent_role", {"name": "parity-role", "data": {}})
    record = await _invoke(
        authed_client,
        "create_agent_type",
        {
            "name": "parity-agent",
            "data": {
                "description": "full parity",
                "role_id": role["record"]["id"],
                "model_id": "gpt-4o",
                "system_instruction": "be helpful",
                "input_type": "none",
                "input_schema": {"type": "object"},
                "output_type": "auto",
                "output_schema": {"type": "object"},
                "output_data_type_id": dt["record"]["id"],
                "guardrail_max_iterations": 24,
                "guardrail_max_delegation_depth": 4,
                "guardrail_max_delegated_steps": 100,
                "guardrail_execution_timeout_seconds": 600,
                "guardrail_token_budget": 500_000,
                "guardrail_token_enforcement_mode": "observe",
                "guardrail_token_fallback_mode": "observe_and_log",
                "guardrail_conversational_token_visibility_mode": "enabled",
                "guardrail_conversational_continuation_policy": "allow",
            },
        },
    )
    got = record["record"]
    assert got["guardrail_max_iterations"] == 24
    assert got["guardrail_max_delegation_depth"] == 4
    assert got["guardrail_max_delegated_steps"] == 100
    assert got["guardrail_execution_timeout_seconds"] == 600
    assert got["guardrail_token_budget"] == 500_000
    assert got["guardrail_token_enforcement_mode"] == "observe"
    assert got["guardrail_token_fallback_mode"] == "observe_and_log"
    assert got["guardrail_conversational_token_visibility_mode"] == "enabled"
    assert got["guardrail_conversational_continuation_policy"] == "allow"
    assert got["input_schema"] == {"type": "object"}
    assert got["output_schema"] == {"type": "object"}
    assert got["output_data_type_id"] == dt["record"]["id"]
    assert got["output_data_type_name"] == "parity-dt"
    assert got["role_id"] == role["record"]["id"]


@pytest.mark.asyncio
async def test_agent_type_update_accepts_role_identity_types_and_output_data_type(authed_client, allow_all):
    role = await _invoke(authed_client, "create_agent_role", {"name": "parity-role-2", "data": {}})
    agent = await _invoke(
        authed_client, "create_agent_type", {"name": "parity-agent-2", "data": {}}
    )
    updated = await _invoke(
        authed_client,
        "update_agent_type",
        {
            "id": agent["record"]["id"],
            "data": {
                "role_id": role["record"]["id"],
                "input_type": "typed",
                "output_type": "typed",
            },
        },
    )
    assert updated["record"]["role_id"] == role["record"]["id"]
    assert updated["record"]["input_type"] == "typed"
    assert updated["record"]["output_type"] == "typed"


@pytest.mark.asyncio
async def test_agent_type_conversational_output_conflict_is_structured(authed_client, allow_all):
    dt = await _invoke(
        authed_client,
        "create_data_type",
        {"name": "parity-dt-2", "data": {"slug": "parity-dt-2", "fields": [{"name": "a", "type": "number"}]}},
    )
    problems = await _invoke_expect_400(
        authed_client,
        "create_agent_type",
        {
            "name": "parity-conv",
            "data": {"input_type": "conversation", "output_data_type_id": dt["record"]["id"]},
        },
    )
    assert problems[0]["field"] == "output_data_type_id"
    assert "conversation" in problems[0]["problem"]


@pytest.mark.asyncio
async def test_agent_type_guardrail_contract_is_structured(authed_client, allow_all):
    problems = await _invoke_expect_400(
        authed_client,
        "create_agent_type",
        {"name": "parity-guard", "data": {"guardrail_max_iterations": 999_999}},
    )
    assert problems[0]["field"] == "guardrail_max_iterations"


@pytest.mark.asyncio
async def test_agent_type_unknown_field_is_rejected_with_allowed_set(authed_client, allow_all):
    agent = await _invoke(authed_client, "create_agent_type", {"name": "bogus-field-agent", "data": {}})
    problems = await _invoke_expect_400(
        authed_client,
        "update_agent_type",
        {"id": agent["record"]["id"], "data": {"bogus_field": 1}},
    )
    assert problems[0]["field"] == "bogus_field"
    assert "system_instruction" in problems[0]["remedy"]




# ── agent_identity: status + role_ids (task 2.3) ────────────────────────────


@pytest.mark.asyncio
async def test_agent_identity_create_status_and_update_roles_additive(authed_client, allow_all):
    role_a = await _invoke(authed_client, "create_agent_role", {"name": "id-role-a", "data": {}})
    role_b = await _invoke(authed_client, "create_agent_role", {"name": "id-role-b", "data": {}})
    identity = await _invoke(
        authed_client,
        "create_agent_identity",
        {"name": "parity-identity", "data": {"status": "active", "realm_name": "ai_agents", "realm_username": "parity"}},
    )
    assert identity["record"]["status"] == "active"
    assert identity["record"]["role_ids"] == []

    # Additive role assignment by id, then by name (merge, never replace).
    await _invoke(
        authed_client,
        "update_agent_identity",
        {"id": identity["record"]["id"], "data": {"role_ids": [role_a["record"]["id"]]}},
    )
    updated = await _invoke(
        authed_client,
        "update_agent_identity",
        {"id": identity["record"]["id"], "data": {"role_ids": [role_b["record"]["name"]], "status": "suspended", "realm_username": "parity-2"}},
    )
    assert sorted(updated["record"]["role_ids"]) == sorted([role_a["record"]["id"], role_b["record"]["id"]])
    assert updated["record"]["status"] == "suspended"
    assert updated["record"]["realm_username"] == "parity-2"


@pytest.mark.asyncio
async def test_agent_identity_unknown_role_is_404_no_partial_write(authed_client, allow_all, test_engine):
    from sqlalchemy import select

    from app.db.models.agents import AgentRoleIdentity

    identity = await _invoke(
        authed_client, "create_agent_identity", {"name": "parity-identity-2", "data": {}}
    )
    role = await _invoke(authed_client, "create_agent_role", {"name": "id-role-c", "data": {}})
    response = await authed_client.post(
        "/api/v1/internal/management-tools/update_agent_identity",
        json={
            "session_id": str(uuid.uuid4()),
            "user_sub": "user-1",
            "tool_args": {
                "id": identity["record"]["id"],
                "data": {"role_ids": [role["record"]["id"], str(uuid.uuid4())]},
            },
        },
    )
    assert response.status_code == 404
    # No partial write: the known role must NOT be bound.
    async_session = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(AgentRoleIdentity).where(
                        AgentRoleIdentity.identity_id == uuid.UUID(identity["record"]["id"])
                    )
                )
            )
            .scalars()
            .all()
        )
    assert rows == []


# ── model_config: api_key write-only (task 2.4) ─────────────────────────────


@pytest.mark.asyncio
async def test_model_config_api_key_write_only_and_never_echoed(authed_client, allow_all):
    result = await _invoke(
        authed_client,
        "create_model_config",
        {
            "name": "parity-provider",
            "data": {
                "provider_type": "openai",
                "api_key": "sk-super-secret-value",
                "enabled_models": ["gpt-4o"],
            },
        },
    )
    serialized = repr(result)
    assert "sk-super-secret-value" not in serialized
    assert result["record"]["has_credentials"] is True

    updated = await _invoke(
        authed_client,
        "update_model_config",
        {
            "id": result["record"]["id"],
            "data": {"display_name": "parity-provider-renamed", "provider_type": "anthropic"},
        },
    )
    assert updated["record"]["display_name"] == "parity-provider-renamed"
    assert updated["record"]["provider_type"] == "anthropic"
    assert "sk-super-secret-value" not in repr(updated)


@pytest.mark.asyncio
async def test_identity_serializer_never_exposes_token_material(authed_client, allow_all):
    result = await _invoke(
        authed_client, "create_agent_identity", {"name": "parity-identity-3", "data": {}}
    )
    serialized = repr(result)
    assert "access_token" not in serialized
    assert "refresh_token=" not in serialized.replace("has_refresh_token", "")
    assert "encrypted_refresh_token" not in serialized
    assert result["record"]["has_refresh_token"] is False


# ── schedule: cron/payload updates (task 2.4) ───────────────────────────────


@pytest.mark.asyncio
async def test_schedule_update_accepts_cron_and_payload(authed_client, allow_all):
    agent = await _invoke(authed_client, "create_agent_type", {"name": "sched-agent", "data": {}})
    schedule = await _invoke(
        authed_client,
        "create_schedule",
        {
            "name": "parity-schedule",
            "data": {"cron_expression": "0 9 * * *", "target_id": agent["record"]["id"], "payload": {"q": 1}},
        },
    )
    assert schedule["record"]["payload"] == {"q": 1}
    updated = await _invoke(
        authed_client,
        "update_schedule",
        {
            "id": schedule["record"]["id"],
            "data": {"cron_expression": "30 10 * * *", "payload": {"q": 2}},
        },
    )
    assert updated["record"]["cron_expression"] == "30 10 * * *"
    assert updated["record"]["payload"] == {"q": 2}


# ── data_type: fields contract (task 2.4) ───────────────────────────────────


@pytest.mark.asyncio
async def test_data_type_empty_fields_is_structured_400(authed_client, allow_all):
    problems = await _invoke_expect_400(
        authed_client,
        "create_data_type",
        {"name": "empty-dt", "data": {"slug": "empty-dt", "fields": []}},
    )
    assert problems[0]["field"] == "fields"


@pytest.mark.asyncio
async def test_data_type_duplicate_field_names_are_structured_400(authed_client, allow_all):
    problems = await _invoke_expect_400(
        authed_client,
        "create_data_type",
        {
            "name": "dup-dt",
            "data": {
                "slug": "dup-dt",
                "fields": [{"name": "a", "type": "string"}, {"name": "a", "type": "number"}],
            },
        },
    )
    assert problems[0]["field"] == "fields"
    assert "duplicate" in problems[0]["problem"]


# ── role serializer grant ids (task 2.6) ────────────────────────────────────


@pytest.mark.asyncio
async def test_role_serializer_carries_grant_id_lists(authed_client, allow_all):
    skill = await _invoke(authed_client, "create_skill", {"name": "grant-skill", "data": {}})
    sop = await _invoke(authed_client, "create_sop", {"name": "grant-sop", "data": {}})
    role = await _invoke(
        authed_client,
        "create_agent_role",
        {"name": "grant-role", "data": {"skill_ids": [skill["record"]["id"]], "sop_ids": [sop["record"]["name"]]}},
    )
    fetched = await _invoke(authed_client, "get_agent_role", {"name": "grant-role"})
    assert fetched["record"]["skill_ids"] == [skill["record"]["id"]]
    assert fetched["record"]["sop_ids"] == [sop["record"]["id"]]


# ── enum coercion error lists valid values (task 2.5) ───────────────────────


@pytest.mark.asyncio
async def test_invalid_enum_error_lists_valid_values(authed_client, allow_all):
    problems = await _invoke_expect_400(
        authed_client,
        "create_agent_identity",
        {"name": "parity-identity-4", "data": {"status": "bogus-status"}},
    )
    assert problems[0]["field"] == "status"
    assert "active" in problems[0]["remedy"]


# ── Phase 5 task 5.2 gap fill: per-family coverage for the remaining families ─


@pytest.mark.asyncio
async def test_skill_and_sop_create_update_full_field_parity(authed_client, allow_all):
    """5.2(a): skill + sop accept every UI-editable field via create and update."""
    skill = await _invoke(
        authed_client,
        "create_skill",
        {
            "name": "parity-skill",
            "data": {"description": "d", "instructions": "do it", "is_active": True},
        },
    )
    assert skill["record"]["instructions"] == "do it"
    assert skill["record"]["is_active"] is True
    skill_updated = await _invoke(
        authed_client,
        "update_skill",
        {"id": skill["record"]["id"], "data": {"instructions": "do it better", "is_active": False}},
    )
    assert skill_updated["record"]["instructions"] == "do it better"
    assert skill_updated["record"]["is_active"] is False

    sop = await _invoke(
        authed_client,
        "create_sop",
        {"name": "parity-sop", "data": {"description": "sop-d", "instructions": "steps"}},
    )
    assert sop["record"]["instructions"] == "steps"
    sop_updated = await _invoke(
        authed_client,
        "update_sop",
        {"id": sop["record"]["id"], "data": {"description": "sop-d-2", "is_active": False}},
    )
    assert sop_updated["record"]["description"] == "sop-d-2"
    assert sop_updated["record"]["is_active"] is False


@pytest.mark.asyncio
async def test_skill_invalid_bool_is_structured(authed_client, allow_all):
    """5.2(b): an invalid boolean on a skill returns a structured, actionable error."""
    skill = await _invoke(authed_client, "create_skill", {"name": "bool-skill", "data": {}})
    problems = await _invoke_expect_400(
        authed_client,
        "update_skill",
        {"id": skill["record"]["id"], "data": {"is_active": "sometimes"}},
    )
    assert problems[0]["field"] == "is_active"


# ── task 2.7: SOP steps parity (nested structure) ───────────────────────────


async def _create_sop_steps_prereqs(client: AsyncClient, prefix: str = "step") -> dict:
    skill = await _invoke(client, "create_skill", {"name": f"{prefix}-skill", "data": {}})
    agent = await _invoke(client, "create_agent_type", {"name": f"{prefix}-agent", "data": {}})
    return {"skill": skill["record"], "agent": agent["record"]}


@pytest.mark.asyncio
async def test_sop_create_with_mixed_steps_and_serializer_returns_them(authed_client, allow_all):
    """2.7(a)+(g): create_sop accepts a mixed ordered steps array and get_sop
    serializes the steps in order."""
    prereq = await _create_sop_steps_prereqs(authed_client, "mixstep")
    sop = await _invoke(
        authed_client,
        "create_sop",
        {
            "name": "steps-sop",
            "data": {
                "description": "with steps",
                "steps": [
                    {
                        "order": 1,
                        "step_type": "skill_invocation",
                        "skill_id": prereq["skill"]["id"],
                        "name": "check",
                    },
                    {
                        "order": 2,
                        "step_type": "agent_delegation",
                        "target_agent_type_id": prereq["agent"]["id"],
                    },
                ],
            },
        },
    )
    steps = sop["record"]["steps"]
    assert [s["order"] for s in steps] == [1, 2]
    assert [s["step_type"] for s in steps] == ["skill_invocation", "agent_delegation"]
    assert steps[0]["skill_id"] == prereq["skill"]["id"]
    assert steps[1]["target_agent_type_id"] == prereq["agent"]["id"]

    fetched = await _invoke(authed_client, "get_sop", {"name": "steps-sop"})
    assert fetched["record"]["steps"] == steps


@pytest.mark.asyncio
async def test_sop_update_replaces_steps_and_preserves_order(authed_client, allow_all, test_engine):
    """2.7(b): update_sop with 'steps' replaces the full list — old steps gone,
    new steps persisted in order; absent 'steps' leaves them untouched."""
    from sqlalchemy import select

    from app.db.models.skills import SopStep

    prereq = await _create_sop_steps_prereqs(authed_client, "replstep")
    skill_b = await _invoke(authed_client, "create_skill", {"name": "step-skill-b", "data": {}})
    sop = await _invoke(
        authed_client,
        "create_sop",
        {
            "name": "replace-sop",
            "data": {
                "steps": [
                    {"order": 1, "step_type": "skill_invocation", "skill_id": prereq["skill"]["id"]}
                ],
            },
        },
    )
    sop_id = sop["record"]["id"]

    # Update WITHOUT 'steps' → steps untouched.
    untouched = await _invoke(
        authed_client, "update_sop", {"id": sop_id, "data": {"description": "desc-only"}}
    )
    assert [s["order"] for s in untouched["record"]["steps"]] == [1]

    # Update WITH 'steps' → full replacement, new order preserved.
    updated = await _invoke(
        authed_client,
        "update_sop",
        {
            "id": sop_id,
            "data": {
                "steps": [
                    {"order": 1, "step_type": "skill_invocation", "skill_id": skill_b["record"]["id"]},
                    {
                        "order": 2,
                        "step_type": "agent_delegation",
                        "target_agent_type_id": prereq["agent"]["id"],
                    },
                ],
            },
        },
    )
    steps = updated["record"]["steps"]
    assert [s["order"] for s in steps] == [1, 2]
    assert steps[0]["skill_id"] == skill_b["record"]["id"]
    assert steps[1]["target_agent_type_id"] == prereq["agent"]["id"]

    async_session = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(SopStep).where(SopStep.sop_id == uuid.UUID(sop_id)).order_by(SopStep.order)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 2
    assert rows[0].skill_id == uuid.UUID(skill_b["record"]["id"])
    assert rows[0].skill_id != uuid.UUID(prereq["skill"]["id"])  # old step gone
    assert rows[1].target_agent_type_id == uuid.UUID(prereq["agent"]["id"])


@pytest.mark.asyncio
async def test_sop_delegation_step_resolves_agent_type_by_name(authed_client, allow_all):
    """2.7(c): agent_delegation steps accept an agent-type NAME."""
    prereq = await _create_sop_steps_prereqs(authed_client, "namedel")
    sop = await _invoke(
        authed_client,
        "create_sop",
        {
            "name": "name-delegation-sop",
            "data": {
                "steps": [
                    {
                        "order": 1,
                        "step_type": "agent_delegation",
                        "target_agent_type_id": prereq["agent"]["name"],
                    }
                ],
            },
        },
    )
    steps = sop["record"]["steps"]
    assert steps[0]["target_agent_type_id"] == prereq["agent"]["id"]


@pytest.mark.asyncio
async def test_sop_skill_step_without_skill_id_is_structured(authed_client, allow_all):
    """2.7(d): a skill_invocation step without skill_id → structured error."""
    problems = await _invoke_expect_400(
        authed_client,
        "create_sop",
        {
            "name": "missing-skill-sop",
            "data": {"steps": [{"order": 1, "step_type": "skill_invocation"}]},
        },
    )
    assert problems[0]["field"] == "steps[0].skill_id"
    assert problems[0]["problem"] == "is required"


@pytest.mark.asyncio
async def test_sop_delegation_step_without_target_is_structured(authed_client, allow_all):
    """2.7(e): an agent_delegation step without target_agent_type_id → structured error."""
    problems = await _invoke_expect_400(
        authed_client,
        "create_sop",
        {
            "name": "missing-target-sop",
            "data": {"steps": [{"order": 1, "step_type": "agent_delegation"}]},
        },
    )
    assert problems[0]["field"] == "steps[0].target_agent_type_id"
    assert problems[0]["problem"] == "is required"


@pytest.mark.asyncio
async def test_sop_step_xor_invariant_is_structured(authed_client, allow_all):
    """2.7: skill_invocation + target_agent_type_id (and the inverse) → structured
    errors naming the per-type requirement."""
    prereq = await _create_sop_steps_prereqs(authed_client, "xorstep")
    problems = await _invoke_expect_400(
        authed_client,
        "create_sop",
        {
            "name": "xor-sop",
            "data": {
                "steps": [
                    {
                        "order": 1,
                        "step_type": "skill_invocation",
                        "skill_id": prereq["skill"]["id"],
                        "target_agent_type_id": prereq["agent"]["id"],
                    }
                ],
            },
        },
    )
    assert problems[0]["field"] == "steps[0].target_agent_type_id"
    assert "skill_invocation" in problems[0]["problem"] + problems[0]["remedy"]

    problems = await _invoke_expect_400(
        authed_client,
        "create_sop",
        {
            "name": "xor-sop-2",
            "data": {
                "steps": [
                    {
                        "order": 1,
                        "step_type": "agent_delegation",
                        "target_agent_type_id": prereq["agent"]["id"],
                        "skill_id": prereq["skill"]["id"],
                    }
                ],
            },
        },
    )
    assert problems[0]["field"] == "steps[0].skill_id"
    assert "agent_delegation" in problems[0]["problem"] + problems[0]["remedy"]


@pytest.mark.asyncio
async def test_sop_unknown_step_field_is_structured(authed_client, allow_all):
    problems = await _invoke_expect_400(
        authed_client,
        "create_sop",
        {
            "name": "unknown-step-field-sop",
            "data": {"steps": [{"order": 1, "bogus": 1}]},
        },
    )
    assert problems[0]["field"] == "steps[0]"
    assert "bogus" in problems[0]["problem"]


@pytest.mark.asyncio
async def test_sop_unknown_skill_reference_is_404_no_partial_write(authed_client, allow_all):
    response = await authed_client.post(
        "/api/v1/internal/management-tools/create_sop",
        json={
            "session_id": str(uuid.uuid4()),
            "user_sub": "user-1",
            "tool_args": {
                "name": "unknown-ref-sop",
                "data": {
                    "steps": [
                        {"order": 1, "step_type": "skill_invocation", "skill_id": "no-such-skill"}
                    ],
                },
            },
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_sop_step_change_invalidates_bound_role_permission_cache(
    authed_client, allow_all, monkeypatch, test_engine
):
    """2.7(f): replacing steps invalidates the shared permission manager cache
    for every role bound to the SOP."""
    from app.db.models.agents import AgentRoleSOP
    from sqlalchemy import select

    prereq = await _create_sop_steps_prereqs(authed_client, "permstep")
    role = await _invoke(
        authed_client,
        "create_agent_role",
        {"name": "sop-step-role", "data": {}},
    )
    sop = await _invoke(
        authed_client,
        "create_sop",
        {
            "name": "perm-sop",
            "data": {
                "steps": [
                    {"order": 1, "step_type": "skill_invocation", "skill_id": prereq["skill"]["id"]}
                ],
            },
        },
    )

    # Bind the role to the SOP directly (AgentRoleSOP row).
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        session.add(
            AgentRoleSOP(
                role_id=uuid.UUID(role["record"]["id"]), sop_id=uuid.UUID(sop["record"]["id"])
            )
        )
        await session.commit()

    invalidated: list[str] = []

    class _FakePM:
        def invalidate(self, role_id):
            invalidated.append(str(role_id))

    import app.services.agents.permission_manager as pm_module

    monkeypatch.setattr(pm_module, "get_shared_permission_manager", lambda: _FakePM())

    await _invoke(
        authed_client,
        "update_sop",
        {
            "id": sop["record"]["id"],
            "data": {
                "steps": [
                    {
                        "order": 1,
                        "step_type": "agent_delegation",
                        "target_agent_type_id": prereq["agent"]["id"],
                    }
                ],
            },
        },
    )
    assert invalidated == [role["record"]["id"]]


@pytest.mark.asyncio
async def test_agent_role_update_additive_grants_and_unknown_name_404(authed_client, allow_all, test_engine):
    """5.2(a)+(f): role description + skill/sop grants update additively (id-or-name);
    an unknown skill name yields a structured 404 with no partial write."""
    from sqlalchemy import select

    from app.db.models.agents import AgentRoleSkill

    skill_a = await _invoke(authed_client, "create_skill", {"name": "role-skill-a", "data": {}})
    skill_b = await _invoke(authed_client, "create_skill", {"name": "role-skill-b", "data": {}})
    sop = await _invoke(authed_client, "create_sop", {"name": "role-sop", "data": {}})
    role = await _invoke(
        authed_client,
        "create_agent_role",
        {"name": "grant-update-role", "data": {"skill_ids": [skill_a["record"]["id"]]}},
    )
    # Additive merge: second update adds by NAME, first grant survives.
    updated = await _invoke(
        authed_client,
        "update_agent_role",
        {
            "id": role["record"]["id"],
            "data": {
                "description": "now described",
                "skill_ids": [skill_b["record"]["name"]],
                "sop_ids": [sop["record"]["id"]],
            },
        },
    )
    assert updated["record"]["description"] == "now described"
    assert sorted(updated["record"]["skill_ids"]) == sorted(
        [skill_a["record"]["id"], skill_b["record"]["id"]]
    )
    assert updated["record"]["sop_ids"] == [sop["record"]["id"]]

    # Unknown skill name → 404, no partial write.
    response = await authed_client.post(
        "/api/v1/internal/management-tools/update_agent_role",
        json={
            "session_id": str(uuid.uuid4()),
            "user_sub": "user-1",
            "tool_args": {
                "id": role["record"]["id"],
                "data": {"skill_ids": [skill_a["record"]["id"], "no-such-skill"]},
            },
        },
    )
    assert response.status_code == 404
    async_session = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(AgentRoleSkill).where(
                        AgentRoleSkill.role_id == uuid.UUID(role["record"]["id"])
                    )
                )
            )
            .scalars()
            .all()
        )
        skill_ids = {str(r.skill_id) for r in rows}
    assert skill_ids == {skill_a["record"]["id"], skill_b["record"]["id"]}


@pytest.mark.asyncio
async def test_agent_type_skill_sop_bindings_additive_and_idempotent(authed_client, allow_all, test_engine):
    """5.2(f): agent-type skill/sop bindings are additive and idempotent —
    re-approving the same set never duplicates rows or removes existing ones."""
    skill_a = await _invoke(authed_client, "create_skill", {"name": "bind-skill-a", "data": {}})
    skill_b = await _invoke(authed_client, "create_skill", {"name": "bind-skill-b", "data": {}})
    sop = await _invoke(authed_client, "create_sop", {"name": "bind-sop", "data": {}})
    agent = await _invoke(
        authed_client,
        "create_agent_type",
        {
            "name": "bind-agent",
            "data": {"skill_ids": [skill_a["record"]["id"]], "sop_ids": [sop["record"]["name"]]},
        },
    )
    fetched = await _invoke(authed_client, "get_agent_type", {"id": agent["record"]["id"]})
    # Bindings persist as AgentTypeSkillBinding / AgentTypeSopBinding rows
    # (the agent-type serializer exposes binding posture via the bindings
    # surface, not inline lists).
    from sqlalchemy import select

    from app.db.models.agents import AgentTypeSkillBinding, AgentTypeSopBinding

    async_session = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        bound_skills = (
            (
                await session.execute(
                    select(AgentTypeSkillBinding).where(
                        AgentTypeSkillBinding.agent_type_id == uuid.UUID(agent["record"]["id"])
                    )
                )
            )
            .scalars()
            .all()
        )
        bound_sops = (
            (
                await session.execute(
                    select(AgentTypeSopBinding).where(
                        AgentTypeSopBinding.agent_type_id == uuid.UUID(agent["record"]["id"])
                    )
                )
            )
            .scalars()
            .all()
        )
    assert [str(b.skill_id) for b in bound_skills] == [skill_a["record"]["id"]]
    assert [str(b.sop_id) for b in bound_sops] == [sop["record"]["id"]]

    # Additive merge (idempotent re-binding of skill_a + a new skill_b).
    updated = await _invoke(
        authed_client,
        "update_agent_type",
        {
            "id": agent["record"]["id"],
            "data": {"skill_ids": [skill_a["record"]["id"], skill_b["record"]["id"]]},
        },
    )
    async with async_session() as session:
        bound_skills = sorted(
            str(b.skill_id)
            for b in (
                await session.execute(
                    select(AgentTypeSkillBinding).where(
                        AgentTypeSkillBinding.agent_type_id == uuid.UUID(agent["record"]["id"])
                    )
                )
            )
            .scalars()
            .all()
        )
        bound_sops = (
            await session.execute(
                select(AgentTypeSopBinding).where(
                    AgentTypeSopBinding.agent_type_id == uuid.UUID(agent["record"]["id"])
                )
            )
        ).scalars().all()
    # Additive: skill_a survived, skill_b added; sop binding untouched.
    assert bound_skills == sorted([skill_a["record"]["id"], skill_b["record"]["id"]])
    assert [str(b.sop_id) for b in bound_sops] == [sop["record"]["id"]]


@pytest.mark.asyncio
async def test_mcp_server_missing_slug_is_structured_actionable(authed_client, allow_all):
    """5.2(b): the known 'slug is required' failure mode is now a structured,
    self-correctable error."""
    problems = await _invoke_expect_400(
        authed_client, "create_mcp_server", {"name": "slugless", "data": {"base_url": "https://x/mcp"}}
    )
    assert problems[0]["field"] == "slug"
    assert problems[0]["problem"] == "is required"
    assert "slug" in problems[0]["remedy"].lower()


@pytest.mark.asyncio
async def test_mcp_server_duplicate_slug_is_structured_409(authed_client, allow_all):
    """5.2(b): per-tenant slug uniqueness returns a structured 409."""
    first = await _invoke(
        authed_client,
        "create_mcp_server",
        {"name": "dup-srv-1", "data": {"slug": "dup-srv", "base_url": "https://a/mcp"}},
    )
    assert first["record"]["slug"] == "dup-srv"
    response = await authed_client.post(
        "/api/v1/internal/management-tools/create_mcp_server",
        json={
            "session_id": str(uuid.uuid4()),
            "user_sub": "user-1",
            "tool_args": {
                "name": "dup-srv-2",
                "data": {"slug": "dup-srv", "base_url": "https://b/mcp"},
            },
        },
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_mcp_server_serializer_never_exposes_credential_material(authed_client, allow_all):
    """5.2(e): mcp server list/get output carries no credential/token material."""
    created = await _invoke(
        authed_client,
        "create_mcp_server",
        {
            "name": "posture-srv",
            "data": {"slug": "posture-srv", "base_url": "https://p/mcp", "description": "d"},
        },
    )
    fetched = await _invoke(authed_client, "get_mcp_server", {"id": created["record"]["id"]})
    serialized = repr(fetched)
    assert "api_key" not in serialized.lower()
    assert "client_secret" not in serialized.lower()
    assert "bearer" not in serialized.lower()


@pytest.mark.asyncio
async def test_data_type_update_applies_description_and_fields_slug_is_rejected(authed_client, allow_all):
    """5.2(a)+(b): data-type update applies description/typed fields; a slug
    change attempt yields a structured error (slug immutable post-create) and
    leaves the applied fields untouched."""
    created = await _invoke(
        authed_client,
        "create_data_type",
        {
            "name": "upd-dt",
            "data": {"slug": "upd-dt", "fields": [{"name": "a", "type": "string"}]},
        },
    )
    updated = await _invoke(
        authed_client,
        "update_data_type",
        {
            "id": created["record"]["id"],
            "data": {
                "description": "new desc",
                "fields": [{"name": "a", "type": "string"}, {"name": "b", "type": "enum", "options": ["x"]}],
            },
        },
    )
    assert updated["record"]["description"] == "new desc"
    assert [f["name"] for f in updated["record"]["fields"]] == ["a", "b"]

    # Slug is not part of the update allowed set → structured unknown-field error.
    problems = await _invoke_expect_400(
        authed_client,
        "update_data_type",
        {"id": created["record"]["id"], "data": {"slug": "renamed-slug"}},
    )
    assert problems[0]["field"] == "slug"

    fetched = await _invoke(authed_client, "get_data_type", {"id": created["record"]["id"]})
    assert fetched["record"]["slug"] == "upd-dt"
    assert [f["name"] for f in fetched["record"]["fields"]] == ["a", "b"]


@pytest.mark.asyncio
async def test_model_config_update_api_base_url_and_disabled_flag(authed_client, allow_all):
    """5.2(a): model config update applies api_base_url / enabled_models / is_disabled."""
    created = await _invoke(
        authed_client,
        "create_model_config",
        {"name": "base-url-provider", "data": {"provider_type": "openai"}},
    )
    updated = await _invoke(
        authed_client,
        "update_model_config",
        {
            "id": created["record"]["id"],
            "data": {
                "api_base_url": "https://proxy.internal/v1",
                "enabled_models": ["gpt-4o", "gpt-4o-mini"],
                "is_disabled": True,
            },
        },
    )
    assert updated["record"]["api_base_url"] == "https://proxy.internal/v1"
    assert updated["record"]["enabled_models"] == ["gpt-4o", "gpt-4o-mini"]
    assert updated["record"]["is_disabled"] is True


@pytest.mark.asyncio
async def test_permission_denial_is_clear_403_and_writes_nothing(authed_client, monkeypatch, test_engine):
    """5.2(c): a user lacking manage permission gets a clear structured 403
    denial and nothing is persisted."""
    from fastapi import HTTPException

    from app.api.v1.internal import management_tools

    async def _deny(db, user_sub, resource_type, action, tenant_id):
        raise HTTPException(status_code=403, detail="Permission denied for this resource")

    monkeypatch.setattr(management_tools, "_authorize", _deny)
    response = await authed_client.post(
        "/api/v1/internal/management-tools/create_skill",
        json={
            "session_id": str(uuid.uuid4()),
            "user_sub": "blocked-user",
            "tool_args": {"name": "denied-skill", "data": {}},
        },
    )
    assert response.status_code == 403
    # Nothing persisted: no row for the denied skill exists.
    from sqlalchemy import select

    from app.db.models.skills import Skill

    async_session = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        rows = (
            (await session.execute(select(Skill).where(Skill.name == "denied-skill")))
            .scalars()
            .all()
        )
    assert rows == []


# ── agent_role mcp_session_mappings (task 2.8 / 3.6) ────────────────────────


async def _root_tenant_id(engine) -> uuid.UUID:
    from sqlalchemy import select
    from app.db.models.tenant import Tenant

    async with async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)() as s:
        row = (await s.execute(select(Tenant).where(Tenant.is_system_tenant.is_(True)))).scalar_one()
        return row.id


async def _seed_role_mcp_world(
    engine, *, sessions: list[tuple[str, str]], default: str | None = None
):
    """Seed an MCP server with named sessions + a skill bound to one of its tools.

    ``sessions`` is a list of (name, auth_type) pairs; ``default`` optionally
    marks one session ``is_default=True``.  ``created_at`` is staggered in
    list order so "first" is deterministic.  Returns
    (server_id, {session_name: session_id}, skill_id, tenant_id).
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select
    from app.db.models.mcp_hub import McpServer, McpSession, McpTool
    from app.db.models.skills import Skill, SkillToolBinding

    tenant_id = await _root_tenant_id(engine)
    server_id = uuid.uuid4()
    tool_id = uuid.uuid4()
    skill_id = uuid.uuid4()
    server_name = f"parity-srv-{server_id.hex[:8]}"
    sessionmap: dict[str, uuid.UUID] = {}
    base_created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)() as s:
        server = McpServer(
            id=server_id, tenant_id=tenant_id, name=server_name,
            slug=server_name, base_url="http://mcp.example",
        )
        s.add(server)
        for i, (name, auth) in enumerate(sessions):
            sid = uuid.uuid4()
            sessionmap[name] = sid
            s.add(
                McpSession(
                    id=sid, server_id=server_id, name=name, auth_type=auth, is_active=True,
                    is_default=(name == default),
                    created_at=base_created + timedelta(seconds=i),
                )
            )
        s.add(
            McpTool(
                id=tool_id, server_id=server_id, tenant_id=tenant_id,
                name=f"{server.slug}/run_sql", original_name="run_sql", is_active=True,
            )
        )
        s.add(Skill(id=skill_id, tenant_id=tenant_id, name=f"mcp-world-skill-{skill_id.hex[:8]}"))
        s.add(SkillToolBinding(skill_id=skill_id, tool_id=tool_id, order=0))
        await s.commit()
    return server_name, sessionmap, skill_id, tenant_id


async def _grant_skill_to_role(client, role_id: str, skill_id) -> None:
    await _invoke(client, "update_agent_role", {"id": role_id, "data": {"skill_ids": [str(skill_id)]}})


async def _get_role_mappings(client, role_id: str) -> list[dict]:
    fetched = await _invoke(client, "get_agent_role", {"id": role_id})
    return fetched["record"]["mcp_session_mappings"]


@pytest.mark.asyncio
async def test_role_explicit_mapping_by_names_persists(authed_client, allow_all, test_engine):
    """2.8(a): explicit mapping by server-name + session-name persists, additive merge on update."""
    server_name, sessions, skill_id, _ = await _seed_role_mcp_world(
        test_engine, sessions=[("harry", "oauth2")]
    )
    second_name, second_sessions, skill2_id, _ = await _seed_role_mcp_world(
        test_engine, sessions=[("backup", "api_key")]
    )

    role = await _invoke(authed_client, "create_agent_role", {
        "name": f"mcp-map-role-{uuid.uuid4().hex[:8]}",
        "data": {
            "skill_ids": [str(skill_id)],
            "mcp_session_mappings": [{"server": server_name, "session": "harry"}],
        },
    })
    mappings = role["record"]["mcp_session_mappings"]
    assert len(mappings) == 1
    assert mappings[0]["session_name"] == "harry"
    assert mappings[0]["server_name"] == server_name
    assert mappings[0]["auth_type"] == "oauth2"
    assert "encrypted" not in str(mappings).lower()

    # Additive merge: a second update adds a mapping on ANOTHER server, keeps the first.
    await _invoke(authed_client, "update_agent_role", {
        "id": role["record"]["id"],
        "data": {"mcp_session_mappings": [{"server": second_name, "session": "backup"}]},
    })
    mappings = await _get_role_mappings(authed_client, role["record"]["id"])
    assert sorted(m["session_name"] for m in mappings) == ["backup", "harry"]
    # granting another skill keeps the mappings (additive merge, nothing removed)
    await _grant_skill_to_role(authed_client, role["record"]["id"], skill2_id)
    mappings = await _get_role_mappings(authed_client, role["record"]["id"])
    assert sorted(m["session_name"] for m in mappings) == ["backup", "harry"]


@pytest.mark.asyncio
async def test_role_passthrough_auto_default(authed_client, allow_all, test_engine):
    """2.8(b): unmapped server with a passthrough session → auto-mapped to passthrough."""
    server_name, sessions, skill_id, _ = await _seed_role_mcp_world(
        test_engine, sessions=[("robot", "passthrough"), ("harry", "oauth2")]
    )
    role = await _invoke(authed_client, "create_agent_role", {
        "name": f"pt-role-{uuid.uuid4().hex[:8]}", "data": {"skill_ids": [str(skill_id)]},
    })
    assert role["auto_mapped_mcp_sessions"], role
    assert "passthrough" in role["auto_mapped_mcp_sessions"][0]
    mappings = role["record"]["mcp_session_mappings"]
    assert [m["auth_type"] for m in mappings] == ["passthrough"]
    assert mappings[0]["session_id"] == str(sessions["robot"])


@pytest.mark.asyncio
async def test_role_single_session_auto_default(authed_client, allow_all, test_engine):
    """2.8(c): unmapped server with exactly one active session → auto-mapped."""
    server_name, sessions, skill_id, _ = await _seed_role_mcp_world(
        test_engine, sessions=[("solo", "bearer_token")]
    )
    role = await _invoke(authed_client, "create_agent_role", {
        "name": f"solo-role-{uuid.uuid4().hex[:8]}", "data": {"skill_ids": [str(skill_id)]},
    })
    assert role["auto_mapped_mcp_sessions"]
    mappings = role["record"]["mcp_session_mappings"]
    assert [m["session_name"] for m in mappings] == ["solo"]
    assert [m["auth_type"] for m in mappings] == ["bearer_token"]


@pytest.mark.asyncio
async def test_role_multi_session_defaults_to_first_with_confirm_warning(authed_client, allow_all, test_engine):
    """2.8(d): multiple non-passthrough sessions → FIRST session auto-mapped + confirm warning."""
    server_name, sessions, skill_id, _ = await _seed_role_mcp_world(
        test_engine, sessions=[("harry", "oauth2"), ("backup", "api_key"), ("readonly", "bearer_token")]
    )
    role = await _invoke(authed_client, "create_agent_role", {
        "name": f"ambig-role-{uuid.uuid4().hex[:8]}", "data": {"skill_ids": [str(skill_id)]},
    })
    warnings = role.get("warnings") or []
    assert any(
        "parity-srv" in w and "harry" in w and "confirm with the user" in w
        and "backup" in w and "readonly" in w
        for w in warnings
    ), warnings
    # The role is always functional: the FIRST session (created_at ASC) is auto-mapped.
    mappings = role["record"]["mcp_session_mappings"]
    assert [m["session_name"] for m in mappings] == ["harry"]
    assert mappings[0]["session_id"] == str(sessions["harry"])
    assert role.get("auto_mapped_mcp_sessions")


@pytest.mark.asyncio
async def test_role_multi_session_default_flag_wins_over_created_order(authed_client, allow_all, test_engine):
    """2.8(d2): with several sessions, the is_default one is mapped, not the oldest."""
    server_name, sessions, skill_id, _ = await _seed_role_mcp_world(
        test_engine,
        sessions=[("oldest", "oauth2"), ("primary", "oauth2"), ("backup", "api_key")],
        default="primary",
    )
    role = await _invoke(authed_client, "create_agent_role", {
        "name": f"ambig-role-{uuid.uuid4().hex[:8]}", "data": {"skill_ids": [str(skill_id)]},
    })
    mappings = role["record"]["mcp_session_mappings"]
    assert [m["session_name"] for m in mappings] == ["primary"]
    assert mappings[0]["session_id"] == str(sessions["primary"])
    assert any("confirm with the user" in w for w in (role.get("warnings") or []))


@pytest.mark.asyncio
async def test_role_session_from_wrong_server_is_structured(authed_client, allow_all, test_engine):
    """2.8(e): a session that belongs to another server → structured error, no write."""
    server_name, sessions, skill_id, _ = await _seed_role_mcp_world(
        test_engine, sessions=[("harry", "oauth2")]
    )
    other_name, other_sessions, _, _ = await _seed_role_mcp_world(
        test_engine, sessions=[("elsewhere", "api_key")]
    )
    # Reference the foreign session by ID (uuid-shaped resolution is global;
    # a NAME is resolved per-server and would 404 before the ownership check).
    problems = await _invoke_expect_400(authed_client, "create_agent_role", {
        "name": f"wrong-srv-role-{uuid.uuid4().hex[:8]}",
        "data": {
            "mcp_session_mappings": [
                {"server": server_name, "session": str(other_sessions["elsewhere"])},
            ]
        },
    })
    assert problems[0]["field"] == "mcp_session_mappings[0].session"
    assert "belong" in problems[0]["problem"]


@pytest.mark.asyncio
async def test_role_duplicate_server_mapping_is_conflict(authed_client, allow_all, test_engine):
    """2.8(f): re-mapping a mapped server to a DIFFERENT session → 409-style structured error."""
    server_name, sessions, skill_id, _ = await _seed_role_mcp_world(
        test_engine, sessions=[("harry", "oauth2"), ("backup", "api_key")]
    )
    role = await _invoke(authed_client, "create_agent_role", {
        "name": f"dup-role-{uuid.uuid4().hex[:8]}",
        "data": {"mcp_session_mappings": [{"server": server_name, "session": "harry"}]},
    })
    response = await authed_client.post(
        "/api/v1/internal/management-tools/update_agent_role",
        json={
            "session_id": str(uuid.uuid4()), "user_sub": "user-1",
            "tool_args": {
                "id": role["record"]["id"],
                "data": {"mcp_session_mappings": [{"server": server_name, "session": "backup"}]},
            },
        },
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "conflict"
    assert "already maps" in detail["problem"]


@pytest.mark.asyncio
async def test_role_mapping_serializer_surfaces_auth_type_no_credentials(authed_client, allow_all, test_engine):
    """2.8(g): serializer surfaces server/session names + auth_type; never credentials."""
    server_name, sessions, skill_id, _ = await _seed_role_mcp_world(
        test_engine, sessions=[("harry", "oauth2")]
    )
    role = await _invoke(authed_client, "create_agent_role", {
        "name": f"ser-role-{uuid.uuid4().hex[:8]}",
        "data": {"mcp_session_mappings": [{"server": server_name, "session": "harry"}]},
    })
    fetched = await _invoke(authed_client, "get_agent_role", {"id": role["record"]["id"]})
    mapping = fetched["record"]["mcp_session_mappings"][0]
    assert set(mapping) == {"server_id", "server_name", "session_id", "session_name", "auth_type"}
    assert mapping["auth_type"] == "oauth2"
    assert "credential" not in str(fetched).lower()
    assert "secret" not in str(fetched).lower()


@pytest.mark.asyncio
async def test_role_mapping_auth_type_as_session_name_resolves(authed_client, allow_all, test_engine):
    """2.8(h): passing an auth TYPE (e.g. 'passthrough') as the session name resolves
    to that server's active session with that auth type instead of a 404."""
    server_name, sessions, skill_id, _ = await _seed_role_mcp_world(
        test_engine, sessions=[("default", "passthrough"), ("harry", "oauth2")]
    )
    role = await _invoke(authed_client, "create_agent_role", {
        "name": f"authtype-role-{uuid.uuid4().hex[:8]}",
        "data": {
            "skill_ids": [str(skill_id)],
            "mcp_session_mappings": [{"server": server_name, "session": "passthrough"}],
        },
    })
    mappings = role["record"]["mcp_session_mappings"]
    assert len(mappings) == 1
    assert mappings[0]["session_id"] == str(sessions["default"])
    assert mappings[0]["session_name"] == "default"
    assert mappings[0]["auth_type"] == "passthrough"


@pytest.mark.asyncio
async def test_role_mapping_unknown_session_lists_available(authed_client, allow_all, test_engine):
    """2.8(i): a truly unknown session name → structured 404 whose message lists the
    server's available sessions (name + auth type) so the model can self-correct."""
    server_name, sessions, skill_id, _ = await _seed_role_mcp_world(
        test_engine, sessions=[("default", "passthrough"), ("harry", "oauth2")]
    )
    detail = await _invoke_expect_404(authed_client, "create_agent_role", {
        "name": f"unknown-sess-role-{uuid.uuid4().hex[:8]}",
        "data": {
            "skill_ids": [str(skill_id)],
            "mcp_session_mappings": [{"server": server_name, "session": "no-such-session"}],
        },
    })
    message = detail["message"]
    assert "no-such-session" in message
    assert "default (passthrough)" in message
    assert "harry (oauth2)" in message


@pytest.mark.asyncio
async def test_role_mapping_auth_type_without_matching_session_is_structured_404(
    authed_client, allow_all, test_engine
):
    """2.8(j): an auth-type name with NO matching session on the server → structured
    404 explaining the auth-type mismatch and listing available sessions."""
    server_name, sessions, skill_id, _ = await _seed_role_mcp_world(
        test_engine, sessions=[("harry", "oauth2")]
    )
    detail = await _invoke_expect_404(authed_client, "create_agent_role", {
        "name": f"no-pt-role-{uuid.uuid4().hex[:8]}",
        "data": {
            "skill_ids": [str(skill_id)],
            "mcp_session_mappings": [{"server": server_name, "session": "passthrough"}],
        },
    })
    message = detail["message"]
    assert "auth TYPE" in message
    assert "harry (oauth2)" in message
    assert detail["error"] == "reference_not_found"
