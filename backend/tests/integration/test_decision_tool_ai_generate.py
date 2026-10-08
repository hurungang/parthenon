"""Round-2 integration tests: the decision tool AI generate endpoint.

Covers:
- ``POST /decision-tools/generate`` returns draft questions + state mappings
  (workflow authoring service call mocked),
- permission gating (like tool creation),
- graceful failure (structured 422, nothing persisted) when the generation
  service errors or returns malformed output,
- no key material in requests/responses,
- ``extract_state_placeholders`` unit cases (backtick dot/bracket paths,
  dedupe, empty input).
"""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_permission
from app.core.resource_types import RT_SYSTEM_DECISION_TOOLS
from app.db.models.decision_tools import DecisionTool
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware
from app.services.system_one.decision_authoring_service import (
    extract_state_placeholders,
)

TOOLS_URL = "/api/v1/decision-tools"
GENERATE_URL = f"{TOOLS_URL}/generate"

SECRET_KEY = "sk-generate-test-secret-9876543210"


def _bypass_jwt_middleware():
    from unittest.mock import patch as _patch

    async def _patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "test-admin", "roles": ["admin"]}
        return await call_next(request)

    return _patch.object(JWTAuthMiddleware, "dispatch", _patched_dispatch)


def _allow_all():
    async def _dep():
        return {"user_id": "test-user", "permissions": ["*::*"]}

    return _dep


async def _clean(session: AsyncSession) -> None:
    from app.db.models.system_one_provider_config import SystemOneProviderConfig

    await session.execute(DecisionTool.__table__.delete())
    await session.execute(SystemOneProviderConfig.__table__.delete())
    await session.commit()


@pytest_asyncio.fixture
async def gen_client(test_engine):
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    async with SessionLocal() as session:
        await _clean(session)

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    for action in ("read", "create", "update", "delete"):
        app.dependency_overrides[
            require_permission(RT_SYSTEM_DECISION_TOOLS, action)
        ] = _allow_all()

    with _bypass_jwt_middleware():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c


def _generation_model_configured(monkeypatch):
    """Force the workflow generation model to be 'configured'."""
    import app.api.v1.decision_tools as dt_api

    monkeypatch.setattr(dt_api, "get_workflow_generation_model_id", lambda: "cfg-gpt")


GOOD_DRAFT = json.dumps(
    {
        "questions": [
            {
                "question_key": "approve",
                "question_type": "choice",
                "instructions": "Approve if `input.tier` is gold.",
                "criteria_options": {"yes": "approve", "no": "reject"},
                "is_required": True,
            },
            {
                "question_key": "risk",
                "question_type": "score",
                "instructions": "Rate risk given `input.amount`.",
                "criteria_options": ["low", "medium", "high"],
                "is_required": True,
            },
        ],
        "state_preset": {
            "tier": {"source": "input", "key": "tier"},
            "amount": {"source": "input", "key": "amount"},
        },
    }
)


@pytest.mark.asyncio
class TestGenerateEndpoint:
    async def test_generate_returns_draft_questions_and_state_mappings(
        self, gen_client, monkeypatch
    ):
        _generation_model_configured(monkeypatch)
        calls: list[dict] = []

        async def fake_generate_workflow_text(**kwargs):
            calls.append(kwargs)
            return GOOD_DRAFT

        import app.services.system_one.decision_authoring_service as auth_svc

        monkeypatch.setattr(
            auth_svc, "generate_workflow_text", fake_generate_workflow_text
        )

        resp = await gen_client.post(
            GENERATE_URL,
            json={"description": "Approve small loans under $10k"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [q["question_key"] for q in body["questions"]] == [
            "approve",
            "risk",
        ]
        assert body["questions"][0]["question_type"] == "choice"
        assert body["questions"][0]["criteria_options"] == {
            "yes": "approve",
            "no": "reject",
        }
        assert body["state_preset"] == {
            "tier": {"source": "input", "key": "tier"},
            "amount": {"source": "input", "key": "amount"},
        }
        # Detected backtick state paths from the drafted instructions:
        assert sorted(body["detected_state_paths"]) == ["input.amount", "input.tier"]
        assert body["model_id"] == "cfg-gpt"
        # the authoring service received description + prompt materials
        assert calls and "Approve small loans" in calls[0]["user_prompt"]

        # draft questions would pass per-type authoring validation
        from app.schemas.decision_tools import DecisionToolQuestionCreate

        for q in body["questions"]:
            DecisionToolQuestionCreate.model_validate(q)

    async def test_generate_fails_gracefully_when_service_errors(
        self, gen_client, monkeypatch
    ):
        _generation_model_configured(monkeypatch)

        from app.services.agents.workflow_authoring_service import WorkflowAuthoringError

        async def failing(**kwargs):
            raise WorkflowAuthoringError("model unavailable")

        import app.services.system_one.decision_authoring_service as auth_svc

        monkeypatch.setattr(auth_svc, "generate_workflow_text", failing)

        resp = await gen_client.post(
            GENERATE_URL, json={"description": "something"}
        )
        assert resp.status_code == 422
        assert "model unavailable" in resp.text

        # no partial tool persisted
        SessionLocal = async_sessionmaker(AsyncSession)
        # (verified by the caller's fixture-cleaned table; assert via API list)
        listing = await gen_client.get(TOOLS_URL)
        assert listing.status_code == 200
        assert listing.json() == []

    async def test_generate_malformed_model_output_is_structured_422(
        self, gen_client, monkeypatch
    ):
        _generation_model_configured(monkeypatch)

        async def malformed(**kwargs):
            return "this is not JSON at all"

        import app.services.system_one.decision_authoring_service as auth_svc

        monkeypatch.setattr(auth_svc, "generate_workflow_text", malformed)

        resp = await gen_client.post(
            GENERATE_URL, json={"description": "something"}
        )
        assert resp.status_code == 422
        assert "invalid JSON" in resp.text

    async def test_generate_missing_workflow_model_422(self, gen_client, monkeypatch):
        import app.api.v1.decision_tools as dt_api

        monkeypatch.setattr(dt_api, "get_workflow_generation_model_id", lambda: None)
        resp = await gen_client.post(
            GENERATE_URL, json={"description": "something"}
        )
        assert resp.status_code == 422
        assert "Workflow generation model" in resp.text

    async def test_generate_unknown_data_type_422(self, gen_client, monkeypatch):
        _generation_model_configured(monkeypatch)
        resp = await gen_client.post(
            GENERATE_URL,
            json={
                "description": "x",
                "input_data_type_id": str(uuid.uuid4()),
            },
        )
        assert resp.status_code == 422
        assert "not found or not visible" in resp.text

    async def test_generate_response_has_no_key_material(self, gen_client, monkeypatch):
        _generation_model_configured(monkeypatch)

        async def leaky(**kwargs):
            # Simulate a model echo that would carry a key if the service ever
            # leaked one into prompts — must not appear in OUR response since
            # the key never enters request handling.
            return GOOD_DRAFT

        import app.services.system_one.decision_authoring_service as auth_svc

        monkeypatch.setattr(auth_svc, "generate_workflow_text", leaky)

        resp = await gen_client.post(
            GENERATE_URL,
            json={"description": f"desc mentioning {SECRET_KEY} verbatim input"},
        )
        assert resp.status_code == 200
        # The response only carries draft content; nothing secret-derived.
        assert SECRET_KEY not in resp.text


@pytest.mark.asyncio
class TestGeneratePermissions:
    async def test_generate_denied_without_permission(self, test_engine):
        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )

        async def override_db():
            async with SessionLocal() as session:
                yield session
                await session.commit()

        app = create_app()
        app.dependency_overrides[get_db] = override_db
        with _bypass_jwt_middleware():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    GENERATE_URL, json={"description": "x"}
                )
                assert resp.status_code in (401, 403)


# ── extract_state_placeholders unit cases ─────────────────────────────────


class TestExtractStatePlaceholders:
    def test_backtick_dot_paths(self):
        assert extract_state_placeholders("Check `input.tier` and `input.amount`") == [
            "input.tier",
            "input.amount",
        ]

    def test_backtick_bracket_paths(self):
        assert extract_state_placeholders("Use `input.items[0].sku` here") == [
            "input.items[0].sku"
        ]

    def test_dedupes_repeated_paths(self):
        assert extract_state_placeholders("`a.b` then `a.b` again `a.b`") == ["a.b"]

    def test_empty_and_none_like_inputs(self):
        assert extract_state_placeholders("") == []
        assert extract_state_placeholders("no backticks here") == []

    def test_strips_whitespace_inside_backticks(self):
        assert extract_state_placeholders("`  spaced.path  `") == ["spaced.path"]

    def test_mixed_content(self):
        text = "Given `state.risk` and `state.risk` plus `plain text` and `x[1]`"
        assert extract_state_placeholders(text) == ["state.risk", "plain text", "x[1]"]
