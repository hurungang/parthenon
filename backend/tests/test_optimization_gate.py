"""Composed plan/optimize gate + dedicated Optimize trigger.

Optimization is a separate, preconditioned action. The gate composes three
preconditions in a deterministic order:

1. the agent is not conversational (conversational agents have no plan),
2. the workspace AUTHORING model is configured AND still enabled in the
   tenant's model catalogue (no fallback model is ever selected),
3. at least one ``completed`` execution exists (the real reference run the
   optimizer learns from).

``can_generate_plan`` is the base-plan precondition (1+2); the execution
precondition only gates the optimization run.

Covers:

- gate computation (authoring-model states, conversational exclusion,
  ``AgentJob.status == completed`` count, reason precedence, no writes),
- ``GET /agents/types/{id}/optimization-gate`` response shape (extended
  payload), blocked/enabled transitions,
- ``POST /agents/sessions/optimize`` gate enforcement (412 +
  ``optimize_gate_unmet`` with a per-precondition ``reason_code``, no session
  created, no dispatch), ``__command`` + mission injection, 202, and
- normal ``POST /agents/sessions`` never injecting ``__command``.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
from app.db.models.tenant_setting import TenantSetting
from app.db.session import get_db
from app.main import create_app
from app.services.agents.command_prompts import OPTIMIZE_AND_VERIFY_SLUG
from app.services.agents.optimizer_model_settings import (
    OPTIMIZER_MODEL_KEY,
    REASON_OPTIMIZER_MODEL_NOT_CONFIGURED,
    REASON_OPTIMIZER_MODEL_NOT_ENABLED,
)
from app.services.agents.session_service import (
    REASON_CONVERSATIONAL_AGENT,
    REASON_NO_SUCCESSFUL_EXECUTION,
    AgentSessionService,
)
from app.services.agents.workflow_generation_settings import (
    REASON_AUTHORING_MODEL_NOT_CONFIGURED,
    REASON_AUTHORING_MODEL_NOT_ENABLED,
    WORKFLOW_GENERATION_MODEL_KEY,
)
from app.services.tenancy.root_tenant import get_root_tenant_id
from app.services.tenancy.tenant_settings_service import set_value


#: Model id enabled in the workspace catalogue (the usable authoring model).
AUTHORING_MODEL_ID = "gate-authoring-model"
#: Model id stored as the selection but absent from the catalogue (stale).
STALE_MODEL_ID = "gate-removed-model"
#: Model id enabled in the catalogue and selected as the OPTIMIZER model.
OPTIMIZER_MODEL_ID = "gate-optimizer-model"

#: Display-name prefix for the ModelConfig rows this module owns (teardown).
_CONFIG_DISPLAY_PREFIX = "gate-authoring-"


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _allow_agent_action():
    def override():
        return {"sub": "gate-test", "roles": ["admin"]}

    return override


@pytest.fixture
def _bypass_public_auth():
    from app.middleware.auth import JWTAuthMiddleware
    from app.middleware.tenant_resolution import TenantResolutionMiddleware

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "gate-test"}
        return await call_next(request)

    async def passthrough_resolution(self, request, call_next):
        request.state.tenancy_enabled = False
        return await call_next(request)

    with patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch), patch.object(
        TenantResolutionMiddleware, "dispatch", passthrough_resolution
    ):
        yield


@pytest_asyncio.fixture
async def public_client(
    test_engine, _bypass_public_auth
) -> AsyncGenerator[AsyncClient, None]:
    """Public agent-endpoint client (JWT + RBAC bypassed, real SQLite DB)."""
    app = create_app()
    for action in ("read", "create", "update", "delete", "execute"):
        app.dependency_overrides[require_permission(RT_AGENT, action)] = (
            _allow_agent_action()
        )

    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


def _session_factory(test_engine):
    return async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )


# ── Authoring-model setup (shared session-scoped SQLite engine) ──────────────


async def _root_tenant_id(test_engine) -> uuid.UUID:
    async with _session_factory(test_engine)() as session:
        tenant_id = await get_root_tenant_id(session)
    assert tenant_id is not None, "session test engine must provision the root tenant"
    return tenant_id


async def _clear_authoring_model(test_engine) -> None:
    """Remove this module's model rows (before/after each test).

    Covers BOTH the plan-authoring selection and the workspace optimizer
    selection: the optimizer model must never leak between gate tests (it is a
    separate setting, resolved explicit → authoring).
    """
    async with _session_factory(test_engine)() as session:
        await session.execute(
            delete(TenantSetting).where(
                TenantSetting.key.in_(
                    (WORKFLOW_GENERATION_MODEL_KEY, OPTIMIZER_MODEL_KEY)
                )
            )
        )
        await session.execute(
            delete(ModelConfig).where(
                ModelConfig.display_name.like(f"{_CONFIG_DISPLAY_PREFIX}%")
            )
        )
        await session.commit()


async def _configure_authoring_model(
    test_engine, model_id: str = AUTHORING_MODEL_ID
) -> uuid.UUID:
    """Enable ``model_id`` in the root tenant catalogue + select it."""
    root_id = await _root_tenant_id(test_engine)
    async with _session_factory(test_engine)() as session:
        config = ModelConfig(
            id=uuid.uuid4(),
            tenant_id=root_id,
            display_name=f"{_CONFIG_DISPLAY_PREFIX}{model_id}",
            provider_type=ModelProvider.openai,
            api_base_url="http://localhost:9999/v1",
            enabled_models=[model_id],
        )
        session.add(config)
        await session.flush()
        config_id = config.id
        await set_value(session, root_id, WORKFLOW_GENERATION_MODEL_KEY, model_id)
        await session.commit()
    return config_id


async def _select_authoring_model(test_engine, model_id: str) -> None:
    """Persist a selection WITHOUT a matching catalogue entry (stale id)."""
    root_id = await _root_tenant_id(test_engine)
    async with _session_factory(test_engine)() as session:
        await set_value(session, root_id, WORKFLOW_GENERATION_MODEL_KEY, model_id)
        await session.commit()


@pytest_asyncio.fixture(autouse=True)
async def _isolated_authoring_model(test_engine):
    """Each test starts and ends with NO workspace authoring model."""
    await _clear_authoring_model(test_engine)
    yield
    await _clear_authoring_model(test_engine)


async def _create_agent_type(
    test_engine, *, input_type: AgentInputType = AgentInputType.none
) -> uuid.UUID:
    agent_type_id = uuid.uuid4()
    async with _session_factory(test_engine)() as session:
        session.add(
            AgentType(
                id=agent_type_id,
                name=f"gate-{agent_type_id.hex[:8]}",
                input_type=input_type,
                output_type=(
                    AgentOutputType.auto
                    if input_type == AgentInputType.conversation
                    else AgentOutputType.markdown
                ),
            )
        )
        await session.commit()
    return agent_type_id


async def _add_job(
    test_engine,
    agent_type_id: uuid.UUID,
    status: AgentJobStatus,
    *,
    output_data=None,
) -> uuid.UUID:
    job_id = uuid.uuid4()
    now = datetime.now(UTC)
    async with _session_factory(test_engine)() as session:
        session.add(
            AgentJob(
                id=job_id,
                agent_type_id=agent_type_id,
                status=status,
                input_data={"message": "run"},
                output_data=output_data,
                started_at=now if status != AgentJobStatus.queued else None,
                completed_at=now
                if status
                in {
                    AgentJobStatus.completed,
                    AgentJobStatus.failed,
                    AgentJobStatus.terminated,
                }
                else None,
            )
        )
        await session.commit()
    return job_id


async def _count_jobs(test_engine, agent_type_id: uuid.UUID) -> int:
    async with _session_factory(test_engine)() as session:
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(AgentJob)
                    .where(AgentJob.agent_type_id == agent_type_id)
                )
            ).scalar_one()
        )


# ── Gate computation (service level) ─────────────────────────────────────────


class TestOptimizationGateComputation:
    async def test_authoring_model_unset_blocks_generate_and_optimize(
        self, test_engine
    ):
        """No authoring model → structured "not configured" (no fallback)."""
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        async with _session_factory(test_engine)() as session:
            gate = await AgentSessionService().get_optimization_gate(
                session, agent_type_id
            )
        assert gate.can_generate_plan is False
        assert gate.can_optimize is False
        assert gate.workflow_model_configured is False
        assert gate.workflow_model_id is None
        assert gate.is_conversational is False
        assert gate.reason_code == REASON_AUTHORING_MODEL_NOT_CONFIGURED
        assert gate.reason
        assert "System Config" in gate.reason

    async def test_stale_authoring_model_reports_not_enabled_and_echoes_id(
        self, test_engine
    ):
        """A selection no longer in the catalogue is "not enabled" — the id is
        echoed so the UI can ask for a re-select, and nothing falls back."""
        await _select_authoring_model(test_engine, STALE_MODEL_ID)
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        async with _session_factory(test_engine)() as session:
            gate = await AgentSessionService().get_optimization_gate(
                session, agent_type_id
            )
        assert gate.can_generate_plan is False
        assert gate.can_optimize is False
        assert gate.workflow_model_configured is False
        assert gate.workflow_model_id == STALE_MODEL_ID
        assert gate.reason_code == REASON_AUTHORING_MODEL_NOT_ENABLED
        assert STALE_MODEL_ID in (gate.reason or "")

    async def test_no_prior_executions_blocks_with_reason(self, test_engine):
        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(test_engine)
        async with _session_factory(test_engine)() as session:
            gate = await AgentSessionService().get_optimization_gate(
                session, agent_type_id
            )
        assert gate.can_optimize is False
        # Base-plan generation does NOT require an execution.
        assert gate.can_generate_plan is True
        assert gate.workflow_model_configured is True
        assert gate.workflow_model_id == AUTHORING_MODEL_ID
        assert gate.successful_executions == 0
        assert gate.reason_code == REASON_NO_SUCCESSFUL_EXECUTION
        assert gate.reason
        assert "successful execution" in gate.reason.lower()

    async def test_conversational_agent_blocks_generate_and_optimize(
        self, test_engine
    ):
        """Conversational agents never get plan generation or optimization."""
        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(
            test_engine, input_type=AgentInputType.conversation
        )
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        async with _session_factory(test_engine)() as session:
            gate = await AgentSessionService().get_optimization_gate(
                session, agent_type_id
            )
        assert gate.is_conversational is True
        assert gate.can_generate_plan is False
        assert gate.can_optimize is False
        # The model itself IS configured — only the agent shape blocks it.
        assert gate.workflow_model_configured is True
        assert gate.reason_code == REASON_CONVERSATIONAL_AGENT

    async def test_precedence_conversational_outranks_authoring_model(
        self, test_engine
    ):
        """Precedence is conversational → authoring model → executions."""
        agent_type_id = await _create_agent_type(
            test_engine, input_type=AgentInputType.conversation
        )
        # No authoring model AND no executions: conversational still wins.
        async with _session_factory(test_engine)() as session:
            gate = await AgentSessionService().get_optimization_gate(
                session, agent_type_id
            )
        assert gate.reason_code == REASON_CONVERSATIONAL_AGENT
        assert gate.is_conversational is True
        assert gate.workflow_model_configured is False

    async def test_precedence_authoring_model_outranks_executions(
        self, test_engine
    ):
        """A configured+completed agent with no model reports the model first."""
        await _select_authoring_model(test_engine, STALE_MODEL_ID)
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        async with _session_factory(test_engine)() as session:
            gate = await AgentSessionService().get_optimization_gate(
                session, agent_type_id
            )
        assert gate.successful_executions == 1
        assert gate.reason_code == REASON_AUTHORING_MODEL_NOT_ENABLED

    async def test_only_completed_jobs_count(self, test_engine):
        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(test_engine)
        for status in (
            AgentJobStatus.queued,
            AgentJobStatus.running,
            AgentJobStatus.failed,
            AgentJobStatus.terminated,
        ):
            await _add_job(test_engine, agent_type_id, status)

        async with _session_factory(test_engine)() as session:
            gate = await AgentSessionService().get_optimization_gate(
                session, agent_type_id
            )
        assert gate.successful_executions == 0
        assert gate.can_optimize is False
        assert gate.reason_code == REASON_NO_SUCCESSFUL_EXECUTION

    async def test_one_completed_job_enables_optimize(self, test_engine):
        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        async with _session_factory(test_engine)() as session:
            gate = await AgentSessionService().get_optimization_gate(
                session, agent_type_id
            )
        assert gate.can_optimize is True
        assert gate.can_generate_plan is True
        assert gate.successful_executions == 1
        assert gate.reason is None
        assert gate.reason_code is None

    async def test_completed_but_empty_result_still_counts(self, test_engine):
        """The gate keys off ``status == completed`` — a legitimately empty
        business result (e.g. a lookup that found nothing) is still a real
        reference run for the optimizer."""
        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(
            test_engine, agent_type_id, AgentJobStatus.completed, output_data={}
        )
        await _add_job(
            test_engine, agent_type_id, AgentJobStatus.completed, output_data=None
        )

        async with _session_factory(test_engine)() as session:
            gate = await AgentSessionService().get_optimization_gate(
                session, agent_type_id
            )
        assert gate.can_optimize is True
        assert gate.successful_executions == 2

    async def test_counts_are_scoped_to_the_agent_type(self, test_engine):
        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(test_engine)
        other_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, other_type_id, AgentJobStatus.completed)

        async with _session_factory(test_engine)() as session:
            gate = await AgentSessionService().get_optimization_gate(
                session, agent_type_id
            )
        assert gate.can_optimize is False
        assert gate.successful_executions == 0

    async def test_count_helper_matches_gate(self, test_engine):
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.failed)

        async with _session_factory(test_engine)() as session:
            count = await AgentSessionService().count_successful_executions(
                session, agent_type_id
            )
        assert count == 2

    async def test_gate_is_read_only(self, test_engine):
        """No stored counter: reading the gate must not create/modify jobs."""
        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        async with _session_factory(test_engine)() as session:
            before = (
                await session.execute(
                    select(func.count())
                    .select_from(AgentJob)
                    .where(AgentJob.agent_type_id == agent_type_id)
                )
            ).scalar_one()
            service = AgentSessionService()
            await service.get_optimization_gate(session, agent_type_id)
            await service.count_successful_executions(session, agent_type_id)
            after = (
                await session.execute(
                    select(func.count())
                    .select_from(AgentJob)
                    .where(AgentJob.agent_type_id == agent_type_id)
                )
            ).scalar_one()
        assert before == after == 1

    async def test_gate_uses_a_preloaded_agent_type(self, test_engine):
        """The optional ``agent_type`` avoids a second read and yields the
        same conversational flag (callers already hold the row)."""
        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(
            test_engine, input_type=AgentInputType.conversation
        )
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        async with _session_factory(test_engine)() as session:
            agent_type = await session.get(AgentType, agent_type_id)
            gate = await AgentSessionService().get_optimization_gate(
                session, agent_type_id, agent_type=agent_type
            )
        assert gate.is_conversational is True
        assert gate.reason_code == REASON_CONVERSATIONAL_AGENT


# ── Gate endpoint ─────────────────────────────────────────────────────────────


_GATE_FIELDS = {
    "can_optimize",
    "successful_executions",
    "reason",
    "can_generate_plan",
    "workflow_model_configured",
    "workflow_model_id",
    "is_conversational",
    "reason_code",
    # Optimization-CONVERSATION entry (a mode of the agent itself) — additive
    # and independent of the one-shot ``can_optimize`` precondition.
    "optimization_conversation_available",
    "optimization_conversation_reason_code",
    # Derived optimizer-model state (explicit selection else the authoring model).
    "optimizer_model_configured",
    "optimizer_model_id",
    "optimizer_model_source",
    "optimizer_model_reason_code",
}


class TestOptimizationGateEndpoint:
    async def test_unknown_agent_type_404(self, public_client):
        resp = await public_client.get(
            f"/api/v1/agents/types/{uuid.uuid4()}/optimization-gate"
        )
        assert resp.status_code == 404

    async def test_blocked_before_first_successful_execution(
        self, public_client, test_engine
    ):
        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(test_engine)
        resp = await public_client.get(
            f"/api/v1/agents/types/{agent_type_id}/optimization-gate"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body) == _GATE_FIELDS
        assert body["can_optimize"] is False
        assert body["successful_executions"] == 0
        assert body["reason"]
        assert body["reason_code"] == REASON_NO_SUCCESSFUL_EXECUTION
        # Base-plan generation is already available.
        assert body["can_generate_plan"] is True
        assert body["workflow_model_configured"] is True
        assert body["workflow_model_id"] == AUTHORING_MODEL_ID
        assert body["is_conversational"] is False

    async def test_blocked_when_authoring_model_unset(
        self, public_client, test_engine
    ):
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        resp = await public_client.get(
            f"/api/v1/agents/types/{agent_type_id}/optimization-gate"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["can_optimize"] is False
        assert body["can_generate_plan"] is False
        assert body["workflow_model_configured"] is False
        assert body["workflow_model_id"] is None
        assert body["reason_code"] == REASON_AUTHORING_MODEL_NOT_CONFIGURED
        assert body["reason"]

    async def test_blocked_when_authoring_model_no_longer_enabled(
        self, public_client, test_engine
    ):
        await _select_authoring_model(test_engine, STALE_MODEL_ID)
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        resp = await public_client.get(
            f"/api/v1/agents/types/{agent_type_id}/optimization-gate"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["can_optimize"] is False
        assert body["can_generate_plan"] is False
        assert body["workflow_model_configured"] is False
        # The stale id is echoed so the UI can say "re-select".
        assert body["workflow_model_id"] == STALE_MODEL_ID
        assert body["reason_code"] == REASON_AUTHORING_MODEL_NOT_ENABLED

    async def test_conversational_agent_reports_exclusion(
        self, public_client, test_engine
    ):
        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(
            test_engine, input_type=AgentInputType.conversation
        )
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        resp = await public_client.get(
            f"/api/v1/agents/types/{agent_type_id}/optimization-gate"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["is_conversational"] is True
        assert body["can_generate_plan"] is False
        assert body["can_optimize"] is False
        assert body["reason_code"] == REASON_CONVERSATIONAL_AGENT

    async def test_enabled_after_a_completed_execution(
        self, public_client, test_engine
    ):
        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        resp = await public_client.get(
            f"/api/v1/agents/types/{agent_type_id}/optimization-gate"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["can_optimize"] is True
        assert body["can_generate_plan"] is True
        assert body["successful_executions"] == 1
        assert body["reason"] is None
        assert body["reason_code"] is None

    async def test_gate_enables_without_reload_after_execution(
        self, public_client, test_engine
    ):
        """Blocked-by-execution flips to enabled once a run completes (no
        stored state, so the next read reflects the new DB state)."""
        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(test_engine)

        first = await public_client.get(
            f"/api/v1/agents/types/{agent_type_id}/optimization-gate"
        )
        assert first.json()["reason_code"] == REASON_NO_SUCCESSFUL_EXECUTION

        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        second = await public_client.get(
            f"/api/v1/agents/types/{agent_type_id}/optimization-gate"
        )
        body = second.json()
        assert body["can_optimize"] is True
        assert body["reason_code"] is None


# ── Extended payload: conversation availability + optimizer model ───────────


async def _configure_optimizer_model(
    test_engine, model_id: str = OPTIMIZER_MODEL_ID
) -> uuid.UUID:
    """Enable ``model_id`` in the root tenant catalogue + select it."""
    root_id = await _root_tenant_id(test_engine)
    async with _session_factory(test_engine)() as session:
        config = ModelConfig(
            id=uuid.uuid4(),
            tenant_id=root_id,
            display_name=f"{_CONFIG_DISPLAY_PREFIX}{model_id}",
            provider_type=ModelProvider.openai,
            api_base_url="http://localhost:9999/v1",
            enabled_models=[model_id],
        )
        session.add(config)
        await session.flush()
        config_id = config.id
        await set_value(session, root_id, OPTIMIZER_MODEL_KEY, model_id)
        await session.commit()
    return config_id


async def _select_optimizer_without_catalogue(
    test_engine, model_id: str
) -> None:
    root_id = await _root_tenant_id(test_engine)
    async with _session_factory(test_engine)() as session:
        await set_value(session, root_id, OPTIMIZER_MODEL_KEY, model_id)
        await session.commit()


class TestGateConversationAvailability:
    async def test_typed_subject_reports_the_conversation_as_available(
        self, test_engine
    ):
        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        async with _session_factory(test_engine)() as session:
            gate = await AgentSessionService().get_optimization_gate(
                session, agent_type_id
            )

        assert gate.can_optimize is True
        assert gate.optimization_conversation_available is True
        assert gate.optimization_conversation_reason_code is None
        assert gate.optimizer_model_configured is True
        assert gate.optimizer_model_id == AUTHORING_MODEL_ID
        assert gate.optimizer_model_source == "authoring"
        assert gate.optimizer_model_reason_code is None

    async def test_conversational_subject_can_open_the_conversation(
        self, test_engine
    ):
        """Conversational agents are still excluded from the ONE-SHOT Optimize
        action (``can_optimize`` unchanged) but the optimization CONVERSATION
        is available for them — the mode runs the conversational loop."""
        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(
            test_engine, input_type=AgentInputType.conversation
        )
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        async with _session_factory(test_engine)() as session:
            gate = await AgentSessionService().get_optimization_gate(
                session, agent_type_id
            )

        # One-shot semantics unchanged.
        assert gate.is_conversational is True
        assert gate.can_optimize is False
        assert gate.can_generate_plan is False
        assert gate.reason_code == REASON_CONVERSATIONAL_AGENT
        # The conversation entry is independent and available.
        assert gate.optimization_conversation_available is True
        assert gate.optimization_conversation_reason_code is None

    async def test_a_missing_plan_is_information_not_a_block(self, test_engine):
        """A conversational subject with no plan still reports availability —
        the entry must exist wherever optimization would be possible."""
        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(
            test_engine, input_type=AgentInputType.conversation
        )
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        async with _session_factory(test_engine)() as session:
            gate = await AgentSessionService().get_optimization_gate(
                session, agent_type_id
            )

        assert gate.optimization_conversation_available is True

    async def test_conversation_availability_requires_a_reference_execution(
        self, test_engine
    ):
        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(test_engine)

        async with _session_factory(test_engine)() as session:
            gate = await AgentSessionService().get_optimization_gate(
                session, agent_type_id
            )

        assert gate.optimization_conversation_available is False
        assert gate.optimization_conversation_reason_code == (
            REASON_NO_SUCCESSFUL_EXECUTION
        )

    async def test_conversation_availability_reports_the_model_reason(
        self, test_engine
    ):
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        async with _session_factory(test_engine)() as session:
            gate = await AgentSessionService().get_optimization_gate(
                session, agent_type_id
            )

        assert gate.optimization_conversation_available is False
        assert gate.optimization_conversation_reason_code == (
            REASON_OPTIMIZER_MODEL_NOT_CONFIGURED
        )
        assert gate.optimizer_model_reason_code == (
            REASON_OPTIMIZER_MODEL_NOT_CONFIGURED
        )


class TestGateOptimizerModelFields:
    async def test_explicit_optimizer_model_is_reported(self, test_engine):
        # Authoring model remains the one-shot precondition; the optimizer
        # selection is reported separately.
        await _configure_authoring_model(test_engine)
        await _configure_optimizer_model(test_engine)
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        async with _session_factory(test_engine)() as session:
            gate = await AgentSessionService().get_optimization_gate(
                session, agent_type_id
            )

        assert gate.can_optimize is True  # unchanged by the optimizer setting
        assert gate.workflow_model_id == AUTHORING_MODEL_ID
        assert gate.optimizer_model_id == OPTIMIZER_MODEL_ID
        assert gate.optimizer_model_source == "optimizer"
        assert gate.optimizer_model_configured is True
        assert gate.optimizer_model_reason_code is None
        assert gate.optimization_conversation_available is True

    async def test_stale_optimizer_model_blocks_the_conversation_only(
        self, test_engine
    ):
        """A stale optimizer selection blocks the conversation but leaves the
        one-shot ``can_optimize`` precondition (authoring model) intact."""
        await _configure_authoring_model(test_engine)
        await _select_optimizer_without_catalogue(test_engine, STALE_MODEL_ID)
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        async with _session_factory(test_engine)() as session:
            gate = await AgentSessionService().get_optimization_gate(
                session, agent_type_id
            )

        assert gate.can_optimize is True
        assert gate.optimizer_model_id is None  # no effective model
        assert gate.optimizer_model_source == "optimizer"
        assert gate.optimizer_model_configured is False
        assert gate.optimizer_model_reason_code == REASON_OPTIMIZER_MODEL_NOT_ENABLED
        assert gate.optimization_conversation_available is False
        assert gate.optimization_conversation_reason_code == (
            REASON_OPTIMIZER_MODEL_NOT_ENABLED
        )

    async def test_optimizer_model_does_not_affect_can_optimize(
        self, test_engine
    ):
        """``can_optimize`` is not affected by the optimizer-model setting."""
        await _configure_optimizer_model(test_engine)
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        async with _session_factory(test_engine)() as session:
            gate = await AgentSessionService().get_optimization_gate(
                session, agent_type_id
            )

        # Authoring model is still unset → the one-shot action stays blocked.
        assert gate.can_optimize is False
        assert gate.reason_code == REASON_AUTHORING_MODEL_NOT_CONFIGURED
        # …while the conversation has an optimizer model but no authoring
        # fallback is needed: the explicit selection resolves.
        assert gate.optimizer_model_id == OPTIMIZER_MODEL_ID
        assert gate.optimization_conversation_available is True

    async def test_endpoint_reports_the_optimizer_fields(self, public_client, test_engine):
        await _configure_authoring_model(test_engine)
        await _configure_optimizer_model(test_engine)
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        response = await public_client.get(
            f"/api/v1/agents/types/{agent_type_id}/optimization-gate"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body) == _GATE_FIELDS
        assert body["optimization_conversation_available"] is True
        assert body["optimization_conversation_reason_code"] is None
        assert body["optimizer_model_configured"] is True
        assert body["optimizer_model_id"] == OPTIMIZER_MODEL_ID
        assert body["optimizer_model_source"] == "optimizer"
        assert body["optimizer_model_reason_code"] is None
        assert body["can_optimize"] is True

    async def test_conversational_entry_is_available_on_the_endpoint(
        self, public_client, test_engine
    ):
        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(
            test_engine, input_type=AgentInputType.conversation
        )
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        response = await public_client.get(
            f"/api/v1/agents/types/{agent_type_id}/optimization-gate"
        )
        body = response.json()
        assert body["is_conversational"] is True
        assert body["can_optimize"] is False  # one-shot action unchanged
        assert body["optimization_conversation_available"] is True


# ── Optimize trigger ──────────────────────────────────────────────────────────


def _fake_launch(captured: dict):
    async def fake_launch(**kwargs):
        captured.update(kwargs)
        return {
            "session_id": str(uuid.uuid4()),
            "triggered": True,
            "trigger_error": None,
        }

    return fake_launch


def _fake_get_session(agent_type_id: uuid.UUID):
    async def fake_get_session(session_id, db):
        return {
            "id": str(session_id),
            "agent_type_id": str(agent_type_id),
            "status": "queued",
            "started_at": None,
            "completed_at": None,
            "error_message": "",
            "created_at": datetime.now(UTC).isoformat(),
        }

    return fake_get_session


class TestOptimizeTrigger:
    async def test_unknown_agent_type_404(self, public_client):
        resp = await public_client.post(
            "/api/v1/agents/sessions/optimize",
            json={"agent_type_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 404

    @pytest.mark.parametrize(
        ("setup_authoring_model", "input_type", "add_completed_job", "reason_code"),
        [
            # Precedence: conversational → authoring model → executions.
            (False, AgentInputType.conversation, True, REASON_CONVERSATIONAL_AGENT),
            (True, AgentInputType.conversation, True, REASON_CONVERSATIONAL_AGENT),
            (False, AgentInputType.none, True, REASON_AUTHORING_MODEL_NOT_CONFIGURED),
            (False, AgentInputType.none, False, REASON_AUTHORING_MODEL_NOT_CONFIGURED),
            (True, AgentInputType.none, False, REASON_NO_SUCCESSFUL_EXECUTION),
        ],
    )
    async def test_gate_unmet_rejects_with_412_per_reason_code(
        self,
        public_client,
        test_engine,
        monkeypatch,
        setup_authoring_model,
        input_type,
        add_completed_job,
        reason_code,
    ):
        """The UI state is not trusted: the trigger re-checks the gate and
        rejects with the FIRST unmet precondition's own ``reason_code``."""
        from app.api.v1 import agents as agents_module

        if setup_authoring_model:
            await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(test_engine, input_type=input_type)
        if add_completed_job:
            await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)
        jobs_before = await _count_jobs(test_engine, agent_type_id)

        captured: dict = {}
        monkeypatch.setattr(
            agents_module._lifecycle_handler, "launch", _fake_launch(captured)
        )

        resp = await public_client.post(
            "/api/v1/agents/sessions/optimize",
            json={"agent_type_id": str(agent_type_id)},
        )
        assert resp.status_code == 412, resp.text
        detail = resp.json()["detail"]
        assert detail["error"] == "optimize_gate_unmet"
        assert detail["reason_code"] == reason_code
        assert detail["reason"]
        # Nothing was dispatched and no session was created.
        assert captured == {}
        assert await _count_jobs(test_engine, agent_type_id) == jobs_before

    async def test_stale_authoring_model_rejects_with_its_own_reason(
        self, public_client, test_engine, monkeypatch
    ):
        from app.api.v1 import agents as agents_module

        await _select_authoring_model(test_engine, STALE_MODEL_ID)
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        captured: dict = {}
        monkeypatch.setattr(
            agents_module._lifecycle_handler, "launch", _fake_launch(captured)
        )

        resp = await public_client.post(
            "/api/v1/agents/sessions/optimize",
            json={"agent_type_id": str(agent_type_id)},
        )
        assert resp.status_code == 412, resp.text
        detail = resp.json()["detail"]
        assert detail["error"] == "optimize_gate_unmet"
        assert detail["reason_code"] == REASON_AUTHORING_MODEL_NOT_ENABLED
        assert captured == {}

    async def test_trigger_injects_command_markers_and_mission(
        self, public_client, test_engine, monkeypatch
    ):
        from app.api.v1 import agents as agents_module

        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        captured: dict = {}
        monkeypatch.setattr(
            agents_module._lifecycle_handler, "launch", _fake_launch(captured)
        )
        monkeypatch.setattr(
            agents_module._session_service,
            "get_session",
            _fake_get_session(agent_type_id),
        )

        resp = await public_client.post(
            "/api/v1/agents/sessions/optimize",
            json={"agent_type_id": str(agent_type_id)},
        )
        assert resp.status_code == 202, resp.text

        input_data = captured["input_data"]
        assert input_data["__command"] == OPTIMIZE_AND_VERIFY_SLUG
        assert input_data["__command_agent_type_id"] == str(agent_type_id)
        mission = input_data["message"]
        # The mission is interpolated with the target agent type and clearly
        # states there is no user task for this run.
        assert str(agent_type_id) in mission
        assert "{agent_type_id}" not in mission
        assert "Optimization-only run" in mission
        assert "There is no user task for this run" in mission
        assert "needs_feedback" in mission
        # A normal task input is neither required nor reused.
        assert captured["agent_type_id"] == agent_type_id

    async def test_trigger_dispatches_through_the_lifecycle_handler(
        self, public_client, test_engine, monkeypatch
    ):
        from app.api.v1 import agents as agents_module

        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        captured: dict = {}
        monkeypatch.setattr(
            agents_module._lifecycle_handler, "launch", _fake_launch(captured)
        )
        monkeypatch.setattr(
            agents_module._session_service,
            "get_session",
            _fake_get_session(agent_type_id),
        )

        resp = await public_client.post(
            "/api/v1/agents/sessions/optimize",
            json={"agent_type_id": str(agent_type_id)},
        )
        assert resp.status_code == 202
        assert set(captured) >= {"agent_type_id", "input_data", "user_id", "db"}

    async def test_trigger_does_not_mutate_normal_run_input(
        self, public_client, test_engine, monkeypatch
    ):
        """The optimize trigger is a distinct execution — it must not require
        or echo a caller-supplied task input."""
        from app.api.v1 import agents as agents_module

        await _configure_authoring_model(test_engine)
        agent_type_id = await _create_agent_type(test_engine)
        await _add_job(test_engine, agent_type_id, AgentJobStatus.completed)

        captured: dict = {}
        monkeypatch.setattr(
            agents_module._lifecycle_handler, "launch", _fake_launch(captured)
        )
        monkeypatch.setattr(
            agents_module._session_service,
            "get_session",
            _fake_get_session(agent_type_id),
        )

        resp = await public_client.post(
            "/api/v1/agents/sessions/optimize",
            json={"agent_type_id": str(agent_type_id), "input_data": {"message": "x"}},
        )
        assert resp.status_code == 202, resp.text
        # The caller-supplied task input is ignored — the prompt is the
        # optimization mission.
        assert not captured["input_data"]["message"].startswith("x")
        assert captured["input_data"]["message"].startswith(
            "You are optimizing an AI agent's workflow"
        )


# ── Normal run: no optimization side effect ──────────────────────────────────


class TestNormalRunNeverOptimizes:
    async def test_normal_run_does_not_inject_command(
        self, public_client, test_engine, monkeypatch
    ):
        from app.api.v1 import agents as agents_module

        agent_type_id = await _create_agent_type(test_engine)
        captured: dict = {}
        monkeypatch.setattr(
            agents_module._lifecycle_handler, "launch", _fake_launch(captured)
        )
        monkeypatch.setattr(
            agents_module._session_service,
            "get_session",
            _fake_get_session(agent_type_id),
        )

        resp = await public_client.post(
            "/api/v1/agents/sessions",
            json={
                "agent_type_id": str(agent_type_id),
                "input_data": {"message": "compile the quarterly report"},
            },
        )
        assert resp.status_code in (200, 202), resp.text
        assert "__command" not in (captured["input_data"] or {})
        assert "__command_agent_type_id" not in (captured["input_data"] or {})
        assert captured["input_data"]["message"] == "compile the quarterly report"

    async def test_legacy_optimize_field_is_not_a_run_mode(
        self, public_client, test_engine, monkeypatch
    ):
        """``optimize: true`` no longer exists on the launch body — it is
        ignored, so a normal run never performs optimization."""
        from app.api.v1 import agents as agents_module

        agent_type_id = await _create_agent_type(test_engine)
        captured: dict = {}
        monkeypatch.setattr(
            agents_module._lifecycle_handler, "launch", _fake_launch(captured)
        )
        monkeypatch.setattr(
            agents_module._session_service,
            "get_session",
            _fake_get_session(agent_type_id),
        )

        resp = await public_client.post(
            "/api/v1/agents/sessions",
            json={
                "agent_type_id": str(agent_type_id),
                "input_data": {"message": "just run"},
                "optimize": True,
            },
        )
        assert resp.status_code in (200, 202), resp.text
        assert "__command" not in (captured["input_data"] or {})
