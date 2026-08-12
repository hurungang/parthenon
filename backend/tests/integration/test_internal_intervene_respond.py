"""Integration tests: Internal intervene respond endpoint.

Tests cover:
- POST /api/v1/internal/data/intervene/respond — approval, choice, text responses
- Error cases: 404 not found, 400 already responded, 401/403 without service cert
- Agent session resume: status transitions from waiting_for_human to running
- Persistence: InterveneResponse fields are stored correctly
"""
from __future__ import annotations

import os
import uuid
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.api.deps import require_service_certificate
from app.db.models.agents import (
    AgentInputType,
    AgentJob,
    AgentJobStatus,
    AgentOutputType,
    AgentType,
)
from app.db.models.identity import Identity
from app.db.models.intervene import (
    InterveneRequest,
    InterveneRequestStatus,
    InterventionType,
)
from app.db.models.platform_user import PlatformUser
from app.db.session import Base, get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware
from app.services.agents.intervene_service import InterveneRequestStore
from sqlalchemy.dialects.postgresql import UUID as _PG_UUID

# ── SQLite + UUID compatibility ──────────────────────────────────────────────

_orig_pg_uuid_result_processor = _PG_UUID.result_processor


def _sqlite_tolerant_uuid_result_processor(self, dialect, coltype):
    orig_proc = _orig_pg_uuid_result_processor(self, dialect, coltype)
    if dialect.name != "sqlite" or orig_proc is None:
        return orig_proc

    def proc(value: object) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, int):
            return uuid.UUID(int=value)
        return orig_proc(value)

    return proc


_PG_UUID.result_processor = _sqlite_tolerant_uuid_result_processor

_INTEGRATION_URL = "sqlite+aiosqlite:///:memory:"


# ── Auth bypass helpers ─────────────────────────────────────────────────────

def _bypass_jwt():
    """Patch JWTAuthMiddleware so internal endpoints need no JWT token."""
    async def _patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "test-internal", "roles": ["admin"]}
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", _patched_dispatch)


def _bypass_service_cert():
    """Override require_service_certificate to return a fake service identity."""
    def _dep():
        return {"cert_type": "service", "service_name": "test-service"}
    return _dep


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="module")
async def test_engine():
    """Session-scoped StaticPool engine — shared in-memory SQLite."""
    engine = create_async_engine(
        _INTEGRATION_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        use_insertmanyvalues=False,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Function-scoped DB session bound to the shared StaticPool engine."""
    SessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    async with SessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def internal_client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """HTTP test client with service-cert auth bypassed for /internal endpoints.

    - JWTAuthMiddleware is patched defensively (internal paths are already JWT-exempt).
    - require_service_certificate dependency is overridden to skip CA validation.
    """
    SessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_service_certificate] = _bypass_service_cert()

    with _bypass_jwt():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _create_test_data(
    db: AsyncSession,
    intervention_type: InterventionType = InterventionType.approval,
    choices: list[str] | None = None,
) -> dict:
    """Create minimal seed data needed for the internal intervene respond flow.

    Returns a dict with keys: platform_user, identity, agent_type, agent_job, intervene_request.
    """
    # Create a PlatformUser
    platform_user = PlatformUser(
        id=uuid.uuid4(),
        sub=f"test-internal-user-{uuid.uuid4().hex}",
        email="test-internal@example.com",
        display_name="Test Internal User",
    )
    db.add(platform_user)
    await db.flush()

    # Create an Identity with matching subject (different ID from PlatformUser)
    identity = Identity(
        id=uuid.uuid4(),
        subject=platform_user.sub,
        display_name=platform_user.display_name,
    )
    db.add(identity)
    await db.flush()

    # Create an AgentType
    agent_type = AgentType(
        name=f"Internal-Test-Agent-{uuid.uuid4().hex[:8]}",
        input_type=AgentInputType.conversation,
        output_type=AgentOutputType.auto,
    )
    db.add(agent_type)
    await db.flush()

    # Create an AgentJob in waiting_for_human status
    agent_job = AgentJob(
        id=uuid.uuid4(),
        agent_type_id=agent_type.id,
        status=AgentJobStatus.waiting_for_human,
        triggered_by_user_id=identity.id,
    )
    db.add(agent_job)
    await db.flush()

    # Create an InterveneRequest
    store = InterveneRequestStore()
    intervene_request = await store.create_request(
        db=db,
        agent_session_id=agent_job.id,
        agent_type_id=agent_type.id,
        intervention_type=intervention_type,
        reason=f"Test {intervention_type.value} request",
        choices=choices,
    )
    await db.commit()

    return {
        "platform_user": platform_user,
        "identity": identity,
        "agent_type": agent_type,
        "agent_job": agent_job,
        "intervene_request": intervene_request,
    }


# ── Test: Successful approval response ────────────────────────────────────────

class TestInternalRespondApproval:

    @pytest.mark.asyncio
    async def test_internal_respond_approval(
        self, db_session: AsyncSession, internal_client: AsyncClient
    ):
        """Submit an approval response via the internal respond endpoint.

        Verifies:
        - Returns 200 with valid response data
        - InterveneRequest status is 'responded'
        - Response has approval_value=True
        - Agent session is resumed (status transitions from waiting_for_human to running)
        """
        data = await _create_test_data(db_session, InterventionType.approval)
        req = data["intervene_request"]
        agent_job = data["agent_job"]

        response = await internal_client.post(
            "/api/v1/internal/data/intervene/respond",
            json={"request_id": str(req.id), "approval_value": True},
        )
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        body = response.json()
        assert body["request_id"] == str(req.id)
        assert body["approval_value"] is True
        assert "id" in body
        assert "responded_at" in body

        # Verify InterveneRequest status is responded
        await db_session.refresh(req)
        assert req.status == InterveneRequestStatus.responded, (
            f"Expected responded, got {req.status}"
        )

        # Verify AgentJob status transitioned to running
        await db_session.refresh(agent_job)
        assert agent_job.status == AgentJobStatus.running, (
            f"Expected running, got {agent_job.status}"
        )


# ── Test: Successful choice response ──────────────────────────────────────────

class TestInternalRespondChoice:

    @pytest.mark.asyncio
    async def test_internal_respond_choice(
        self, db_session: AsyncSession, internal_client: AsyncClient
    ):
        """Submit a choice response via the internal respond endpoint.

        Verifies:
        - Returns 200 with valid response data
        - selected_choice is persisted correctly
        - InterveneRequest status is 'responded'
        """
        data = await _create_test_data(
            db_session,
            InterventionType.choice,
            choices=["Option A", "Option B"],
        )
        req = data["intervene_request"]

        response = await internal_client.post(
            "/api/v1/internal/data/intervene/respond",
            json={"request_id": str(req.id), "selected_choice": "Option A"},
        )
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        body = response.json()
        assert body["request_id"] == str(req.id)
        assert body["selected_choice"] == "Option A"
        assert "id" in body

        await db_session.refresh(req)
        assert req.status == InterveneRequestStatus.responded


# ── Test: Successful text response ────────────────────────────────────────────

class TestInternalRespondText:

    @pytest.mark.asyncio
    async def test_internal_respond_text(
        self, db_session: AsyncSession, internal_client: AsyncClient
    ):
        """Submit a text response via the internal respond endpoint.

        Verifies:
        - Returns 200 with valid response data
        - text_value is persisted correctly
        - InterveneRequest status is 'responded'
        """
        data = await _create_test_data(db_session, InterventionType.text)
        req = data["intervene_request"]

        response = await internal_client.post(
            "/api/v1/internal/data/intervene/respond",
            json={"request_id": str(req.id), "text_value": "This is a test text response"},
        )
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        body = response.json()
        assert body["request_id"] == str(req.id)
        assert body["text_value"] == "This is a test text response"
        assert "id" in body

        await db_session.refresh(req)
        assert req.status == InterveneRequestStatus.responded


# ── Test: 404 for non-existent request ────────────────────────────────────────

class TestInternalRespondNotFound:

    @pytest.mark.asyncio
    async def test_internal_respond_not_found(self, internal_client: AsyncClient):
        """Submit response with a non-existent request ID. Expect 404."""
        fake_id = uuid.uuid4()
        response = await internal_client.post(
            "/api/v1/internal/data/intervene/respond",
            json={"request_id": str(fake_id), "approval_value": True},
        )
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text}"
        )


# ── Test: 400 for already-responded request ───────────────────────────────────

class TestInternalRespondAlreadyResponded:

    @pytest.mark.asyncio
    async def test_internal_respond_already_responded(
        self, db_session: AsyncSession, internal_client: AsyncClient
    ):
        """Submit response twice — first should succeed, second should return 400."""
        data = await _create_test_data(db_session, InterventionType.approval)
        req = data["intervene_request"]

        # First response — should succeed
        response1 = await internal_client.post(
            "/api/v1/internal/data/intervene/respond",
            json={"request_id": str(req.id), "approval_value": True},
        )
        assert response1.status_code == 200, (
            f"First response: expected 200, got {response1.status_code}: {response1.text}"
        )

        # Second response — should fail with 400
        response2 = await internal_client.post(
            "/api/v1/internal/data/intervene/respond",
            json={"request_id": str(req.id), "approval_value": False},
        )
        assert response2.status_code == 400, (
            f"Second response: expected 400, got {response2.status_code}: {response2.text}"
        )
        assert "responded" in response2.text.lower()


# ── Test: Operator resolved via subject when triggered_by_user_id is None ───────

class TestInternalRespondViaSubject:

    @pytest.mark.asyncio
    async def test_internal_respond_via_operator_subject(
        self, db_session: AsyncSession, internal_client: AsyncClient
    ):
        """Submit response when AgentJob has no triggered_by_user_id.

        This simulates a delegated sub-agent scenario where the agent session
        has no direct user association. The operator is resolved via the
        operator_subject field matching an Identity record.
        """
        # Create test data, then clear triggered_by_user_id to simulate delegation
        data = await _create_test_data(db_session, InterventionType.approval)
        req = data["intervene_request"]
        agent_job = data["agent_job"]
        identity = data["identity"]

        # Clear triggered_by_user_id — delegated agents have none
        agent_job.triggered_by_user_id = None
        await db_session.commit()
        await db_session.refresh(agent_job)

        response = await internal_client.post(
            "/api/v1/internal/data/intervene/respond",
            json={
                "request_id": str(req.id),
                "approval_value": True,
                "operator_subject": identity.subject,
            },
        )
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        body = response.json()
        assert body["request_id"] == str(req.id)
        assert body["approval_value"] is True
        # 200 means operator was resolved — the endpoint blocks requests
        # where the operator can't be determined

    @pytest.mark.asyncio
    async def test_internal_respond_via_operator_subject_not_found(
        self, db_session: AsyncSession, internal_client: AsyncClient
    ):
        """Submit response with a non-existent operator_subject.

        Should return 400 because the subject can't be resolved.
        """
        data = await _create_test_data(db_session, InterventionType.approval)
        req = data["intervene_request"]
        agent_job = data["agent_job"]

        # Clear triggered_by_user_id — delegated agents have none
        agent_job.triggered_by_user_id = None
        await db_session.commit()

        response = await internal_client.post(
            "/api/v1/internal/data/intervene/respond",
            json={
                "request_id": str(req.id),
                "approval_value": True,
                "operator_subject": "non-existent-subject",
            },
        )
        assert response.status_code == 400, (
            f"Expected 400, got {response.status_code}: {response.text}"
        )
        assert "Cannot determine operator" in response.text

class TestInternalRespondRequiresServiceCert:

    @pytest.mark.asyncio
    async def test_internal_respond_requires_service_cert(
        self, db_session: AsyncSession, test_engine
    ):
        """Call the internal respond endpoint WITHOUT a service certificate.

        The internal /api/v1/internal/ path is JWT-exempt but requires
        require_service_certificate.  Without a valid X-Client-Certificate
        header, the endpoint must return 401 (unauthorized) — and NOT 200.
        """
        SessionLocal = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
            async with SessionLocal() as session:
                yield session

        app = create_app()
        app.dependency_overrides[get_db] = override_get_db
        # Deliberately do NOT override require_service_certificate

        data = await _create_test_data(db_session, InterventionType.approval)
        req = data["intervene_request"]

        # /api/v1/internal/* paths are JWT-exempt in JWTAuthMiddleware,
        # so we don't need JWT bypass — just an ASGI transport client.
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/internal/data/intervene/respond",
                json={"request_id": str(req.id), "approval_value": True},
            )

        # Without an X-Client-Certificate header, require_service_certificate
        # raises HTTPException(401).  Accept either 401 or 403.
        assert response.status_code in (401, 403), (
            f"Expected 401 or 403 without service cert, "
            f"got {response.status_code}: {response.text}"
        )
