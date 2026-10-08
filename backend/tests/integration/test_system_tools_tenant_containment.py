"""Scenario 4 (+ decision tools) — system tool cross-tenant containment.

``query_result`` / ``save_data`` / ``get_data`` / ``get_output`` and the
outputs listing must resolve and filter strictly within the signed
tenant, even when identical data type names / record filters exist in
another tenant.  Tenant stamping is verified at the DB level.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.api.v1.internal.system_tools import (
    SystemToolRequest,
    get_data_tool,
    get_output_tool,
    query_result_tool,
    save_data_tool,
)
from app.core.tenant_context import TenantContext

from tests.integration._strict_tenant_utils import (  # noqa: F401
    create_agent_job,
    create_agent_type,
    create_two_tenants,
    db,
    make_module_schema_fixture,
)

_schema = make_module_schema_fixture()

DATA_TYPE_NAME = "customer_summary"  # identical in BOTH tenants


async def _seed_data_type(db, tenant_id):
    from app.db.models.agent_data_type import AgentDataType

    data_type = AgentDataType(
        tenant_id=tenant_id,
        name=DATA_TYPE_NAME,
        slug=DATA_TYPE_NAME,
        fields=[{"name": "total", "type": "number"}],
    )
    db.add(data_type)
    await db.commit()
    await db.refresh(data_type)
    return data_type


async def _seed_output(db, tenant_id, data_type_id, agent_type_id, session_id, total):
    from app.db.models.agent_output import AgentOutput, AgentOutputValidationStatus

    output = AgentOutput(
        tenant_id=tenant_id,
        data_type_id=data_type_id,
        agent_type_id=agent_type_id,
        execution_session_id=session_id,
        field_values={"total": total},
        validation_status=AgentOutputValidationStatus.valid,
    )
    db.add(output)
    await db.commit()
    await db.refresh(output)
    return output


def _ctx(tenant) -> TenantContext:
    return TenantContext(tenant_id=tenant.id, slug=tenant.slug, name=tenant.name)


def _request(session_id: str, tool_args: dict, agent_type_id: str | None = None):
    return SystemToolRequest(
        session_id=session_id, agent_type_id=agent_type_id, tool_args=tool_args
    )


class TestQueryResultContainment:
    async def test_query_result_resolves_own_tenant_data_type_and_rows(self, db):
        tenant_a, tenant_b = await create_two_tenants(db)
        at_a = await create_agent_type(db, tenant_a.id, "at-a")
        at_b = await create_agent_type(db, tenant_b.id, "at-b")
        job_a = await create_agent_job(db, tenant_a.id, at_a.id)
        job_b = await create_agent_job(db, tenant_b.id, at_b.id)
        dt_a = await _seed_data_type(db, tenant_a.id)
        dt_b = await _seed_data_type(db, tenant_b.id)
        await _seed_output(db, tenant_a.id, dt_a.id, at_a.id, job_a.id, 100)
        await _seed_output(db, tenant_b.id, dt_b.id, at_b.id, job_b.id, 999)

        response = await query_result_tool(
            _request(str(job_a.id), {"data_type_name": DATA_TYPE_NAME}),
            _ctx(tenant_a),
            db,
        )
        results = response.result["results"]
        assert len(results) == 1
        assert results[0]["field_values"]["total"] == 100
        assert results[0]["agent_type_id"] == str(at_a.id)

    async def test_query_result_tenant_b_gets_only_tenant_b_rows(self, db):
        tenant_a, tenant_b = await create_two_tenants(db)
        at_a = await create_agent_type(db, tenant_a.id, "at-a2")
        at_b = await create_agent_type(db, tenant_b.id, "at-b2")
        job_a = await create_agent_job(db, tenant_a.id, at_a.id)
        job_b = await create_agent_job(db, tenant_b.id, at_b.id)
        dt_a = await _seed_data_type(db, tenant_a.id)
        dt_b = await _seed_data_type(db, tenant_b.id)
        await _seed_output(db, tenant_a.id, dt_a.id, at_a.id, job_a.id, 100)
        await _seed_output(db, tenant_b.id, dt_b.id, at_b.id, job_b.id, 999)

        response = await query_result_tool(
            _request(str(job_b.id), {"data_type_name": DATA_TYPE_NAME}),
            _ctx(tenant_b),
            db,
        )
        totals = [r["field_values"]["total"] for r in response.result["results"]]
        assert totals == [999]

    async def test_query_result_miss_when_data_type_only_in_other_tenant(self, db):
        from fastapi import HTTPException

        tenant_a, tenant_b = await create_two_tenants(db)
        at_b = await create_agent_type(db, tenant_b.id, "at-b3")
        job_b = await create_agent_job(db, tenant_b.id, at_b.id)
        dt_b = await _seed_data_type(db, tenant_b.id)
        await _seed_output(db, tenant_b.id, dt_b.id, at_b.id, job_b.id, 5)

        with pytest.raises(HTTPException) as exc_info:
            await query_result_tool(
                _request(str(job_b.id), {"data_type_name": DATA_TYPE_NAME}),
                _ctx(tenant_a),
                db,
            )
        assert exc_info.value.status_code == 404


class TestSaveDataGetDataContainment:
    async def test_save_data_stamps_tenant_at_db_level(self, db):
        tenant_a, _tenant_b = await create_two_tenants(db)
        at_a = await create_agent_type(db, tenant_a.id, "at-a4")
        job_a = await create_agent_job(db, tenant_a.id, at_a.id)

        response = await save_data_tool(
            _request(
                str(job_a.id),
                {"data_name": "draft", "data_value": {"k": "v"}},
                agent_type_id=str(at_a.id),
            ),
            _ctx(tenant_a),
            db,
        )
        saved_id = response.result["id"]
        row = (
            await db.execute(
                text("SELECT tenant_id FROM agent_data WHERE id = :id"),
                {"id": uuid.UUID(saved_id)},
            )
        ).first()
        assert row is not None and str(row[0]) == str(tenant_a.id)

    async def test_get_data_cross_tenant_returns_nothing(self, db):
        tenant_a, tenant_b = await create_two_tenants(db)
        at_a = await create_agent_type(db, tenant_a.id, "at-a5")
        at_b = await create_agent_type(db, tenant_b.id, "at-b5")
        job_a = await create_agent_job(db, tenant_a.id, at_a.id)
        job_b = await create_agent_job(db, tenant_b.id, at_b.id)

        await save_data_tool(
            _request(
                str(job_a.id),
                {"data_name": "shared-name", "data_value": {"secret": True}},
                agent_type_id=str(at_a.id),
            ),
            _ctx(tenant_a),
            db,
        )

        # Tenant B queries with the IDENTICAL data_name / agent type / session.
        for tool_args in (
            {"data_name": "shared-name"},
            {"agent_type_id": str(at_a.id)},
            {"session_id": str(job_a.id)},
        ):
            response = await get_data_tool(
                _request(str(job_b.id), tool_args),
                _ctx(tenant_b),
                db,
            )
            assert response.result["count"] == 0
            assert response.result["records"] == []

        # ... while tenant A retrieves its own record.
        response = await get_data_tool(
            _request(str(job_a.id), {"data_name": "shared-name"}),
            _ctx(tenant_a),
            db,
        )
        assert response.result["count"] == 1

    async def test_agent_data_service_defense_in_depth(self, db):
        """Direct service-level queries still contain results via the
        explicit tenant predicate (independent of session scoping)."""
        from app.services.agent_data.service import AgentDataService

        tenant_a, tenant_b = await create_two_tenants(db)
        at_a = await create_agent_type(db, tenant_a.id, "at-a6")
        job_a = await create_agent_job(db, tenant_a.id, at_a.id)

        service = AgentDataService()
        await service.save(
            db=db,
            session_id=job_a.id,
            data_name="svc-record",
            data_value={"n": 1},
            agent_type_id=at_a.id,
            tenant_id=tenant_a.id,
        )
        await db.commit()

        own = await service.query_by_filters(
            db=db, data_name="svc-record", tenant_id=tenant_a.id
        )
        assert len(own) == 1
        foreign = await service.query_by_filters(
            db=db, data_name="svc-record", tenant_id=tenant_b.id
        )
        assert foreign == []


class TestOutputsContainment:
    async def test_get_output_returns_only_bound_tenant_outputs(self, db):
        tenant_a, tenant_b = await create_two_tenants(db)
        at_a = await create_agent_type(db, tenant_a.id, "at-a7")
        at_b = await create_agent_type(db, tenant_b.id, "at-b7")
        job_a = await create_agent_job(db, tenant_a.id, at_a.id)
        job_b = await create_agent_job(db, tenant_b.id, at_b.id)
        dt_a = await _seed_data_type(db, tenant_a.id)
        dt_b = await _seed_data_type(db, tenant_b.id)
        await _seed_output(db, tenant_a.id, dt_a.id, at_a.id, job_a.id, 1)
        await _seed_output(db, tenant_b.id, dt_b.id, at_b.id, job_b.id, 2)

        response = await get_output_tool(
            _request(str(job_b.id), {"agent_type_id": str(at_a.id)}),
            _ctx(tenant_b),
            db,
        )
        # Tenant A's agent type id matches nothing inside tenant B.
        assert response.result["count"] == 0
        assert response.result["records"] == []

        response = await get_output_tool(
            _request(str(job_b.id), {"agent_type_id": str(at_b.id)}),
            _ctx(tenant_b),
            db,
        )
        agent_type_ids = {
            r["agent_type_id"] for r in response.result["records"]
        }
        assert agent_type_ids == {str(at_b.id)}

    async def test_output_service_tenant_predicate(self, db):
        from app.services.outputs.service import OutputService

        tenant_a, tenant_b = await create_two_tenants(db)
        at_a = await create_agent_type(db, tenant_a.id, "at-a8")
        at_b = await create_agent_type(db, tenant_b.id, "at-b8")
        job_a = await create_agent_job(db, tenant_a.id, at_a.id)
        job_b = await create_agent_job(db, tenant_b.id, at_b.id)
        dt_a = await _seed_data_type(db, tenant_a.id)
        dt_b = await _seed_data_type(db, tenant_b.id)
        out_a = await _seed_output(db, tenant_a.id, dt_a.id, at_a.id, job_a.id, 1)
        await _seed_output(db, tenant_b.id, dt_b.id, at_b.id, job_b.id, 2)

        service = OutputService()
        items_b, total_b = await service.list_outputs(
            db=db, filters={}, tenant_id=tenant_b.id
        )
        assert total_b == 1 and all(i.tenant_id == tenant_b.id for i in items_b)
        items_a, total_a = await service.list_outputs(
            db=db, filters={}, tenant_id=tenant_a.id
        )
        assert total_a == 1 and items_a[0].id == out_a.id


class TestDecisionToolStrictTenantMatch:
    async def test_decision_tool_resolves_only_within_calling_tenant(self, db):
        """Strict (tenant, name) matching — no ``IS NULL OR own`` fallback."""
        from app.db.models.decision_tools import DecisionTool, DecisionToolStatus
        from app.services.system_one.decision_engine import (
            DecisionExecutionEngine,
            DecisionExecutionError,
        )
        from app.services.system_one.decision_tool_service import DecisionToolService

        tenant_a, tenant_b = await create_two_tenants(db)
        suffix = uuid.uuid4().hex[:6]

        def _tool(tenant_id, name):
            return DecisionTool(
                tenant_id=tenant_id,
                name=name,
                description="d",
                act_threshold=0.8,
                confirm_threshold=0.6,
                provider_model="gpt-4o-mini",
                status=DecisionToolStatus.active,
                enabled=True,
            )

        tool_a = _tool(tenant_a.id, f"tool_{suffix}")
        db.add_all(
            [
                tool_a,
                _tool(tenant_b.id, f"tool_{suffix}"),  # identical name in tenant B
                _tool(tenant_b.id, f"b_only_{suffix}"),  # exists only in tenant B
            ]
        )
        await db.commit()

        engine = DecisionExecutionEngine()
        resolved = await engine.resolve_tool(db, f"tool_{suffix}", tenant_a.id)
        assert resolved.id == tool_a.id

        # A name that exists only in tenant B is unresolvable from tenant A.
        with pytest.raises(DecisionExecutionError):
            await engine.resolve_tool(db, f"b_only_{suffix}", tenant_a.id)

        # Service-level lookup agrees (strict tenant predicate).
        miss = await DecisionToolService().get_by_name(
            db, f"b_only_{suffix}", tenant_a.id
        )
        assert miss is None
