"""Internal ``request_live_test`` system tool — the script-level proposal.

``POST /api/v1/internal/system-tools/request-live-test`` is how the optimizer
asks for ONE operator-approved run of a **saved script**. The caller supplies
``{script_version_id, reason}`` — **never** an operation list: the tool-call
preview shown on the approval card is derived server-side from the approved
version's own ``python_source``.

Pinned here (over the real CC handler + DB):

* an accepted proposal writes, in one transaction, the ``pending`` ledger row
  (server-derived subject, ``script_version_id``, derived preview) **and** the
  linked ``approval`` intervention whose card is titled "Run this script live";
* the tool result returns the ledger id / intervention id / expiry / the script
  version / the derived preview (not a caller-supplied list);
* a replay of the same script version returns the stored outcome — no second
  row, no second approval;
* a second, different proposal while one is pending is refused
  (``live_test_already_pending``) and writes nothing;
* a script with no literal ``tools.call`` is refused (``no_tool_calls``) with
  nothing written.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.tenant_context import (
    TenantContext,
    reset_current_tenant_context,
    set_current_tenant_context,
)
from app.db.models.agents import AgentInputType, AgentOutputType, AgentType
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.db.models.intervene import (
    InterveneRequest,
    InterveneRequestStatus,
    InterventionType,
)
from app.db.models.optimization_live_test import (
    OptimizationLiveTestRequest,
    OptimizationLiveTestStatus,
)
from app.db.models.script_registry import (
    SandboxValidationStatus,
    ScriptDefinition,
    ScriptVersion,
)
from app.db.models.tenant import Tenant, TenantStatus
from app.db.session import Base
from app.services.agents.optimization_mode import OPTIMIZATION_CHANNEL
from app.services.tenancy.root_tenant import invalidate_root_tenant_cache

PERMITTED_TOOL = "crm____searchCustomers"
SECOND_TOOL = "crm____createOrder"
SCRIPT_SOURCE = (
    "def run(context, tools):\n"
    f"    customer = tools.call('{PERMITTED_TOOL}', {{'q': 'ada'}})\n"
    f"    return tools.call('{SECOND_TOOL}', {{'q': 'ada'}})\n"
)


@pytest_asyncio.fixture
async def isolated_db() -> AsyncSession:
    invalidate_root_tenant_cache()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )()
    session.add(
        Tenant(
            id=uuid.uuid4(),
            slug="live-tool-workspace",
            name="Live Tool Workspace",
            status=TenantStatus.active,
            is_system_tenant=True,
        )
    )
    await session.commit()
    yield session
    await session.rollback()
    await session.close()
    await engine.dispose()
    invalidate_root_tenant_cache()


@contextmanager
def _as_tenant(tenant: Tenant):
    token = set_current_tenant_context(
        TenantContext(
            tenant_id=tenant.id,
            slug=tenant.slug,
            name=tenant.name,
            is_system_tenant=bool(tenant.is_system_tenant),
        )
    )
    try:
        yield
    finally:
        reset_current_tenant_context(token)


async def _tenant(db: AsyncSession) -> Tenant:
    return (
        await db.execute(select(Tenant).where(Tenant.slug == "live-tool-workspace"))
    ).scalar_one()


async def _subject(db: AsyncSession, tenant_id: uuid.UUID) -> AgentType:
    agent_type = AgentType(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=f"live-tool-agent-{uuid.uuid4().hex[:8]}",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.markdown,
        is_active=True,
    )
    db.add(agent_type)
    await db.flush()
    return agent_type


async def _session(
    db: AsyncSession, tenant_id: uuid.UUID, agent_type: AgentType
) -> ConversationSession:
    session = ConversationSession(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        agent_type_id=agent_type.id,
        channel=OPTIMIZATION_CHANNEL,
        status=ConversationStatus.active,
    )
    db.add(session)
    await db.flush()
    return session


async def _script(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_type: AgentType,
    *,
    source: str | None = SCRIPT_SOURCE,
) -> tuple[ScriptDefinition, ScriptVersion]:
    definition = ScriptDefinition(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        agent_type_id=agent_type.id,
        name=f"live-tool-script-{uuid.uuid4().hex[:8]}",
    )
    db.add(definition)
    await db.flush()
    version = ScriptVersion(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        script_definition_id=definition.id,
        version_label=f"v{uuid.uuid4().hex[:4]}",
        python_source=source,
        sandbox_validation_status=SandboxValidationStatus.passed,
    )
    db.add(version)
    await db.flush()
    return definition, version


def _body(**overrides):
    from app.api.v1.internal.optimization_tools import SystemToolRequest

    payload: dict = {"session_id": "conv-session-1", "tool_args": {}}
    payload.update(overrides)
    return SystemToolRequest(**payload)


def _tenant_ctx(tenant: Tenant) -> TenantContext:
    return TenantContext(
        tenant_id=tenant.id,
        slug=tenant.slug,
        name=tenant.name,
        is_system_tenant=bool(tenant.is_system_tenant),
    )


@pytest.fixture(autouse=True)
def _no_live_socket():
    """The approval-card announcement is best effort; never hit the network."""
    with patch(
        "app.services.control_center.comm_hub_client.CommunicationHubClient."
        "dispatch_message",
        AsyncMock(),
    ):
        yield


async def _count(db: AsyncSession, model) -> int:  # noqa: ANN001
    return int(
        (await db.execute(select(func.count()).select_from(model))).scalar_one()
    )


class TestRequestLiveTestTool:
    @pytest.mark.asyncio
    async def test_an_accepted_proposal_records_the_ledger_and_its_approval(
        self, isolated_db: AsyncSession
    ):
        from app.api.v1.internal.system_tools import request_live_test_tool

        tenant = await _tenant(isolated_db)
        subject = await _subject(isolated_db, tenant.id)
        session = await _session(isolated_db, tenant.id, subject)
        definition, version = await _script(isolated_db, tenant.id, subject)
        await isolated_db.commit()

        with _as_tenant(tenant):
            response = await request_live_test_tool(
                _body(
                    agent_type_id=str(subject.id),
                    conversation_session_id=str(session.id),
                    tool_args={
                        "script_version_id": str(version.id),
                        "reason": "Replay could not prove the totals step.",
                    },
                ),
                _tenant_ctx(tenant),
                isolated_db,
            )

        result = response.result
        assert result["status"] == "pending"
        assert result["live_test_request_id"]
        assert result["intervene_request_id"]
        assert result["expires_at"]
        assert result["script_version_id"] == str(version.id)
        # The preview is derived from the script source, in source order.
        assert [op["tool_name"] for op in result["operations"]] == [
            PERMITTED_TOOL,
            SECOND_TOOL,
        ]
        assert "whole script once" in result["instruction"]

        row = await isolated_db.get(
            OptimizationLiveTestRequest, uuid.UUID(result["live_test_request_id"])
        )
        await isolated_db.refresh(row)
        assert row.status is OptimizationLiveTestStatus.pending
        assert row.target_agent_type_id == subject.id
        assert row.script_version_id == version.id
        assert row.requested_operations == result["operations"]
        assert row.executed_operations is None
        assert row.intervene_request_id is not None
        assert row.request_turn_id is not None

        intervention = await isolated_db.get(
            InterveneRequest, row.intervene_request_id
        )
        await isolated_db.refresh(intervention)
        assert intervention.intervention_type is InterventionType.approval
        assert intervention.status is InterveneRequestStatus.pending
        assert intervention.conversation_session_id == session.id
        # The card names the script and says what it will call.
        assert "**Run this script live**" in intervention.reason
        assert definition.name in intervention.reason
        assert "It will call:" in intervention.reason
        assert PERMITTED_TOOL in intervention.reason
        assert "ONCE" in intervention.reason

    @pytest.mark.asyncio
    async def test_the_caller_never_supplies_the_operation_list(
        self, isolated_db: AsyncSession
    ):
        """``tool_args.operations`` is ignored: the preview is the script's own."""
        from app.api.v1.internal.system_tools import request_live_test_tool

        tenant = await _tenant(isolated_db)
        subject = await _subject(isolated_db, tenant.id)
        session = await _session(isolated_db, tenant.id, subject)
        _definition, version = await _script(isolated_db, tenant.id, subject)
        await isolated_db.commit()

        with _as_tenant(tenant):
            response = await request_live_test_tool(
                _body(
                    agent_type_id=str(subject.id),
                    conversation_session_id=str(session.id),
                    tool_args={
                        "script_version_id": str(version.id),
                        "reason": "tamper",
                        # Ignored — no operation list is accepted.
                        "operations": [
                            {
                                "tool_name": "other-server____deleteEverything",
                                "arguments": {},
                                "purpose": "tamper",
                            }
                        ],
                    },
                ),
                _tenant_ctx(tenant),
                isolated_db,
            )

        assert response.result["status"] == "pending"
        assert [op["tool_name"] for op in response.result["operations"]] == [
            PERMITTED_TOOL,
            SECOND_TOOL,
        ]
        assert all(
            "deleteEverything" not in op["tool_name"]
            for op in response.result["operations"]
        )

    @pytest.mark.asyncio
    async def test_a_replay_of_the_same_script_version_returns_the_stored_proposal(
        self, isolated_db: AsyncSession
    ):
        from app.api.v1.internal.system_tools import request_live_test_tool

        tenant = await _tenant(isolated_db)
        subject = await _subject(isolated_db, tenant.id)
        session = await _session(isolated_db, tenant.id, subject)
        _definition, version = await _script(isolated_db, tenant.id, subject)
        await isolated_db.commit()
        args = {
            "agent_type_id": str(subject.id),
            "conversation_session_id": str(session.id),
            "tool_args": {"script_version_id": str(version.id), "reason": "r"},
        }

        with _as_tenant(tenant):
            first = await request_live_test_tool(
                _body(**args), _tenant_ctx(tenant), isolated_db
            )
            second = await request_live_test_tool(
                _body(**args), _tenant_ctx(tenant), isolated_db
            )

        assert first.result["status"] == second.result["status"] == "pending"
        assert first.result["live_test_request_id"] == (
            second.result["live_test_request_id"]
        )
        assert await _count(isolated_db, OptimizationLiveTestRequest) == 1
        assert await _count(isolated_db, InterveneRequest) == 1

    @pytest.mark.asyncio
    async def test_a_second_different_proposal_is_refused_while_one_is_pending(
        self, isolated_db: AsyncSession
    ):
        from app.api.v1.internal.system_tools import request_live_test_tool

        tenant = await _tenant(isolated_db)
        subject = await _subject(isolated_db, tenant.id)
        session = await _session(isolated_db, tenant.id, subject)
        _definition, first_version = await _script(isolated_db, tenant.id, subject)
        _definition2, second_version = await _script(isolated_db, tenant.id, subject)
        await isolated_db.commit()

        with _as_tenant(tenant):
            first = await request_live_test_tool(
                _body(
                    agent_type_id=str(subject.id),
                    conversation_session_id=str(session.id),
                    tool_args={
                        "script_version_id": str(first_version.id),
                        "reason": "one",
                    },
                ),
                _tenant_ctx(tenant),
                isolated_db,
            )
            second = await request_live_test_tool(
                _body(
                    agent_type_id=str(subject.id),
                    conversation_session_id=str(session.id),
                    tool_args={
                        "script_version_id": str(second_version.id),
                        "reason": "two",
                    },
                ),
                _tenant_ctx(tenant),
                isolated_db,
            )

        assert first.result["status"] == "pending"
        assert second.result["status"] == "refused"
        assert second.result["reason_code"] == "live_test_already_pending"
        assert await _count(isolated_db, OptimizationLiveTestRequest) == 1

    @pytest.mark.asyncio
    async def test_a_script_without_literal_tool_calls_is_refused(
        self, isolated_db: AsyncSession
    ):
        from app.api.v1.internal.system_tools import request_live_test_tool

        tenant = await _tenant(isolated_db)
        subject = await _subject(isolated_db, tenant.id)
        session = await _session(isolated_db, tenant.id, subject)
        _definition, version = await _script(
            isolated_db,
            tenant.id,
            subject,
            source="def run(context, tools):\n    return {'ok': True}\n",
        )
        await isolated_db.commit()

        with _as_tenant(tenant):
            response = await request_live_test_tool(
                _body(
                    agent_type_id=str(subject.id),
                    conversation_session_id=str(session.id),
                    tool_args={"script_version_id": str(version.id), "reason": "r"},
                ),
                _tenant_ctx(tenant),
                isolated_db,
            )

        assert response.result["status"] == "refused"
        assert response.result["reason_code"] == "no_tool_calls"
        assert await _count(isolated_db, OptimizationLiveTestRequest) == 0
        assert await _count(isolated_db, InterveneRequest) == 0
