"""API tests for the internal CC↔AR script endpoints (``/api/v1/internal/scripts``).

Covers:
- Candidate / verification / fallback / execution / repair submission flows
- Serving-version lookup for the Script-First Dispatcher (E1–E3; no modes)
- LLM-reference fetch for shadow comparison (V1)
- Certificate rules on ``/internal/*``: no certificate → 401,
  agent-instance certificate → 403 (SEC4, existing middleware)
"""
from __future__ import annotations

import uuid
from typing import Any, AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_internal_tenant_context, require_service_certificate
from app.db.models.conversations import ConversationSession, ConversationTurn, TurnRole
from app.db.models.script_registry import VerificationComparisonOutcome
from app.db.session import get_db
from app.main import create_app
from app.services.script_registry import ScriptRegistryService
from app.services.tenancy.root_tenant import ensure_root_tenant, get_root_tenant_id

MINIMAL_GRAPH = {
    "name": "g",
    "steps": [{"kind": "tool_call", "name": "s1", "tool_name": "a____b"}],
}


def _bypass_service_cert():
    async def override():
        return {"cert_type": "service", "service_name": "agent-runtime"}

    return override


@pytest_asyncio.fixture
async def internal_client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """Client with service-cert + internal tenant deps overridden, real in-memory DB."""
    app = create_app()
    app.dependency_overrides[require_service_certificate] = _bypass_service_cert()

    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db

    async with SessionLocal() as session:
        await ensure_root_tenant(session)
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest_asyncio.fixture
async def tenant_id(db_session) -> uuid.UUID:
    return await get_root_tenant_id(db_session)


async def _submit_candidate(client: AsyncClient, agent_type_id: uuid.UUID, **overrides) -> dict:
    payload: dict[str, Any] = {
        "agent_type_id": str(agent_type_id),
        "name": f"internal-def-{uuid.uuid4().hex[:8]}",
        "declarative_step_graph": MINIMAL_GRAPH,
    }
    payload.update(overrides)
    response = await client.post("/api/v1/internal/scripts/candidates", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# ── Candidates ────────────────────────────────────────────────────────────────


class TestCandidateSubmission:
    async def test_candidate_creates_definition_and_draft_version(
        self, internal_client, tenant_id
    ):
        body = await _submit_candidate(internal_client, uuid.uuid4())
        assert body["lifecycle_status"] == "draft"
        assert body["version_label"] == "v1"
        assert body["declarative_step_graph"] == MINIMAL_GRAPH

    async def test_second_candidate_same_name_appends_version(
        self, internal_client
    ):
        agent_type_id = uuid.uuid4()
        name = f"internal-def-{uuid.uuid4().hex[:8]}"
        first = await _submit_candidate(internal_client, agent_type_id, name=name)
        second = await _submit_candidate(internal_client, agent_type_id, name=name)
        assert second["script_definition_id"] == first["script_definition_id"]
        assert second["version_label"] == "v2"

    async def test_candidate_requires_step_graph(self, internal_client):
        response = await internal_client.post(
            "/api/v1/internal/scripts/candidates",
            json={"agent_type_id": str(uuid.uuid4()), "name": "no-graph"},
        )
        assert response.status_code == 422


# ── Serving-version lookup & version fetch (script-first dispatch) ───────────


class TestServingVersionAndVersions:
    async def test_compiled_version_fetch(self, internal_client):
        body = await _submit_candidate(internal_client, uuid.uuid4())
        response = await internal_client.get(
            f"/api/v1/internal/scripts/versions/{body['id']}"
        )
        assert response.status_code == 200
        assert response.json()["declarative_step_graph"] == MINIMAL_GRAPH

    async def test_unknown_version_404(self, internal_client):
        response = await internal_client.get(
            f"/api/v1/internal/scripts/versions/{uuid.uuid4()}"
        )
        assert response.status_code == 404


# ── Verification submission (V1–V3) ───────────────────────────────────────────


class TestVerificationSubmission:
    async def test_match_verdict_recorded(self, internal_client):
        body = await _submit_candidate(internal_client, uuid.uuid4())
        response = await internal_client.post(
            "/api/v1/internal/scripts/verifications",
            json={
                "script_version_id": body["id"],
                "comparison_outcome": "match",
                "expected_output": {"result": 1},
                "actual_output": {"result": 1},
                "input_context": {"ticket": "T-1"},
                "reference_execution_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 201
        assert response.json()["verdict"] == "promoted"
        assert response.json()["input_context"] == {"ticket": "T-1"}

    async def test_mismatch_keeps_draft_with_reason(self, internal_client):
        body = await _submit_candidate(internal_client, uuid.uuid4())
        response = await internal_client.post(
            "/api/v1/internal/scripts/verifications",
            json={
                "script_version_id": body["id"],
                "comparison_outcome": "mismatch",
                "verdict_reason": "output mismatch",
            },
        )
        assert response.status_code == 201
        assert response.json()["verdict"] == "rejected"

    async def test_unknown_version_404(self, internal_client):
        response = await internal_client.post(
            "/api/v1/internal/scripts/verifications",
            json={
                "script_version_id": str(uuid.uuid4()),
                "comparison_outcome": "match",
            },
        )
        assert response.status_code == 404

    async def test_invalid_outcome_rejected(self, internal_client):
        response = await internal_client.post(
            "/api/v1/internal/scripts/verifications",
            json={
                "script_version_id": str(uuid.uuid4()),
                "comparison_outcome": "probably_fine",
            },
        )
        assert response.status_code == 422


# ── Fallback & execution reporting (F2, G2) ───────────────────────────────────


class TestFallbackAndExecutionReporting:
    async def test_execution_report(self, internal_client):
        response = await internal_client.post(
            "/api/v1/internal/scripts/executions",
            json={
                "outcome": "success",
                "script_version_id": str(uuid.uuid4()),
                "duration_ms": 120,
                "tools_invoked": [{"step": "s1", "tool_name": "a____b"}],
                "model_backed_steps_used": [],
                "session_id": str(uuid.uuid4()),
                "tokens_saved_estimate": 2000,
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["tokens_saved_estimate"] == 2000
        assert "execution_mode" not in body

    async def test_fallback_report_with_execution_link(self, internal_client):
        execution = (
            await internal_client.post(
                "/api/v1/internal/scripts/executions",
                json={
                        "outcome": "fell_back",
                    "script_version_id": str(uuid.uuid4()),
                },
            )
        ).json()
        response = await internal_client.post(
            "/api/v1/internal/scripts/fallbacks",
            json={
                "execution_record_id": execution["id"],
                "script_version_id": execution["script_version_id"],
                "trigger_reason": "tool_schema_mismatch",
                "resulting_action": "llm_completed",
                "failure_detail": "missing expected keys: ['id']",
            },
        )
        assert response.status_code == 201
        assert response.json()["script_health_impact"] == 1

    async def test_invalid_trigger_reason_rejected(self, internal_client):
        response = await internal_client.post(
            "/api/v1/internal/scripts/fallbacks",
            json={
                "execution_record_id": str(uuid.uuid4()),
                "trigger_reason": "vibes",
                "resulting_action": "llm_completed",
            },
        )
        assert response.status_code == 422


async def _compiled_definition(db_session, agent_type_id=None):
    from app.db.models.script_registry import ScriptLifecycleStatus

    service = ScriptRegistryService()
    tenant_id = await get_root_tenant_id(db_session)
    definition = await service.create_definition(
        db_session,
        name=f"serving-def-{uuid.uuid4().hex[:8]}",
        agent_type_id=agent_type_id or uuid.uuid4(),
        tenant_id=tenant_id,
    )
    version = await service.create_version(
        db_session,
        definition_id=definition.id,
        declarative_step_graph=MINIMAL_GRAPH,
    )
    await service.record_verification(
        db_session,
        version_id=version.id,
        comparison_outcome=VerificationComparisonOutcome.match,
        expected_output={"result": 1},
        actual_output={"result": 1},
    )
    await service.transition_version(
        db_session, version.id, ScriptLifecycleStatus.compiled
    )
    return definition, version


# ── Serving-version lookup (E1–E3; script-first, no modes) ────────────────────


class TestServingVersionLookup:
    async def test_serving_version_returned_for_compiled_workflow(
        self, internal_client, db_session
    ):
        definition, version = await _compiled_definition(db_session)
        await db_session.commit()
        response = await internal_client.get(
            "/api/v1/internal/scripts/serving-version",
            params={"agent_type_id": str(definition.agent_type_id)},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["script_version_id"] == str(version.id)
        assert body["script_definition_id"] == str(definition.id)
        assert body["declarative_step_graph"] == MINIMAL_GRAPH
        # No execution modes exist — no mode attribute in the response
        assert "execution_mode" not in body
        assert "mode" not in body

    async def test_no_serving_version_returns_empty(self, internal_client):
        """No compiled script → no serving version; the dispatcher takes the
        LLM path without error (E3)."""
        response = await internal_client.get(
            "/api/v1/internal/scripts/serving-version",
            params={"agent_type_id": str(uuid.uuid4())},
        )
        assert response.status_code == 200
        assert response.json()["script_version_id"] is None


# ── Repair attempts (E9/E10, F3) ──────────────────────────────────────────────


class TestRepairSubmission:
    async def test_repair_creates_attempt_and_linked_draft(
        self, internal_client, db_session
    ):
        from app.db.models.script_registry import RepairAttempt

        _, version = await _compiled_definition(db_session)
        await db_session.commit()
        response = await internal_client.post(
            "/api/v1/internal/scripts/repairs",
            json={
                "script_version_id": str(version.id),
                "declarative_step_graph": MINIMAL_GRAPH,
                "defect_diagnosis": "tool schema drifted: missing 'id' key",
                "diff_applied": "repair attempt 1 (tool_schema_mismatch)",
                "attempt_number": 1,
                "created_by": "agent-runtime-repair-loop",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["script_version_id"] == str(version.id)
        assert body["defect_diagnosis"] == "tool schema drifted: missing 'id' key"
        assert body["retry_outcome"] == "pending"
        assert body["repaired_version_id"]
        # The repaired candidate exists as a new draft version with lineage
        repaired = await internal_client.get(
            f"/api/v1/internal/scripts/versions/{body['repaired_version_id']}"
        )
        assert repaired.status_code == 200
        assert repaired.json()["lifecycle_status"] == "draft"
        # The RepairAttempt row is persisted and listed per script
        listing = await internal_client.get(
            "/api/v1/internal/scripts/repairs",
            params={"script_id": str(version.script_definition_id)},
        )
        assert listing.status_code == 200
        items = listing.json()["items"]
        assert [a["id"] for a in items] == [body["id"]]

    async def test_repair_unknown_version_404(self, internal_client):
        response = await internal_client.post(
            "/api/v1/internal/scripts/repairs",
            json={
                "script_version_id": str(uuid.uuid4()),
                "declarative_step_graph": MINIMAL_GRAPH,
                "defect_diagnosis": "no such version",
            },
        )
        assert response.status_code == 404


# ── LLM reference fetch (V1) ──────────────────────────────────────────────────


class TestLlmReferenceFetch:
    async def test_unknown_session_404(self, internal_client):
        response = await internal_client.get(
            f"/api/v1/internal/scripts/llm-reference/{uuid.uuid4()}"
        )
        assert response.status_code == 404

    async def test_reference_returns_turns_and_tool_calls(
        self, internal_client, db_session, tenant_id
    ):
        session = ConversationSession(
            tenant_id=tenant_id,
            agent_type_id=uuid.uuid4(),
            title="reference run",
        )
        db_session.add(session)
        await db_session.flush()
        turn_user = ConversationTurn(
            session_id=session.id, role=TurnRole.user, content="do the thing"
        )
        turn_agent = ConversationTurn(
            session_id=session.id, role=TurnRole.agent, content="done"
        )
        db_session.add_all([turn_user, turn_agent])
        await db_session.flush()
        response = await internal_client.get(
            f"/api/v1/internal/scripts/llm-reference/{session.id}"
        )
        assert response.status_code == 200
        body = response.json()
        assert [t["content"] for t in body["turns"]] == ["do the thing", "done"]
        assert body["tool_calls"] == []


# ── Certificate rules (SEC4) ──────────────────────────────────────────────────


class TestCertificateRules:
    async def test_no_certificate_rejected_on_internal_scripts(self, test_engine):
        """No cert header → 401 (fail-closed middleware, no override)."""
        from unittest.mock import patch

        from app.middleware.auth import JWTAuthMiddleware

        async def patched_dispatch(self, request, call_next):
            request.state.identity = {}
            return await call_next(request)

        app = create_app()
        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )

        async def override_db():
            async with SessionLocal() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        with patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/v1/internal/scripts/serving-version",
                    params={"agent_type_id": str(uuid.uuid4())},
                )
        assert response.status_code == 401

    async def test_agent_instance_certificate_rejected_with_403(
        self, test_engine, db_session
    ):
        """Agent-instance certs are explicitly blocked from /internal/* (403)."""
        import app.services.certificate_authority as ca_module
        from unittest.mock import patch

        from app.middleware.auth import JWTAuthMiddleware
        from app.services.certificate_authority import CertificateAuthorityService

        ca_module._ca_private_key = None
        ca_module._ca_certificate = None
        try:
            app = create_app()
            SessionLocal = async_sessionmaker(
                bind=test_engine, class_=AsyncSession, expire_on_commit=False
            )

            async def override_db():
                async with SessionLocal() as session:
                    yield session

            app.dependency_overrides[get_db] = override_db

            async def patched_dispatch(self, request, call_next):
                request.state.identity = {}
                return await call_next(request)

            svc = CertificateAuthorityService()
            await svc.initialize(db_session)
            issued = await svc.issue(
                agent_type_id=uuid.uuid4(),
                instance_id="rogue-instance",
                db=db_session,
            )

            with patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(
                        "/api/v1/internal/scripts/serving-version",
                        params={"agent_type_id": str(uuid.uuid4())},
                        headers={
                            "X-Client-Certificate": issued.certificate_pem.replace(
                                "\n", "\\n"
                            )
                        },
                    )
            assert response.status_code == 403
            assert "agent-instance" in response.json()["detail"].lower()
        finally:
            ca_module._ca_private_key = None
            ca_module._ca_certificate = None

    async def test_service_certificate_accepted(self, test_engine, db_session):
        """A valid service certificate passes require_service_certificate."""
        from unittest.mock import patch

        from app.middleware.auth import JWTAuthMiddleware
        from app.services.certificate_authority import (
            CertificateAuthorityService,
            issue_service_certificate,
        )

        ca_module = __import__(
            "app.services.certificate_authority", fromlist=["*"]
        )
        ca_module._ca_private_key = None
        ca_module._ca_certificate = None
        try:
            app = create_app()
            SessionLocal = async_sessionmaker(
                bind=test_engine, class_=AsyncSession, expire_on_commit=False
            )

            async def override_db():
                async with SessionLocal() as session:
                    yield session
                    await session.commit()

            app.dependency_overrides[get_db] = override_db

            async def patched_dispatch(self, request, call_next):
                request.state.identity = {}
                return await call_next(request)

            svc = CertificateAuthorityService()
            await svc.initialize(db_session)
            await ensure_root_tenant(db_session)
            issued = await issue_service_certificate("agent-runtime")

            with patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(
                        "/api/v1/internal/scripts/serving-version",
                        params={"agent_type_id": str(uuid.uuid4())},
                        headers={
                            "X-Client-Certificate": issued.certificate_pem.replace(
                                "\n", "\\n"
                            )
                        },
                    )
            assert response.status_code == 200, response.text
            body = response.json()
            # Script-first serving lookup (no modes): no compiled script for
            # a random agent type → no serving version, LLM path by default.
            assert body["script_version_id"] is None
            assert "mode" not in body
        finally:
            ca_module._ca_private_key = None
            ca_module._ca_certificate = None


class TestOptimizedPlanLookupAllowlisted:
    """Regression for FIX (allowlist): AR's optimized-plan lookup was rejected
    with 403 endpoint_not_allowlisted because the endpoint was missing from the
    AR internal allowlist — dispatch silently degraded to the base-plan path.
    The endpoint must be callable by an Agent Runtime service certificate."""

    async def test_optimized_plan_lookup_not_allowlist_denied(self, internal_client):
        response = await internal_client.get(
            "/api/v1/internal/scripts/optimized-plan",
            params={"agent_type_id": "00000000-0000-0000-0000-000000000001"},
        )
        assert response.status_code != 403
        detail = response.json().get("detail")
        assert not (
            isinstance(detail, dict) and detail.get("reason") == "endpoint_not_allowlisted"
        ), "optimized-plan lookup must be in the AR internal allowlist"

    async def test_optimized_plan_lookup_returns_payload(self, internal_client):
        # Unknown agent type → 404 (no optimized plan); the contract under
        # test is that AR callers are NOT allowlist-denied.
        response = await internal_client.get(
            "/api/v1/internal/scripts/optimized-plan",
            params={"agent_type_id": "00000000-0000-0000-0000-000000000001"},
        )
        assert response.status_code in (200, 404)
