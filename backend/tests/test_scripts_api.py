"""API tests for the Control Center script registry REST router (``/api/v1/scripts``).

Covers:
- CRUD for definitions and versions (G1)
- Lifecycle endpoints: promote/demote/retire with server-side validation (C3,
  V4 — 409 on state-machine violations)
- Version diff endpoint
- Verification / fallback / health read endpoints (V2, F2, F4)
- Execution-mode configuration (E1) and resolution
- Compilation / cost-savings reports (G3, G4)
- Permission gating via ``require_permission()`` against ``agent::scripts``
  (403 when denied; 404 for unknown ids)
"""
from __future__ import annotations

import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_permission
from app.core.resource_types import RT_AGENT_SCRIPTS
from app.db.models.script_execution import (
    ScriptExecutionOutcome,
)
from app.db.models.script_registry import (
    FallbackResultingAction,
    FallbackTriggerReason,
    VerificationComparisonOutcome,
)
from app.db.session import get_db
from app.main import create_app
from app.services.script_registry import ScriptRegistryService
from app.services.tenancy.root_tenant import get_root_tenant_id

MINIMAL_GRAPH = {
    "name": "g",
    "steps": [{"kind": "tool_call", "name": "s1", "tool_name": "a____b"}],
}


def _allow():
    def override():
        return {"sub": "scripts-admin-test", "roles": ["admin"]}

    return override


def _deny():
    async def override():
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Permission denied")

    return override


@pytest.fixture
def _bypass_auth():
    from unittest.mock import patch

    from app.middleware.auth import JWTAuthMiddleware
    from app.middleware.tenant_resolution import TenantResolutionMiddleware

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "scripts-admin-test"}
        return await call_next(request)

    # Tenant resolution would bind the *dev* database's root tenant to the
    # request (AsyncSessionLocal), mismatching the test database's seeded
    # rows.  Pass through so requests run in single-tenant mode (no
    # tenant scoping), consistent with the seeding fixtures.
    async def passthrough_resolution(self, request, call_next):
        request.state.tenancy_enabled = False
        return await call_next(request)

    with patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch), patch.object(
        TenantResolutionMiddleware, "dispatch", passthrough_resolution
    ):
        yield


@pytest_asyncio.fixture
async def client(test_engine, _bypass_auth) -> AsyncGenerator[AsyncClient, None]:
    app = create_app()
    for action in ("read", "manage"):
        app.dependency_overrides[require_permission(RT_AGENT_SCRIPTS, action)] = _allow()

    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _seed_definition(db_session: AsyncSession) -> dict:
    service = ScriptRegistryService()
    definition = await service.create_definition(
        db_session,
        name=f"api-def-{uuid.uuid4().hex[:8]}",
        agent_type_id=uuid.uuid4(),
        tenant_id=await get_root_tenant_id(db_session),
    )
    version = await service.create_version(
        db_session,
        definition_id=definition.id,
        declarative_step_graph=MINIMAL_GRAPH,
    )
    return {"definition": definition, "version": version}


@pytest_asyncio.fixture
async def seeded(db_session):
    seeded_data = await _seed_definition(db_session)
    # The API uses a separate session; make seeded rows visible to it.
    await db_session.commit()
    return seeded_data


# ── Definitions ───────────────────────────────────────────────────────────────


class TestDefinitionCrud:
    async def test_list_scripts_returns_list_shape(self, client):
        response = await client.get("/api/v1/scripts")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body["items"], list)
        assert body["total"] == len(body["items"])

    async def test_create_definition_returns_201(self, client, db_session):
        response = await client.post(
            "/api/v1/scripts",
            json={
                "name": f"api-created-{uuid.uuid4().hex[:8]}",
                "agent_type_id": str(uuid.uuid4()),
                "description": "created via REST",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["lifecycle_status"] == "draft"
        assert body["health_status"] == "healthy"

    async def test_create_definition_validation_error(self, client):
        response = await client.post(
            "/api/v1/scripts", json={"name": "", "agent_type_id": str(uuid.uuid4())}
        )
        assert response.status_code == 422

    async def test_get_script_404_for_unknown_id(self, client):
        response = await client.get(f"/api/v1/scripts/{uuid.uuid4()}")
        assert response.status_code == 404

    async def test_get_script_returns_versions(self, client, db_session, seeded):
        response = await client.get(f"/api/v1/scripts/{seeded['definition'].id}")
        assert response.status_code == 200
        assert response.json()["id"] == str(seeded["definition"].id)

    async def test_list_versions(self, client, db_session, seeded):
        response = await client.get(
            f"/api/v1/scripts/{seeded['definition'].id}/versions"
        )
        assert response.status_code == 200
        versions = response.json()
        assert len(versions) == 1
        assert versions[0]["declarative_step_graph"] == MINIMAL_GRAPH

    async def test_create_version_via_rest(self, client, db_session, seeded):
        response = await client.post(
            f"/api/v1/scripts/{seeded['definition'].id}/versions",
            json={"declarative_step_graph": MINIMAL_GRAPH, "version_label": "vX"},
        )
        assert response.status_code == 201
        assert response.json()["version_label"] == "vX"

    async def test_create_version_for_unknown_definition_404(self, client):
        response = await client.post(
            f"/api/v1/scripts/{uuid.uuid4()}/versions",
            json={"declarative_step_graph": MINIMAL_GRAPH},
        )
        assert response.status_code == 404

    async def test_version_diff_endpoint(self, client, db_session):
        service = ScriptRegistryService()
        definition = await service.create_definition(
            db_session,
            name=f"diff-def-{uuid.uuid4().hex[:8]}",
            agent_type_id=uuid.uuid4(),
        )
        graph_a = {
            "name": "g",
            "steps": [{"kind": "tool_call", "name": "s1", "tool_name": "a____b"}],
        }
        graph_b = {
            "name": "g",
            "steps": [
                {"kind": "tool_call", "name": "s1", "tool_name": "a____b"},
                {"kind": "tool_call", "name": "s2", "tool_name": "c____d"},
            ],
        }
        v1 = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=graph_a
        )
        v2 = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=graph_b
        )
        response = await client.get(
            f"/api/v1/scripts/{definition.id}/versions/{v2.id}/diff",
            params={"against": str(v1.id)},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["steps_added"] == ["s2"]

    async def test_diff_missing_against_param_422(self, client, db_session, seeded):
        response = await client.get(
            f"/api/v1/scripts/{seeded['definition'].id}/versions/{seeded['version'].id}/diff"
        )
        assert response.status_code == 422


# ── Lifecycle transitions ─────────────────────────────────────────────────────


class TestLifecycleEndpoints:
    async def test_promote_draft_without_verification_409(self, client, db_session, seeded):
        response = await client.post(
            f"/api/v1/scripts/{seeded['definition'].id}/versions/{seeded['version'].id}/promote",
            json={"target_status": "verified"},
        )
        assert response.status_code == 409
        assert "verification" in response.json()["detail"]

    async def test_promote_draft_to_compiled_ok_auto_compile_path(self, client, db_session, seeded):
        # Auto-compile promotes directly: the recorded LLM run is the evidence,
        # and dispatch falls back to the LLM unconditionally on script failure.
        response = await client.post(
            f"/api/v1/scripts/{seeded['definition'].id}/versions/{seeded['version'].id}/promote",
            json={"target_status": "compiled"},
        )
        assert response.status_code == 200
        assert response.json()["lifecycle_status"] == "compiled"

    async def test_retire_draft_version_ok(self, client, db_session, seeded):
        response = await client.post(
            f"/api/v1/scripts/{seeded['definition'].id}/versions/{seeded['version'].id}/retire"
        )
        assert response.status_code == 200
        assert response.json()["lifecycle_status"] == "retired"

    async def test_retire_twice_409_terminal_state(self, client, db_session, seeded):
        url = f"/api/v1/scripts/{seeded['definition'].id}/versions/{seeded['version'].id}/retire"
        assert (await client.post(url)).status_code == 200
        assert (await client.post(url)).status_code == 409

    async def test_promote_unknown_version_404(self, client, db_session, seeded):
        response = await client.post(
            f"/api/v1/scripts/{seeded['definition'].id}/versions/{uuid.uuid4()}/promote",
            json={"target_status": "verified"},
        )
        assert response.status_code == 404


# ── Verification / fallbacks / health ─────────────────────────────────────────


class TestEvidenceEndpoints:
    async def test_verifications_listed_after_submission(
        self, client, db_session, seeded
    ):
        service = ScriptRegistryService()
        await service.record_verification(
            db_session,
            version_id=seeded["version"].id,
            comparison_outcome=VerificationComparisonOutcome.match,
        )
        response = await client.get(
            f"/api/v1/scripts/{seeded['definition'].id}/verifications"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["verdict"] == "promoted"

    async def test_fallbacks_and_health_after_fallback(self, client, db_session, seeded):
        service = ScriptRegistryService()
        version = seeded["version"]
        execution = await service.record_execution(
            db_session,
            outcome=ScriptExecutionOutcome.fell_back,
            script_version_id=version.id,
        )
        await service.record_fallback(
            db_session,
            execution_record_id=execution.id,
            script_version_id=version.id,
            trigger_reason=FallbackTriggerReason.execution_error,
            resulting_action=FallbackResultingAction.llm_completed,
            failure_detail="boom",
        )
        fallbacks = await client.get(f"/api/v1/scripts/{seeded['definition'].id}/fallbacks")
        assert fallbacks.status_code == 200
        assert fallbacks.json()["total"] == 1
        assert fallbacks.json()["items"][0]["failure_detail"] == "boom"

        health = await client.get(f"/api/v1/scripts/{seeded['definition'].id}/health")
        assert health.status_code == 200
        assert health.json()["total_fallback_count"] == 1


class TestReportEndpoints:
    async def test_compilation_report_empty_history(self, client):
        response = await client.get("/api/v1/scripts/reports/compilation")
        assert response.status_code == 200
        body = response.json()
        assert body["total_executions"] >= 0
        assert isinstance(body["script_hit_rate"], float)
        assert isinstance(body["fallback_rate"], float)

    async def test_cost_savings_report_shape(self, client):
        response = await client.get("/api/v1/scripts/reports/cost-savings")
        assert response.status_code == 200
        body = response.json()
        for key in (
            "total_executions",
            "script_runs",
            "llm_runs",
            "fallback_runs",
            "script_hit_rate",
            "fallback_rate",
            "tokens_saved_total",
            "residual_model_backed_steps",
        ):
            assert key in body

    async def test_executions_audit_listing(self, client):
        response = await client.get("/api/v1/scripts/executions")
        assert response.status_code == 200
        assert "items" in response.json()


# ── Permission gating ─────────────────────────────────────────────────────────


class TestPermissionGating:
    async def test_denied_permission_returns_403(self, test_engine, _bypass_auth):
        app = create_app()
        for action in ("read", "manage"):
            app.dependency_overrides[require_permission(RT_AGENT_SCRIPTS, action)] = _deny()

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )

        async def override_db():
            async with SessionLocal() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            read = await client.get("/api/v1/scripts")
            manage = await client.post(
                "/api/v1/scripts",
                json={"name": "x", "agent_type_id": str(uuid.uuid4())},
            )
        assert read.status_code == 403
        assert manage.status_code == 403


# ── Execution modes removed; repairs endpoint present (E10, refinement) ───────


class TestModesRemovedRepairsPresent:
    def test_no_mode_endpoints_in_openapi(self):
        """No execution-mode endpoints exist anywhere in the OpenAPI schema —
        modes were removed; script-first dispatch is the fixed strategy."""
        from fastapi.routing import APIRoute

        app = create_app()
        paths = {
            route.path
            for route in app.routes
            if isinstance(route, APIRoute)
        }
        mode_paths = [p for p in paths if "mode" in p and "scripts" in p]
        assert mode_paths == []
        schema = app.openapi()
        script_paths = [p for p in schema["paths"] if "/scripts" in p]
        assert script_paths, "script endpoints must be registered"
        assert not [
            p for p in script_paths if "execution-mode" in p or p.rstrip("/").endswith("/mode")
        ]

    def test_no_execution_mode_configuration_model_registered(self):
        """The ExecutionModeConfiguration model is gone from the codebase."""
        import app.db.models.script_execution as se

        assert not hasattr(se, "ExecutionModeConfiguration")

    async def test_repairs_endpoint_lists_attempts(
        self, client, db_session, seeded
    ):
        from app.db.models.script_registry import RepairAttempt, RepairRetryOutcome

        definition, version = seeded["definition"], seeded["version"]
        service = ScriptRegistryService()
        tenant_id = await get_root_tenant_id(db_session)
        execution = await service.record_execution(
            db_session,
            outcome=ScriptExecutionOutcome.fell_back,
            script_version_id=version.id,
            tenant_id=tenant_id,
        )
        event = await service.record_fallback(
            db_session,
            execution_record_id=execution.id,
            script_version_id=version.id,
            trigger_reason=FallbackTriggerReason.execution_error,
            resulting_action=FallbackResultingAction.repair_not_produced,
            failure_detail="tool args drifted",
            tenant_id=tenant_id,
        )
        attempt = RepairAttempt(
            tenant_id=definition.tenant_id,
            fallback_event_id=event.id,
            script_version_id=version.id,
            defect_diagnosis="tool args drifted from schema",
            diff_applied="repair attempt 1 (execution_error)",
            retry_outcome=RepairRetryOutcome.pending,
        )
        db_session.add(attempt)
        await db_session.flush()

        response = await client.get(f"/api/v1/scripts/{definition.id}/repairs")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["defect_diagnosis"] == "tool args drifted from schema"
        assert body["items"][0]["retry_outcome"] == "pending"

    async def test_repairs_endpoint_permission_gated(
        self, test_engine, _bypass_auth, seeded
    ):
        app = create_app()
        for action in ("read", "manage"):
            app.dependency_overrides[require_permission(RT_AGENT_SCRIPTS, action)] = _deny()

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )

        async def override_db():
            async with SessionLocal() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as denied:
            response = await denied.get(
                f"/api/v1/scripts/{seeded['definition'].id}/repairs"
            )
        assert response.status_code == 403
