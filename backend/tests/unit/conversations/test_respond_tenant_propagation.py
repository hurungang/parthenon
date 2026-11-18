"""Regression — the answered-turn resume dispatch must carry the request tenant.

Multi-tenancy is enabled in production, so every internal data-plane call needs
the signed ``X-Internal-Tenant-*`` header set.  The conversation-scoped resume
dispatch used to read the module contextvar (``get_current_tenant_context()``)
only.  That contextvar is **not** bound on the answer path:

* ``/api/v1/internal/*`` is a tenant-resolution bypass (the tenant is verified
  from the signed headers by ``require_internal_tenant_context`` — the
  dependency result was discarded), and
* the WebSocket answer path (CH → CC ``/internal/data/intervene/respond``) is
  the production route for an intervention answer.

Result: the CC → CH resume dispatch went out headerless, CH relayed headerless,
and CC's ``.../resume/claim`` rejected it 401 — marking a perfectly valid pause
``unresumable``.

These tests pin the contract: **all three** respond callers thread the tenant
resolved from the request (or from the internal-auth dependency) explicitly into
``dispatch_answered_conversation_turn``.  Each test asserts the contextvar is
NOT bound, so a contextvar-only implementation cannot pass.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.deps import (
    require_internal_tenant_context,
    require_permission,
    require_service_certificate,
)
from app.api.v1.conversations import ConversationRouter
from app.api.v1.intervene import InterveneRouter
from app.api.v1.internal.session_data import InternalSessionDataRouter
from app.core.resource_types import RT_AGENT_HUMAN_INTERVENTION, RT_AGENT_TRAILS
from app.core.tenant_context import (
    TenantContext,
    get_current_tenant_context,
    set_tenant_context,
)
from app.db.models.agents import AgentInputType, AgentType
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.db.models.identity import Identity
from app.db.models.intervene import InterveneRequest, InterventionType
from app.db.session import get_db
from app.services.control_center.agent_runtime_client import AgentRuntimeClient
from app.services.conversations.turn_resume_store import ConversationTurnResumeStore

TENANT = TenantContext(tenant_id=uuid.uuid4(), slug="acme", name="Acme Corp")

#: The authenticated operator's OIDC subject used by every respond caller.
OPERATOR_SUBJECT = "tenant-propagation-operator"


# ── Seeding ───────────────────────────────────────────────────────────────────


async def _seed_paused_conversation(
    db: AsyncSession,
) -> tuple[ConversationSession, InterveneRequest, Identity]:
    """A conversation-scoped pause with a LIVE (resumable) resume record."""
    from sqlalchemy import select

    conv = ConversationSession(status=ConversationStatus.active)
    db.add(conv)
    agent_type = AgentType(
        name=f"tenant-prop-{uuid.uuid4().hex[:8]}",
        input_type=AgentInputType.conversation,
    )
    db.add(agent_type)
    await db.flush()

    # Reuse across tests: the DB engine is session-scoped.
    operator = (
        await db.execute(select(Identity).where(Identity.subject == OPERATOR_SUBJECT))
    ).scalar_one_or_none()
    if operator is None:
        operator = Identity(
            id=uuid.uuid4(),
            subject=OPERATOR_SUBJECT,
            display_name="Operator",
        )
        db.add(operator)
        await db.flush()

    req = InterveneRequest(
        agent_type_id=agent_type.id,
        intervention_type=InterventionType.approval,
        reason="**Create Skill: Tenant Propagation**",
        conversation_session_id=conv.id,
    )
    db.add(req)
    await db.flush()

    await ConversationTurnResumeStore().create_or_reuse(
        conv.id,
        db,
        intervene_request_id=req.id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    await db.commit()
    return conv, req, operator


# ── Resume-call capture ───────────────────────────────────────────────────────


@pytest.fixture
def resume_calls(monkeypatch) -> list[dict]:
    """Capture every resume dispatch without touching CH/AR over the wire.

    The captured header set mirrors the real client exactly:
    ``AgentRuntimeClient.resume_session`` signs with
    ``tenant_context_headers(tenant_context)`` before the POST to CH.
    """
    from app.core.tenant_signature import tenant_context_headers

    calls: list[dict] = []

    async def _fake_resume_session(
        self,
        session_id,
        response_value=None,
        tenant_context=None,
        *,
        resume_id=None,
        request_id=None,
    ):
        calls.append(
            {
                "session_id": session_id,
                "tenant_context": tenant_context,
                "headers": tenant_context_headers(tenant_context),
                "resume_id": resume_id,
                "request_id": request_id,
                # Provable: the tenant did NOT come from the module contextvar.
                "contextvar": get_current_tenant_context(),
            }
        )
        return {"status": "resumed"}

    monkeypatch.setattr(AgentRuntimeClient, "resume_session", _fake_resume_session)
    return calls


def _assert_signed_for(context: TenantContext, headers: dict[str, str]) -> None:
    """The CC→CH resume request must carry a CH/CC-verifiable signed set."""
    from app.core.tenant_signature import verify_tenant_signature_headers

    assert headers, "the resume request must carry signed tenant headers"
    verified = verify_tenant_signature_headers(headers)
    assert str(verified.tenant_id) == str(context.tenant_id)
    assert verified.slug == context.slug


# ── App builders (one per respond caller) ─────────────────────────────────────


class _ResolvedTenantMiddleware(BaseHTTPMiddleware):
    """Stand-in for ``TenantResolutionMiddleware`` (tenancy ON, tenant bound).

    Sets the resolved context on ``request.state`` exactly like production and
    deliberately does NOT bind the module contextvar — the real middleware's
    bind is not visible to internal/bypassed paths, which is the whole point.
    """

    async def dispatch(self, request: Request, call_next):
        request.state.tenancy_enabled = True
        set_tenant_context(request, TENANT)
        return await call_next(request)


def _client(app: FastAPI, db: AsyncSession) -> AsyncClient:
    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def intervene_client(db_session: AsyncSession):
    app = FastAPI()
    app.add_middleware(_ResolvedTenantMiddleware)
    app.include_router(InterveneRouter, prefix="/api/v1")
    app.dependency_overrides[
        require_permission(RT_AGENT_HUMAN_INTERVENTION, "respond")
    ] = lambda: {"sub": OPERATOR_SUBJECT}
    async with _client(app, db_session) as client:
        yield client


@pytest_asyncio.fixture
async def conversation_client(db_session: AsyncSession):
    app = FastAPI()
    app.add_middleware(_ResolvedTenantMiddleware)
    app.include_router(ConversationRouter, prefix="/api/v1")
    app.dependency_overrides[require_permission(RT_AGENT_TRAILS, "read")] = (
        lambda: {"sub": OPERATOR_SUBJECT}
    )
    async with _client(app, db_session) as client:
        yield client


@pytest_asyncio.fixture
async def internal_client(db_session: AsyncSession):
    """The CH → CC answer path — a tenant-resolution BYPASS in production."""
    app = FastAPI()
    app.include_router(InternalSessionDataRouter, prefix="/api/v1")
    app.dependency_overrides[require_service_certificate] = lambda: None
    app.dependency_overrides[require_internal_tenant_context] = lambda: TENANT
    async with _client(app, db_session) as client:
        yield client


# ── Tests: one per respond caller ─────────────────────────────────────────────


class TestInterveneRespondTenantPropagation:
    @pytest.mark.asyncio
    async def test_conversation_scoped_respond_threads_request_tenant(
        self, db_session: AsyncSession, intervene_client: AsyncClient,
        resume_calls: list[dict],
    ):
        conv, req, _operator = await _seed_paused_conversation(db_session)

        response = await intervene_client.post(
            f"/api/v1/intervene/requests/{req.id}/respond",
            json={"request_id": str(req.id), "approval_value": True},
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 200, response.text

        assert len(resume_calls) == 1, "exactly one resume dispatch"
        call = resume_calls[0]
        assert call["session_id"] == conv.id
        assert call["tenant_context"] == TENANT, (
            "the resume dispatch must carry the REQUEST-resolved tenant "
            f"(got {call['tenant_context']!r})"
        )
        _assert_signed_for(TENANT, call["headers"])
        assert call["contextvar"] is None, (
            "the contextvar must not be the propagation source"
        )


class TestConversationInterventionRespondTenantPropagation:
    @pytest.mark.asyncio
    async def test_conversation_intervention_respond_threads_request_tenant(
        self, db_session: AsyncSession, conversation_client: AsyncClient,
        resume_calls: list[dict],
    ):
        conv, req, _operator = await _seed_paused_conversation(db_session)

        response = await conversation_client.post(
            f"/api/v1/conversations/{conv.id}/interventions/{req.id}/respond",
            json={"request_id": str(req.id), "approval_value": True},
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 200, response.text

        assert len(resume_calls) == 1
        call = resume_calls[0]
        assert call["session_id"] == conv.id
        assert call["tenant_context"] == TENANT
        _assert_signed_for(TENANT, call["headers"])
        assert call["contextvar"] is None


class TestInternalInterveneRespondTenantPropagation:
    @pytest.mark.asyncio
    async def test_internal_respond_threads_verified_dependency_tenant(
        self, db_session: AsyncSession, internal_client: AsyncClient,
        resume_calls: list[dict],
    ):
        """The production WS answer route: no contextvar, verified dependency."""
        conv, req, operator = await _seed_paused_conversation(db_session)

        response = await internal_client.post(
            "/api/v1/internal/data/intervene/respond",
            json={
                "request_id": str(req.id),
                "approval_value": True,
                "operator_subject": operator.subject,
            },
        )
        assert response.status_code == 200, response.text

        assert len(resume_calls) == 1
        call = resume_calls[0]
        assert call["session_id"] == conv.id
        assert call["request_id"] == req.id
        assert call["tenant_context"] == TENANT, (
            "require_internal_tenant_context's verified context must be "
            "threaded into the resume dispatch"
        )
        _assert_signed_for(TENANT, call["headers"])
        assert call["contextvar"] is None, (
            "this path bypasses tenant resolution — no contextvar to fall back on"
        )


class TestOptionalTenantContextHelper:
    """``optional_tenant_context`` is request-derived, never contextvar-derived."""

    def test_none_when_tenancy_disabled(self):
        from app.core.tenant_context import optional_tenant_context

        class _Req:
            class state:  # noqa: N801 - request.state stand-in
                tenancy_enabled = False
                tenant_context = TENANT

        assert optional_tenant_context(_Req()) is None  # type: ignore[arg-type]

    def test_returns_bound_context_when_enabled(self):
        from app.core.tenant_context import optional_tenant_context

        class _Req:
            class state:  # noqa: N801 - request.state stand-in
                tenancy_enabled = True
                tenant_context = TENANT

        assert optional_tenant_context(_Req()) is TENANT  # type: ignore[arg-type]

    def test_none_when_unresolved(self):
        from app.core.tenant_context import optional_tenant_context

        class _Req:
            class state:  # noqa: N801 - request.state stand-in
                tenancy_enabled = True

        assert optional_tenant_context(_Req()) is None  # type: ignore[arg-type]
