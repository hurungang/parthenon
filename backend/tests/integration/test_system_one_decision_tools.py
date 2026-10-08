"""Integration tests for System One decision tools.

Covers:
- migration verification via the schema (decision_tools /
  decision_tool_questions exist with unique (tenant_id, name);
  skills.skill_type ABSENT; decision_skill tables ABSENT — negative probes)
- decision tool CRUD via the API
- per-tenant name uniqueness: duplicate within one tenant → 409, the SAME
  name in two tenants → both 201 (tenant isolation)
- configured-model authoring gate (422 without a provider)
- per-question-type validation negatives
- auto-generated description generation (regenerated on update)
- execution with a mocked transport (single dispatch, typed answers,
  DecisionExecutionResult persisted keyed to the tool)
- decision results query by decision_tool_id
- permission enforcement on system::decision_tools
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_permission
from app.core.resource_types import (
    RT_AGENT_TRAILS,
    RT_SYSTEM_DECISION_TOOLS,
    RT_SYSTEM_SYSTEM_ONE,
)
from app.db.models.decision_tools import DecisionTool
from app.db.models.skills import Skill, SkillToolBinding
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware
from app.services.system_one.provider_config_service import (
    SystemOneProviderConfigService,
)

TOOLS_URL = "/api/v1/decision-tools"
RESULTS_URL = "/api/v1/results/decision"
PROVIDERS_URL = "/api/v1/system-one/providers"
SKILLS_URL = "/api/v1/skills"

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


def _bypass_jwt_middleware():
    """Patch JWTAuthMiddleware to inject identity claims without real JWT."""
    from unittest.mock import patch as _patch

    async def _patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "test-admin", "roles": ["admin"]}
        return await call_next(request)

    return _patch.object(JWTAuthMiddleware, "dispatch", _patched_dispatch)


def _allow_all():
    async def _dep():
        return {"user_id": "test-user", "permissions": ["*::*"]}

    return _dep


VALID_TOOL = {
    "name": "approve_loan",
    "purpose": "Approve or reject small loan applications",
    "state_preset": {
        "amount": {"source": "input", "key": "amount"},
        "history": {"source": "agent_data", "key": "customer_history"},
    },
    "act_threshold": 0.9,
    "confirm_threshold": 0.7,
    "questions": [
        {
            "question_key": "approve",
            "question_type": "choice",
            "instructions": "Should this loan be approved?",
            "criteria_options": {"yes": "approve", "no": "reject"},
            "ordering": 0,
        },
        {
            "question_key": "risk_score",
            "question_type": "score",
            "instructions": "Rate applicant risk",
            "criteria_options": ["very low", "low", "medium", "high"],
            "ordering": 1,
        },
        {
            "question_key": "identity_verified",
            "question_type": "noul",
            "instructions": "Is the identity verified?",
            "ordering": 2,
        },
    ],
}


async def _clean_tables(session: AsyncSession) -> None:
    from app.db.models.results import DecisionExecutionResult
    from app.db.models.system_one_provider_config import SystemOneProviderConfig

    await session.execute(DecisionExecutionResult.__table__.delete())
    await session.execute(DecisionTool.__table__.delete())
    await session.execute(SystemOneProviderConfig.__table__.delete())
    await session.commit()


@pytest_asyncio.fixture
async def tools_client(test_engine):
    """Client with decision-tools + results + system-one permissions allowed.

    Supports a test-only tenant context via the ``X-Test-Tenant`` header
    (patched into the router module), so per-tenant scenarios can run
    without enabling multi-tenancy.
    """
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    async with SessionLocal() as session:
        await _clean_tables(session)

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    for action in ("read", "create", "update", "delete"):
        app.dependency_overrides[
            require_permission(RT_SYSTEM_DECISION_TOOLS, action)
        ] = _allow_all()
    app.dependency_overrides[require_permission(RT_AGENT_TRAILS, "read")] = _allow_all()
    app.dependency_overrides[require_permission(RT_SYSTEM_SYSTEM_ONE, "read")] = _allow_all()
    app.dependency_overrides[require_permission(RT_SYSTEM_SYSTEM_ONE, "manage")] = _allow_all()

    # Test-only tenant context: header-driven, replaces tenant resolution.
    import app.api.v1.decision_tools as dt_api
    import app.api.v1.system_one as so_api
    from app.core.tenant_context import TenantContext

    original_get_ctx = dt_api.get_tenant_context
    original_so_get_ctx = so_api.get_tenant_context

    def fake_get_tenant_context(request):
        raw = request.headers.get("x-test-tenant")
        if not raw:
            return original_get_ctx(request)
        return TenantContext(
            tenant_id=uuid.UUID(raw), slug=f"t-{raw[:8]}", name=f"tenant-{raw[:8]}"
        )

    dt_api.get_tenant_context = fake_get_tenant_context
    so_api.get_tenant_context = fake_get_tenant_context

    with _bypass_jwt_middleware():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    dt_api.get_tenant_context = original_get_ctx
    so_api.get_tenant_context = original_so_get_ctx


@pytest_asyncio.fixture
async def skills_client(test_engine):
    """Client with agent-skills permissions allowed and header-driven tenant
    context (mirrors ``tools_client`` for the skills API)."""
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    async with SessionLocal() as session:
        await _clean_tables(session)

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    from app.core.resource_types import RT_AGENT_SKILLS

    for action in ("read", "create", "update", "delete"):
        app.dependency_overrides[require_permission(RT_AGENT_SKILLS, action)] = _allow_all()

    import app.api.v1.skills as skills_api
    from app.core.tenant_context import TenantContext

    original_get_ctx = skills_api.get_tenant_context

    def fake_get_tenant_context(request):
        raw = request.headers.get("x-test-tenant")
        if not raw:
            return original_get_ctx(request)
        return TenantContext(
            tenant_id=uuid.UUID(raw), slug=f"t-{raw[:8]}", name=f"tenant-{raw[:8]}"
        )

    skills_api.get_tenant_context = fake_get_tenant_context

    with _bypass_jwt_middleware():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    skills_api.get_tenant_context = original_get_ctx


@pytest_asyncio.fixture
async def no_permission_client(test_engine):
    """Client WITHOUT permission overrides — real require_permission runs."""
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest_asyncio.fixture
async def provider_configured(tools_client):
    """Create enabled System One providers via the real API for every tenant
    scope the tests use (root/unscoped + TENANT_A + TENANT_B) — provider
    resolution is tenant-contained, so each scope needs its own config."""
    ids = {}
    for label, tenant in (
        ("root", None),
        ("a", TENANT_A),
        ("b", TENANT_B),
    ):
        headers = {"x-test-tenant": str(tenant)} if tenant else {}
        resp = await tools_client.post(
            PROVIDERS_URL,
            json={
                "provider_type": "typesafe",
                "display_name": f"TypeSafe Jev (decision tests, {label})",
                "base_url": "http://localhost:9999/v1",
                "default_model": "jev-latest",
                "api_key": "sk-decision-test-key-1234567890",
                "enabled": True,
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        ids[label] = resp.json()["id"]
    return ids["root"]


class FakeTransport:
    """Records dispatches; returns a canned provider response."""

    def __init__(self, response=None):
        self.calls: list[dict] = []
        self.response = response or {
            "model": "jev-latest",
            "answers": {
                "approve": {
                    "type": "choice",
                    "choice": "yes",
                    "probabilities": {"yes": 0.95, "no": 0.05},
                    "confidence": 0.95,
                },
                "risk_score": {"type": "score", "score": 2, "confidence": 0.85},
                "identity_verified": {"type": "noul", "noul": 1.0},
            },
        }

    async def evaluate(self, *, base_url, api_key, model, state, questions, **kw):
        self.calls.append(
            {
                "base_url": base_url,
                "api_key": api_key,
                "model": model,
                "state": state,
                "questions": questions,
            }
        )
        return self.response


# ── Migration verification (schema probes) ────────────────────────────────


class TestMigrationState:
    @staticmethod
    async def _run(test_engine, fn):
        async with test_engine.connect() as conn:
            return await conn.run_sync(lambda c: fn(sa_inspect(c)))

    @staticmethod
    async def _table_names(test_engine):
        return await TestMigrationState._run(test_engine, lambda i: i.get_table_names())

    @pytest.mark.asyncio
    async def test_decision_tool_tables_exist(self, test_engine):
        names = await self._table_names(test_engine)
        assert "decision_tools" in names
        assert "decision_tool_questions" in names

    @pytest.mark.asyncio
    async def test_unique_constraint_tenant_id_name(self, test_engine):
        uqs = await self._run(test_engine, lambda i: i.get_unique_constraints("decision_tools"))
        column_sets = [set(u["column_names"]) for u in uqs]
        assert {"tenant_id", "name"} in column_sets

    @pytest.mark.asyncio
    async def test_duplicate_name_same_tenant_rejected_at_db_level(
        self, test_engine
    ):
        from sqlalchemy.exc import IntegrityError

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        tenant = uuid.uuid4()
        async with SessionLocal() as session:
            for _ in range(2):
                session.add(
                    DecisionTool(
                        tenant_id=tenant, name="tool_a", act_threshold=0.9,
                        confirm_threshold=0.7,
                    )
                )
            try:
                await session.commit()
                raised = None
            except IntegrityError:
                raised = True
                await session.rollback()
        assert raised, "unique (tenant_id, name) constraint not enforced"

    @pytest.mark.asyncio
    async def test_skills_table_has_no_skill_type_column(self, test_engine):
        assert "skills" in await self._table_names(test_engine)
        columns = await self._run(test_engine, lambda i: {c["name"] for c in i.get_columns("skills")})
        assert "skill_type" not in columns

    @pytest.mark.asyncio
    async def test_decision_skill_tables_absent(self, test_engine):
        names = await self._table_names(test_engine)
        leftovers = [n for n in names if n.startswith("decision_skill")]
        assert leftovers == [], f"decision_skill tables still present: {leftovers}"

    @pytest.mark.asyncio
    async def test_information_schema_postgres(self):
        """Direct information_schema verification against the real Postgres DB.

        Runs against the parthenon-postgres container DB (where alembic
        migrations are applied); skips cleanly when Postgres is unreachable.
        """
        import socket

        try:
            socket.create_connection(("localhost", 5432), timeout=1).close()
        except OSError:
            pytest.skip("PostgreSQL not reachable on localhost:5432")

        import asyncpg

        try:
            conn = await asyncpg.connect(
                "postgresql://parthenon:parthenon@localhost:5432/parthenon"
            )
        except Exception:
            pytest.skip("parthenon Postgres database not reachable")
        try:
                rows = await conn.fetch(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' "
                    "AND table_name IN ('decision_tools', 'decision_tool_questions')"
                )
                assert {r[0] for r in rows} == {
                    "decision_tools",
                    "decision_tool_questions",
                }
                uq = await conn.fetch(
                    "SELECT tc.constraint_name, kcu.column_name "
                    "FROM information_schema.table_constraints tc "
                    "JOIN information_schema.key_column_usage kcu "
                    "ON tc.constraint_name = kcu.constraint_name "
                    "WHERE tc.table_name = 'decision_tools' "
                    "AND tc.constraint_type = 'UNIQUE'"
                )
                assert {"tenant_id", "name"} <= {r[1] for r in uq}, (
                    "unique (tenant_id, name) constraint missing"
                )
                skill_type = await conn.fetch(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'skills' AND column_name = 'skill_type'"
                )
                assert skill_type == []
                decision_skill = await conn.fetch(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_name LIKE 'decision_skill%'"
                )
                assert decision_skill == []
        finally:
            await conn.close()


# ── CRUD ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDecisionToolCrud:
    async def test_create_returns_201_with_generated_description(
        self, tools_client, provider_configured
    ):
        resp = await tools_client.post(TOOLS_URL, json=VALID_TOOL)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["name"] == VALID_TOOL["name"]
        assert body["description"], "auto-generated description must be present"
        assert VALID_TOOL["purpose"] in body["description"]
        assert "approve" in body["description"]
        assert len(body["questions"]) == 3

    async def test_get_by_id(self, tools_client, provider_configured):
        created = (await tools_client.post(TOOLS_URL, json=VALID_TOOL)).json()
        resp = await tools_client.get(f"{TOOLS_URL}/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    async def test_list_within_tenant(self, tools_client, provider_configured):
        await tools_client.post(TOOLS_URL, json=VALID_TOOL)
        await tools_client.post(
            TOOLS_URL, json={**VALID_TOOL, "name": "second_tool"}
        )
        resp = await tools_client.get(TOOLS_URL)
        assert resp.status_code == 200
        names = {t["name"] for t in resp.json()}
        assert {"approve_loan", "second_tool"} <= names

    async def test_update_regenerates_description(
        self, tools_client, provider_configured
    ):
        created = (await tools_client.post(TOOLS_URL, json=VALID_TOOL)).json()
        old_description = created["description"]

        resp = await tools_client.put(
            f"{TOOLS_URL}/{created['id']}",
            json={"purpose": "Brand new purpose for lending decisions"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["description"] != old_description
        assert "Brand new purpose" in body["description"]

        # description endpoint reflects the regenerated text too
        desc = await tools_client.get(f"{TOOLS_URL}/{created['id']}/description")
        assert desc.status_code == 200
        assert "Brand new purpose" in desc.json()["description"]

    async def test_delete_returns_204(self, tools_client, provider_configured):
        created = (await tools_client.post(TOOLS_URL, json=VALID_TOOL)).json()
        resp = await tools_client.delete(f"{TOOLS_URL}/{created['id']}")
        assert resp.status_code == 204
        assert (await tools_client.get(TOOLS_URL)).json() == []

    async def test_cross_tenant_get_returns_404(
        self, tools_client, provider_configured
    ):
        created = (
            await tools_client.post(
                TOOLS_URL, json=VALID_TOOL, headers={"x-test-tenant": str(TENANT_A)}
            )
        ).json()
        resp = await tools_client.get(
            f"{TOOLS_URL}/{created['id']}", headers={"x-test-tenant": str(TENANT_B)}
        )
        assert resp.status_code == 404


# ── Per-tenant name uniqueness ────────────────────────────────────────────


@pytest.mark.asyncio
class TestTenantNameUniqueness:
    async def test_duplicate_name_same_tenant_409(self, tools_client, provider_configured):
        first = await tools_client.post(TOOLS_URL, json=VALID_TOOL)
        assert first.status_code == 201
        dup = await tools_client.post(TOOLS_URL, json=VALID_TOOL)
        assert dup.status_code == 409
        assert isinstance(dup.json()["detail"], list)

    async def test_duplicate_rejected_no_partial_questions(
        self, tools_client, provider_configured, test_engine
    ):
        await tools_client.post(TOOLS_URL, json=VALID_TOOL)
        await tools_client.post(TOOLS_URL, json=VALID_TOOL)  # 409
        SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession)
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    select(DecisionTool).where(DecisionTool.name == "approve_loan")
                )
            ).scalars().all()
        assert len(rows) == 1

    async def test_same_name_in_two_tenants_both_201(
        self, tools_client, provider_configured
    ):
        ra = await tools_client.post(
            TOOLS_URL, json=VALID_TOOL, headers={"x-test-tenant": str(TENANT_A)}
        )
        rb = await tools_client.post(
            TOOLS_URL, json=VALID_TOOL, headers={"x-test-tenant": str(TENANT_B)}
        )
        assert ra.status_code == 201, ra.text
        assert rb.status_code == 201, rb.text
        assert ra.json()["id"] != rb.json()["id"]
        assert str(TENANT_A) == ra.json()["tenant_id"]
        assert str(TENANT_B) == rb.json()["tenant_id"]

    async def test_list_is_tenant_scoped(self, tools_client, provider_configured):
        await tools_client.post(
            TOOLS_URL, json=VALID_TOOL, headers={"x-test-tenant": str(TENANT_A)}
        )
        list_b = await tools_client.get(
            TOOLS_URL, headers={"x-test-tenant": str(TENANT_B)}
        )
        assert list_b.status_code == 200
        assert list_b.json() == []


# ── Configured-model authoring gate ───────────────────────────────────────


@pytest.mark.asyncio
class TestAuthoringGate:
    async def test_create_without_provider_422(self, tools_client):
        resp = await tools_client.post(TOOLS_URL, json=VALID_TOOL)
        assert resp.status_code == 422
        assert "No System One model" in str(resp.json()["detail"])

    async def test_create_with_provider_succeeds(self, tools_client, provider_configured):
        resp = await tools_client.post(TOOLS_URL, json=VALID_TOOL)
        assert resp.status_code == 201

    async def test_delete_provider_blocks_authoring_again(
        self, tools_client, provider_configured
    ):
        await tools_client.delete(f"{PROVIDERS_URL}/{provider_configured}")
        resp = await tools_client.post(TOOLS_URL, json=VALID_TOOL)
        assert resp.status_code == 422


# ── Per-type question validation negatives ────────────────────────────────


@pytest.mark.asyncio
class TestQuestionValidation:
    async def _post(self, tools_client, questions):
        return await tools_client.post(
            TOOLS_URL, json={**VALID_TOOL, "name": f"v-{uuid.uuid4().hex[:8]}", "questions": questions}
        )

    async def test_zero_questions_rejected(self, tools_client, provider_configured):
        resp = await self._post(tools_client, [])
        assert resp.status_code == 422

    async def test_choice_without_options_rejected(self, tools_client, provider_configured):
        resp = await self._post(
            tools_client,
            [{"question_key": "q", "question_type": "choice", "criteria_options": {}}],
        )
        assert resp.status_code == 422

    async def test_choice_with_none_options_rejected(self, tools_client, provider_configured):
        resp = await self._post(
            tools_client,
            [{"question_key": "q", "question_type": "choice"}],
        )
        assert resp.status_code == 422

    async def test_score_without_legend_rejected(self, tools_client, provider_configured):
        resp = await self._post(
            tools_client,
            [{"question_key": "q", "question_type": "score", "criteria_options": []}],
        )
        assert resp.status_code == 422

    async def test_noul_with_criteria_rejected(self, tools_client, provider_configured):
        resp = await self._post(
            tools_client,
            [
                {
                    "question_key": "q",
                    "question_type": "noul",
                    "criteria_options": {"a": "b"},
                }
            ],
        )
        assert resp.status_code == 422

    async def test_duplicate_question_keys_rejected(self, tools_client, provider_configured):
        question = {
            "question_key": "same_key",
            "question_type": "noul",
        }
        resp = await self._post(tools_client, [question, dict(question)])
        assert resp.status_code == 422

    async def test_invalid_state_preset_source_rejected(self, tools_client, provider_configured):
        resp = await tools_client.post(
            TOOLS_URL,
            json={
                **VALID_TOOL,
                "name": f"v-{uuid.uuid4().hex[:8]}",
                "state_preset": {"x": {"source": "bogus", "key": "k"}},
            },
        )
        assert resp.status_code == 422

    async def test_act_below_confirm_rejected(self, tools_client, provider_configured):
        resp = await tools_client.post(
            TOOLS_URL,
            json={
                **VALID_TOOL,
                "name": f"v-{uuid.uuid4().hex[:8]}",
                "act_threshold": 0.5,
                "confirm_threshold": 0.8,
            },
        )
        assert resp.status_code == 422


# ── Execution (mocked transport) ──────────────────────────────────────────


@pytest.mark.asyncio
class TestExecution:
    async def test_execute_single_dispatch_typed_answers_and_persistence(
        self, tools_client, provider_configured, test_engine, monkeypatch
    ):
        created = (await tools_client.post(TOOLS_URL, json=VALID_TOOL)).json()

        fake = FakeTransport()
        import app.services.system_one.decision_engine as engine_module

        monkeypatch.setattr(engine_module, "TypeSafeJevClient", lambda: fake)

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        from app.services.system_one.decision_engine import DecisionExecutionEngine

        async with SessionLocal() as session:
            tool = (
                await session.execute(
                    select(DecisionTool)
                    .where(DecisionTool.id == uuid.UUID(created["id"]))
                    .options(selectinload(DecisionTool.questions))
                )
            ).scalar_one()

            engine = DecisionExecutionEngine()
            result = await engine.execute(
                db=session,
                tool=tool,
                input_state={"amount": 5000, "agent_data": {"customer_history": "clean"}},
                tenant_id=tool.tenant_id,
            )
            await session.commit()

            # single dispatch carrying state + ALL questions
            assert len(fake.calls) == 1
            call = fake.calls[0]
            assert set(call["questions"].keys()) == {
                "approve",
                "risk_score",
                "identity_verified",
            }
            assert call["state"]["amount"] == 5000
            assert call["state"]["history"] == "clean"
            assert call["api_key"] == "sk-decision-test-key-1234567890"
            assert call["model"] == "jev-latest"
            # noul question carries no criteria
            assert "criteria" not in call["questions"]["identity_verified"]

            # gate: min effective confidence = 0.85 (score) → confirm
            assert result.outcome.value == "confirm"
            assert result.status.value == "completed"
            assert result.decision_tool_id == tool.id
            answers = result.answers["answers"]
            assert answers["approve"]["choice"] == "yes"
            assert answers["approve"]["probabilities"] == {"yes": 0.95, "no": 0.05}
            assert answers["identity_verified"]["effective_confidence"] == pytest.approx(1.0)

            result_id = result.id

        # queryable via the decision results endpoint
        resp = await tools_client.get(
            RESULTS_URL, params={"decision_tool_id": created["id"]}
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["id"] == str(result_id)
        assert items[0]["decision_tool_id"] == created["id"]
        assert items[0]["outcome"] == "confirm"
        # no key material anywhere in results
        assert "sk-decision-test-key-1234567890" not in resp.text

    async def test_results_keyed_to_tool_only(self, tools_client, provider_configured, test_engine, monkeypatch):
        """Results are keyed to decision_tool_id; another tool has none."""
        created = (await tools_client.post(TOOLS_URL, json=VALID_TOOL)).json()
        other = (
            await tools_client.post(TOOLS_URL, json={**VALID_TOOL, "name": "other_tool"})
        ).json()

        fake = FakeTransport()
        import app.services.system_one.decision_engine as engine_module

        monkeypatch.setattr(engine_module, "TypeSafeJevClient", lambda: fake)

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        from app.services.system_one.decision_engine import DecisionExecutionEngine

        async with SessionLocal() as session:
            tool = (
                await session.execute(
                    select(DecisionTool)
                    .where(DecisionTool.id == uuid.UUID(created["id"]))
                    .options(selectinload(DecisionTool.questions))
                )
            ).scalar_one()
            await DecisionExecutionEngine().execute(
                db=session, tool=tool, input_state={"amount": 1, "agent_data": {"customer_history": "x"}},
                tenant_id=tool.tenant_id,
            )
            await session.commit()

        r_tool = await tools_client.get(
            RESULTS_URL, params={"decision_tool_id": created["id"]}
        )
        assert r_tool.status_code == 200
        assert len(r_tool.json()) == 1
        assert r_tool.json()[0]["decision_tool_id"] == created["id"]

        r_other = await tools_client.get(
            RESULTS_URL, params={"decision_tool_id": other["id"]}
        )
        assert r_other.status_code == 200
        assert r_other.json() == []

    async def test_provider_failure_persists_failed_result(
        self, tools_client, provider_configured, test_engine, monkeypatch
    ):
        created = (await tools_client.post(TOOLS_URL, json=VALID_TOOL)).json()

        class Failing:
            async def evaluate(self, **kw):
                from app.services.system_one.client import SystemOneClientError

                raise SystemOneClientError("provider down")

        import app.services.system_one.decision_engine as engine_module

        monkeypatch.setattr(engine_module, "TypeSafeJevClient", lambda: Failing())

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        from app.services.system_one.decision_engine import DecisionExecutionEngine

        async with SessionLocal() as session:
            tool = (
                await session.execute(
                    select(DecisionTool)
                    .where(DecisionTool.id == uuid.UUID(created["id"]))
                    .options(selectinload(DecisionTool.questions))
                )
            ).scalar_one()
            result = await DecisionExecutionEngine().execute(
                db=session, tool=tool, input_state={"amount": 1, "agent_data": {"customer_history": "x"}},
                tenant_id=tool.tenant_id,
            )
            await session.commit()
            assert result.status.value == "failed"
            assert result.outcome.value == "escalate"
            assert "provider down" in result.error_message
            assert result.answers is None


# ── Permission enforcement ────────────────────────────────────────────────


@pytest.mark.asyncio
class TestPermissions:
    async def test_routes_denied_without_permission(self, no_permission_client):
        for method, url, kwargs in [
            ("get", TOOLS_URL, {}),
            ("post", TOOLS_URL, {"json": VALID_TOOL}),
            ("get", RESULTS_URL, {}),
        ]:
            resp = await getattr(no_permission_client, method)(url, **kwargs)
            assert resp.status_code in (401, 403), (method, url, resp.status_code)


# ── Skills binding decision tools (virtual tool ids) ──────────────────────


def _virtual_id(decision_tool_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"decision-tool:{uuid.UUID(decision_tool_id)}"))


SKILL_PAYLOAD = {
    "description": "Triage loan applications",
    "instructions": "Evaluate the application with the bound tool.",
}


def _skill_payload() -> dict:
    """Unique skill name per test — skills.name is unique in the schema."""
    return {**SKILL_PAYLOAD, "name": f"loan-triage-{uuid.uuid4().hex[:8]}"}


@pytest.mark.asyncio
class TestSkillDecisionBindings:
    async def test_create_skill_with_decision_binding_succeeds(
        self, tools_client, skills_client, provider_configured
    ):
        created = (await tools_client.post(TOOLS_URL, json=VALID_TOOL)).json()
        payload = {
            **_skill_payload(),
            "tool_ids": [_virtual_id(created["id"])],
        }
        resp = await skills_client.post(SKILLS_URL, json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["tool_ids"] == [str(_virtual_id(created["id"]))]

        # Skill detail renders the binding as the canonical decision____ name
        detail = await skills_client.get(f"{SKILLS_URL}/{body['id']}")
        assert detail.status_code == 200
        assert "decision____approve_loan" in detail.json()["instructions_with_tools"]

    async def test_update_skill_with_decision_binding_succeeds(
        self, tools_client, skills_client, provider_configured
    ):
        created = (await tools_client.post(TOOLS_URL, json=VALID_TOOL)).json()
        skill = (
            await skills_client.post(SKILLS_URL, json={**_skill_payload(), "tool_ids": []})
        ).json()
        resp = await skills_client.put(
            f"{SKILLS_URL}/{skill['id']}",
            json={"tool_ids": [_virtual_id(created["id"])]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["tool_ids"] == [str(_virtual_id(created["id"]))]

    async def test_foreign_tenant_decision_binding_422(
        self, tools_client, skills_client, provider_configured
    ):
        created = (
            await tools_client.post(
                TOOLS_URL, json=VALID_TOOL, headers={"x-test-tenant": str(TENANT_A)}
            )
        ).json()
        resp = await skills_client.post(
            SKILLS_URL, json={**_skill_payload(), "tool_ids": [_virtual_id(created["id"])]}
        )
        assert resp.status_code == 422
        assert "not found" in resp.json()["detail"]

    async def test_disabled_decision_binding_422(
        self, tools_client, skills_client, provider_configured
    ):
        created = (await tools_client.post(TOOLS_URL, json=VALID_TOOL)).json()
        await tools_client.put(
            f"{TOOLS_URL}/{created['id']}", json={"enabled": False}
        )
        resp = await skills_client.post(
            SKILLS_URL, json={**_skill_payload(), "tool_ids": [_virtual_id(created["id"])]}
        )
        assert resp.status_code == 422

    async def test_executor_executes_decision_binding_via_decision_path(
        self, tools_client, skills_client, provider_configured, test_engine, monkeypatch
    ):
        created = (await tools_client.post(TOOLS_URL, json=VALID_TOOL)).json()
        skill = (
            await skills_client.post(
                SKILLS_URL,
                json={**_skill_payload(), "tool_ids": [_virtual_id(created["id"])]},
            )
        ).json()

        fake = FakeTransport()
        import app.services.system_one.decision_engine as engine_module

        monkeypatch.setattr(engine_module, "TypeSafeJevClient", lambda: fake)

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        from app.services.skills.executor import SkillExecutor

        async with SessionLocal() as session:
            results = await SkillExecutor().execute(
                uuid.UUID(skill["id"]),
                {"amount": 5000, "agent_data": {"customer_history": "clean"}},
                session,
            )
            await session.commit()

        assert len(results) == 1
        entry = results[0]
        assert entry["tool"] == "decision____approve_loan"
        assert entry["error"] is None
        assert entry["result"]["tool_name"] == "approve_loan"
        assert entry["result"]["answers"]["approve"]["choice"] == "yes"
        assert entry["result"]["outcome"] == "confirm"
        # executed through the real decision engine (single provider dispatch)
        assert len(fake.calls) == 1

    async def test_executor_other_tenant_decision_binding_raises(
        self, tools_client, provider_configured, test_engine
    ):
        """A binding id that resolves in NO tenant raises SkillExecutionError."""
        from app.services.skills.executor import SkillExecutionError, SkillExecutor

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as session:
            skill = Skill(name="orphan-skill", instructions="i")
            session.add(skill)
            await session.flush()
            session.add(
                SkillToolBinding(
                    skill_id=skill.id,
                    tool_id=uuid.uuid5(uuid.NAMESPACE_URL, "decision-tool:none"),
                    order=0,
                )
            )
            await session.commit()
            skill_id = skill.id

        async with SessionLocal() as session:
            with pytest.raises(SkillExecutionError, match="not found"):
                await SkillExecutor().execute(skill_id, {}, session)
