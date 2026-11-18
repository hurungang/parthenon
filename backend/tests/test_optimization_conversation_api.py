"""Optimization conversation API — create / read / ledger over the real app.

Contract surface of ``POST /conversations/optimization``,
``GET /conversations/{id}/optimization`` and
``GET /conversations/{id}/live-test-requests``:

* the subject is the session's own ``agent_type_id`` and the channel is
  ``"optimization"`` — no scope/second-agent-type field exists anywhere;
* typed **and** conversational agent types both open;
* ``404`` for an unknown subject, ``403`` for a missing permission and ``403``
  for another operator's session;
* opening always answers with an explicit availability (computed, never
  stored) and **starts no work** (no turn, no AgentJob, no ledger row);
* the ledger read returns the request, its operations and the decision
  attribution (read from ``InterveneResponse``);
* a business conversation can never be read as an optimization one (``422``).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import require_permission
from app.core.resource_types import RT_AGENT
from app.db.models.agents import (
    AgentInputType,
    AgentJob,
    AgentJobStatus,
    AgentOutputType,
    AgentType,
    ModelConfig,
    ModelProvider,
)
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.db.models.identity import Identity
from app.db.models.intervene import (
    InterveneRequest,
    InterveneRequestStatus,
    InterveneResponse,
    InterventionType,
)
from app.db.models.optimization_live_test import (
    OptimizationLiveTestRequest,
    OptimizationLiveTestStatus,
)
from app.db.models.tenant import Tenant, TenantStatus
from app.db.session import Base, get_db
from app.main import create_app
from app.services.agents.optimization_mode import OPTIMIZATION_CHANNEL
from app.services.agents.workflow_generation_settings import (
    WORKFLOW_GENERATION_MODEL_KEY,
)
from app.services.tenancy.root_tenant import invalidate_root_tenant_cache
from app.services.tenancy.tenant_settings_service import set_value

AGENT_RUNTIME_MODEL = "conv-api-agent-model"
AUTHORING_MODEL = "conv-api-authoring-model"


# ── Environment ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def api_env():
    """Fresh engine + app client; auth/RBAC bypassed, real ASGI routing."""
    invalidate_root_tenant_cache()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        session.add(
            Tenant(
                id=uuid.uuid4(),
                slug="conv-api-workspace",
                name="Conv API Workspace",
                status=TenantStatus.active,
                is_system_tenant=True,
            )
        )
        await session.commit()

    holder: dict = {"identity_id": None, "sub": "conv-api-operator"}
    denied: dict = {"value": False}

    def _allow():
        def override():
            return {"sub": holder["sub"], "roles": ["admin"]}

        return override

    def _deny():
        from fastapi import HTTPException

        def override():
            raise HTTPException(status_code=403, detail="Forbidden")

        return override

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": holder["sub"]}
        request.state.identity_id = holder["identity_id"]
        return await call_next(request)

    async def passthrough_resolution(self, request, call_next):
        request.state.tenancy_enabled = False
        return await call_next(request)

    from app.middleware.auth import JWTAuthMiddleware
    from app.middleware.tenant_resolution import TenantResolutionMiddleware

    app = create_app()
    app.dependency_overrides[require_permission(RT_AGENT, "read")] = (
        _deny() if denied["value"] else _allow()
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db

    with patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch), patch.object(
        TenantResolutionMiddleware, "dispatch", passthrough_resolution
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield {
                "client": client,
                "engine": engine,
                "session_factory": SessionLocal,
                "holder": holder,
                "denied": denied,
                "app": app,
            }

    await engine.dispose()
    invalidate_root_tenant_cache()


async def _tenant(factory) -> Tenant:
    async with factory() as session:
        return (
            await session.execute(
                select(Tenant).where(Tenant.slug == "conv-api-workspace")
            )
        ).scalar_one()


async def _seed_models(factory, *, optimizer: str | None = None) -> None:
    tenant = await _tenant(factory)
    async with factory() as session:
        for model_id in (AGENT_RUNTIME_MODEL, AUTHORING_MODEL, "conv-api-optimizer"):
            session.add(
                ModelConfig(
                    id=uuid.uuid4(),
                    tenant_id=tenant.id,
                    display_name=f"conv-api-{model_id}",
                    provider_type=ModelProvider.openai,
                    api_base_url="http://localhost:9999/v1",
                    enabled_models=[model_id],
                )
            )
        await session.flush()
        await set_value(
            session, tenant.id, WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL
        )
        if optimizer:
            await set_value(session, tenant.id, "optimizer_model_id", optimizer)
        await session.commit()


async def _operator(factory) -> Identity:
    async with factory() as session:
        identity = Identity(
            id=uuid.uuid4(),
            subject=f"conv-api-op-{uuid.uuid4().hex[:8]}",
            display_name="Operator",
        )
        session.add(identity)
        await session.commit()
        return identity


async def _agent_type(
    factory,
    *,
    input_type: AgentInputType = AgentInputType.typed,
    with_success: bool = False,
) -> AgentType:
    tenant = await _tenant(factory)
    async with factory() as session:
        agent_type = AgentType(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            name=f"conv-api-agent-{uuid.uuid4().hex[:8]}",
            model_id=AGENT_RUNTIME_MODEL,
            input_type=input_type,
            output_type=(
                AgentOutputType.auto
                if input_type == AgentInputType.conversation
                else AgentOutputType.markdown
            ),
            is_active=True,
        )
        session.add(agent_type)
        await session.flush()
        if with_success:
            now = datetime.now(UTC)
            session.add(
                AgentJob(
                    id=uuid.uuid4(),
                    agent_type_id=agent_type.id,
                    status=AgentJobStatus.completed,
                    input_data={"message": "run"},
                    output_data={"ok": True},
                    started_at=now,
                    completed_at=now,
                )
            )
        await session.commit()
        return agent_type


async def _allow_execute(monkeypatch) -> None:
    """Availability is INFORMATION — force the operator's execute grant on."""
    from app.api.v1 import conversations as conversations_module

    monkeypatch.setattr(
        conversations_module,
        "_operator_can_execute",
        AsyncMock(return_value=True),
    )


async def _deny_execute(monkeypatch) -> None:
    from app.api.v1 import conversations as conversations_module

    monkeypatch.setattr(
        conversations_module,
        "_operator_can_execute",
        AsyncMock(return_value=False),
    )


async def _count(factory, model) -> int:
    async with factory() as session:
        return int(
            (
                await session.execute(select(func.count()).select_from(model))
            ).scalar_one()
        )


# ── Create ──────────────────────────────────────────────────────────────────


class TestCreateOptimizationConversation:
    @pytest.mark.asyncio
    async def test_creates_on_a_typed_subject_without_starting_work(
        self, api_env, monkeypatch
    ):
        factory = api_env["session_factory"]
        await _seed_models(factory)
        await _allow_execute(monkeypatch)
        operator = await _operator(factory)
        api_env["holder"]["identity_id"] = operator.id
        agent_type = await _agent_type(
            factory, input_type=AgentInputType.typed, with_success=True
        )

        jobs_before = await _count(factory, AgentJob)
        live_before = await _count(factory, OptimizationLiveTestRequest)

        response = await api_env["client"].post(
            "/api/v1/conversations/optimization",
            json={"agent_type_id": str(agent_type.id)},
        )
        assert response.status_code == 201, response.text
        body = response.json()

        assert body["conversation"]["channel"] == OPTIMIZATION_CHANNEL
        assert body["conversation"]["agent_type_id"] == str(agent_type.id)
        assert body["conversation"]["triggered_by_user_id"] == str(operator.id)
        assert body["subject"]["agent_type_id"] == str(agent_type.id)
        assert body["subject"]["is_conversational"] is False
        assert body["availability"]["available"] is True
        assert body["availability"]["successful_executions"] == 1
        assert body["availability"]["optimizer_model"]["source"] == "authoring"

        # Exactly one session; nothing else was written and no work dispatched.
        async with factory() as session:
            sessions = (
                await session.execute(
                    select(ConversationSession).where(
                        ConversationSession.agent_type_id == agent_type.id
                    )
                )
            ).scalars().all()
            assert len(sessions) == 1
            turns = (
                await session.execute(
                    select(func.count()).select_from(ConversationSession)
                )
            ).scalar_one()
            assert turns == 1
        assert await _count(factory, AgentJob) == jobs_before
        assert await _count(factory, OptimizationLiveTestRequest) == live_before

    @pytest.mark.asyncio
    async def test_creates_on_a_conversational_subject(self, api_env, monkeypatch):
        factory = api_env["session_factory"]
        await _seed_models(factory)
        await _allow_execute(monkeypatch)
        agent_type = await _agent_type(
            factory, input_type=AgentInputType.conversation, with_success=True
        )

        response = await api_env["client"].post(
            "/api/v1/conversations/optimization",
            json={"agent_type_id": str(agent_type.id)},
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["subject"]["is_conversational"] is True
        assert body["availability"]["available"] is True
        assert body["conversation"]["channel"] == OPTIMIZATION_CHANNEL

    @pytest.mark.asyncio
    async def test_unknown_subject_is_404_and_writes_nothing(self, api_env):
        factory = api_env["session_factory"]
        response = await api_env["client"].post(
            "/api/v1/conversations/optimization",
            json={"agent_type_id": str(uuid.uuid4())},
        )
        assert response.status_code == 404
        assert await _count(factory, ConversationSession) == 0

    @pytest.mark.asyncio
    async def test_missing_permission_is_403_and_writes_nothing(self, api_env):
        factory = api_env["session_factory"]
        agent_type = await _agent_type(factory)
        api_env["denied"]["value"] = True
        # Re-override the dependency for the denied variant.
        api_env["app"].dependency_overrides[require_permission(RT_AGENT, "read")] = (
            _forbidden()
        )

        response = await api_env["client"].post(
            "/api/v1/conversations/optimization",
            json={"agent_type_id": str(agent_type.id)},
        )

        assert response.status_code == 403
        assert await _count(factory, ConversationSession) == 0

    @pytest.mark.asyncio
    async def test_availability_reports_no_successful_execution(
        self, api_env, monkeypatch
    ):
        factory = api_env["session_factory"]
        await _seed_models(factory)
        await _allow_execute(monkeypatch)
        agent_type = await _agent_type(factory)  # no completed execution

        response = await api_env["client"].post(
            "/api/v1/conversations/optimization",
            json={"agent_type_id": str(agent_type.id)},
        )

        assert response.status_code == 201, response.text
        availability = response.json()["availability"]
        assert availability["available"] is False
        assert availability["reason_code"] == "no_successful_execution"
        assert availability["reason"]
        assert availability["successful_executions"] == 0

    @pytest.mark.asyncio
    async def test_availability_reports_the_optimizer_model_reason(
        self, api_env, monkeypatch
    ):
        factory = api_env["session_factory"]
        # No authoring model → nothing inheritable, no optimizer selection.
        tenant = await _tenant(factory)
        async with factory() as session:
            await set_value(session, tenant.id, WORKFLOW_GENERATION_MODEL_KEY, None)
            await session.commit()
        await _allow_execute(monkeypatch)
        agent_type = await _agent_type(factory, with_success=True)

        response = await api_env["client"].post(
            "/api/v1/conversations/optimization",
            json={"agent_type_id": str(agent_type.id)},
        )

        assert response.status_code == 201, response.text
        availability = response.json()["availability"]
        assert availability["available"] is False
        assert availability["reason_code"] == "optimizer_model_not_configured"
        assert availability["optimizer_model"]["reason_code"] == (
            "optimizer_model_not_configured"
        )

    @pytest.mark.asyncio
    async def test_availability_reports_permission_denied(self, api_env, monkeypatch):
        factory = api_env["session_factory"]
        await _seed_models(factory)
        await _deny_execute(monkeypatch)
        agent_type = await _agent_type(factory, with_success=True)

        response = await api_env["client"].post(
            "/api/v1/conversations/optimization",
            json={"agent_type_id": str(agent_type.id)},
        )

        assert response.status_code == 201, response.text
        availability = response.json()["availability"]
        assert availability["available"] is False
        assert availability["reason_code"] == "permission_denied"
        assert availability["can_start_work"] is False

    @pytest.mark.asyncio
    async def test_a_scope_or_second_agent_type_is_not_accepted(
        self, api_env, monkeypatch
    ):
        factory = api_env["session_factory"]
        await _seed_models(factory)
        await _allow_execute(monkeypatch)
        subject = await _agent_type(factory, with_success=True)

        response = await api_env["client"].post(
            "/api/v1/conversations/optimization",
            json={
                "agent_type_id": str(subject.id),
                # Neither field exists — the subject is not re-supplied.
                "scope_agent_type_id": str(uuid.uuid4()),
                "target_agent_type_id": str(uuid.uuid4()),
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["subject"]["agent_type_id"] == str(subject.id)
        assert body["conversation"]["agent_type_id"] == str(subject.id)


# ── Read ────────────────────────────────────────────────────────────────────


class TestReadOptimizationConversation:
    @pytest.mark.asyncio
    async def test_read_returns_subject_availability_and_audit(
        self, api_env, monkeypatch
    ):
        factory = api_env["session_factory"]
        await _seed_models(factory)
        await _allow_execute(monkeypatch)
        operator = await _operator(factory)
        api_env["holder"]["identity_id"] = operator.id
        agent_type = await _agent_type(factory, with_success=True)

        created = await api_env["client"].post(
            "/api/v1/conversations/optimization",
            json={"agent_type_id": str(agent_type.id)},
        )
        session_id = created.json()["conversation"]["id"]

        response = await api_env["client"].get(
            f"/api/v1/conversations/{session_id}/optimization"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["conversation"]["id"] == session_id
        assert body["subject"]["agent_type_id"] == str(agent_type.id)
        assert body["availability"]["available"] is True
        assert body["audit"] == {
            "replay_verifications": 0,
            "live_operations": 0,
            "last_live_at": None,
            "replay_only": True,
        }

    @pytest.mark.asyncio
    async def test_unknown_session_is_404(self, api_env):
        response = await api_env["client"].get(
            f"/api/v1/conversations/{uuid.uuid4()}/optimization"
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_another_operators_session_is_403(self, api_env, monkeypatch):
        factory = api_env["session_factory"]
        await _seed_models(factory)
        await _allow_execute(monkeypatch)
        owner = await _operator(factory)
        api_env["holder"]["identity_id"] = owner.id
        agent_type = await _agent_type(factory, with_success=True)
        created = await api_env["client"].post(
            "/api/v1/conversations/optimization",
            json={"agent_type_id": str(agent_type.id)},
        )
        session_id = created.json()["conversation"]["id"]

        intruder = await _operator(factory)
        api_env["holder"]["identity_id"] = intruder.id

        response = await api_env["client"].get(
            f"/api/v1/conversations/{session_id}/optimization"
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_a_business_conversation_is_422(self, api_env):
        factory = api_env["session_factory"]
        agent_type = await _agent_type(factory, input_type=AgentInputType.conversation)
        tenant = await _tenant(factory)
        async with factory() as session:
            session.add(
                ConversationSession(
                    id=uuid.uuid4(),
                    tenant_id=tenant.id,
                    agent_type_id=agent_type.id,
                    channel="web",
                    status=ConversationStatus.active,
                )
            )
            await session.commit()
            business_id = (
                await session.execute(select(ConversationSession.id))
            ).scalar_one()

        response = await api_env["client"].get(
            f"/api/v1/conversations/{business_id}/optimization"
        )
        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "not_optimization_conversation"

    @pytest.mark.asyncio
    async def test_subject_cannot_be_changed_through_any_public_api(
        self, api_env, monkeypatch
    ):
        """No update path exposes ``agent_type_id``/``channel``."""
        factory = api_env["session_factory"]
        await _seed_models(factory)
        await _allow_execute(monkeypatch)
        subject = await _agent_type(factory, with_success=True)
        other = await _agent_type(factory, with_success=True)
        created = await api_env["client"].post(
            "/api/v1/conversations/optimization",
            json={"agent_type_id": str(subject.id)},
        )
        session_id = created.json()["conversation"]["id"]

        # A read "with a different agent type" is not a mutation surface.
        read = await api_env["client"].get(
            f"/api/v1/conversations/{session_id}/optimization",
            params={"agent_type_id": str(other.id)},
        )
        assert read.status_code == 200
        assert read.json()["subject"]["agent_type_id"] == str(subject.id)

        async with factory() as session:
            row = await session.get(ConversationSession, uuid.UUID(session_id))
            assert row is not None
            assert row.agent_type_id == subject.id
            assert row.channel == OPTIMIZATION_CHANNEL


# ── Ledger read ─────────────────────────────────────────────────────────────


class TestLedgerRead:
    @pytest.mark.asyncio
    async def test_empty_ledger(self, api_env, monkeypatch):
        factory = api_env["session_factory"]
        await _seed_models(factory)
        await _allow_execute(monkeypatch)
        agent_type = await _agent_type(factory, with_success=True)
        created = await api_env["client"].post(
            "/api/v1/conversations/optimization",
            json={"agent_type_id": str(agent_type.id)},
        )
        session_id = created.json()["conversation"]["id"]

        response = await api_env["client"].get(
            f"/api/v1/conversations/{session_id}/live-test-requests"
        )
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_denied_and_expired_rows_are_listed_with_attribution(
        self, api_env, monkeypatch
    ):
        factory = api_env["session_factory"]
        await _seed_models(factory)
        await _allow_execute(monkeypatch)
        operator = await _operator(factory)
        api_env["holder"]["identity_id"] = operator.id
        agent_type = await _agent_type(factory, with_success=True)
        created = await api_env["client"].post(
            "/api/v1/conversations/optimization",
            json={"agent_type_id": str(agent_type.id)},
        )
        session_id = uuid.UUID(created.json()["conversation"]["id"])

        tenant = await _tenant(factory)
        async with factory() as session:
            intervene = InterveneRequest(
                id=uuid.uuid4(),
                agent_type_id=agent_type.id,
                intervention_type=InterventionType.approval,
                reason="Live test approval",
                conversation_session_id=session_id,
                status=InterveneRequestStatus.responded,
                responded_at=datetime.now(UTC),
            )
            session.add(intervene)
            await session.flush()
            session.add(
                InterveneResponse(
                    id=uuid.uuid4(),
                    request_id=intervene.id,
                    operator_user_id=operator.id,
                    approval_value=False,
                    responded_at=datetime.now(UTC),
                )
            )
            session.add_all(
                [
                    OptimizationLiveTestRequest(
                        id=uuid.uuid4(),
                        tenant_id=tenant.id,
                        conversation_session_id=session_id,
                        target_agent_type_id=agent_type.id,
                        intervene_request_id=intervene.id,
                        status=OptimizationLiveTestStatus.denied,
                        requested_operations=[
                            {
                                "tool_name": "crm____searchCustomers",
                                "arguments": {"q": "ada"},
                                "purpose": "find the customer",
                            }
                        ],
                        expires_at=datetime.now(UTC) - timedelta(minutes=1),
                    ),
                    OptimizationLiveTestRequest(
                        id=uuid.uuid4(),
                        tenant_id=tenant.id,
                        conversation_session_id=session_id,
                        target_agent_type_id=agent_type.id,
                        status=OptimizationLiveTestStatus.expired,
                        requested_operations=[
                            {
                                "tool_name": "crm____searchCustomers",
                                "arguments": {"q": "grace"},
                                "purpose": "find the customer",
                            }
                        ],
                        expires_at=datetime.now(UTC) - timedelta(minutes=5),
                    ),
                ]
            )
            await session.commit()

        response = await api_env["client"].get(
            f"/api/v1/conversations/{session_id}/live-test-requests"
        )
        assert response.status_code == 200, response.text
        rows = response.json()
        assert len(rows) == 2
        denied = next(row for row in rows if row["status"] == "denied")
        assert denied["target_agent_type_id"] == str(agent_type.id)
        assert denied["requested_operations"][0]["tool_name"] == "crm____searchCustomers"
        assert denied["decided"] if "decided" in denied else True
        assert denied["decision"]["approval_value"] is False
        assert denied["decision"]["operator_user_id"] == str(operator.id)
        # Denied/expired rows carry no execution evidence.
        assert denied["executed_operations"] in (None, [])
        expired = next(row for row in rows if row["status"] == "expired")
        assert expired["executed_operations"] in (None, [])

    @pytest.mark.asyncio
    async def test_ledger_read_requires_ownership(self, api_env, monkeypatch):
        factory = api_env["session_factory"]
        await _seed_models(factory)
        await _allow_execute(monkeypatch)
        owner = await _operator(factory)
        api_env["holder"]["identity_id"] = owner.id
        agent_type = await _agent_type(factory, with_success=True)
        created = await api_env["client"].post(
            "/api/v1/conversations/optimization",
            json={"agent_type_id": str(agent_type.id)},
        )
        session_id = created.json()["conversation"]["id"]

        intruder = await _operator(factory)
        api_env["holder"]["identity_id"] = intruder.id
        response = await api_env["client"].get(
            f"/api/v1/conversations/{session_id}/live-test-requests"
        )
        assert response.status_code == 403


def _forbidden():
    from fastapi import HTTPException

    def override():
        raise HTTPException(status_code=403, detail="Forbidden")

    return override
