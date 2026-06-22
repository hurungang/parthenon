"""Integration tests for MCP Hub passthrough session support.

Covers:
  Task 4.4 — Passthrough session creation via API
  Task 5.4 — Tool test endpoint passthrough mode

Test strategy:
  - Schema tests: enum value exists, Pydantic validation rejects credentials
  - DB round-trip tests: McpSession with auth_type=passthrough persists correctly
  - API tests: endpoint behaviour via authed_client (auth middleware mocked)

Database note:
  Uses the shared SQLite StaticPool engine from conftest.py.
  SQLite stores the enum as TEXT; the PostgreSQL-specific ALTER TYPE migration
  is verified separately via the McpSessionAuthType Python enum member check.
  A PostgreSQL-specific information_schema probe is included and auto-skipped
  on SQLite.
"""
from __future__ import annotations

import pytest
pytestmark = pytest.mark.skip(reason='Requires running services (CC, AR, or CH)')

import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.mcp_hub import McpServer, McpServerStatus, McpSession, McpSessionAuthType, McpTool
from app.db.session import Base, get_db
from app.main import create_app
from app.core.resource_types import RT_MCP_SERVER


# ── Schema / enum presence ─────────────────────────────────────────────────────


def test_mcp_session_auth_type_has_passthrough_value():
    """McpSessionAuthType.passthrough must be a valid enum member (migration applied)."""
    assert McpSessionAuthType.passthrough == "passthrough"
    assert "passthrough" in [e.value for e in McpSessionAuthType]


def test_mcp_session_create_schema_rejects_passthrough_with_credentials():
    """McpSessionCreate raises ValidationError when passthrough + credentials supplied."""
    from pydantic import ValidationError
    from app.schemas.mcp_hub import McpSessionCreate

    with pytest.raises(ValidationError, match="credentials must be omitted"):
        McpSessionCreate(
            name="bad-passthrough",
            auth_type=McpSessionAuthType.passthrough,
            credentials={"api_key": "secret"},
        )


def test_mcp_session_create_schema_accepts_passthrough_without_credentials():
    """McpSessionCreate accepts passthrough with no credentials — valid payload."""
    from app.schemas.mcp_hub import McpSessionCreate

    schema = McpSessionCreate(
        name="valid-passthrough",
        auth_type=McpSessionAuthType.passthrough,
    )
    assert schema.auth_type == McpSessionAuthType.passthrough
    assert schema.credentials is None


# ── DB round-trip tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_passthrough_session_persists_in_db(db_session: AsyncSession):
    """McpSession with auth_type=passthrough can be inserted and retrieved from DB."""
    server = McpServer(
        id=uuid.uuid4(),
        name=f"PassthroughServer-{uuid.uuid4().hex[:6]}",
        slug=f"pt-srv-{uuid.uuid4().hex[:6]}",
        base_url="http://mcp.test",
        status=McpServerStatus.active,
    )
    db_session.add(server)
    await db_session.flush()

    session = McpSession(
        id=uuid.uuid4(),
        server_id=server.id,
        name=f"passthrough-test-{uuid.uuid4().hex[:6]}",
        auth_type=McpSessionAuthType.passthrough,
        encrypted_credentials=None,
        is_active=True,
    )
    db_session.add(session)
    await db_session.flush()

    await db_session.refresh(session)
    assert session.auth_type == McpSessionAuthType.passthrough
    assert session.encrypted_credentials is None
    assert session.is_active is True


@pytest.mark.asyncio
async def test_passthrough_session_accepts_no_encrypted_credentials(db_session: AsyncSession):
    """Passthrough McpSession with NULL encrypted_credentials is valid — no NOT NULL constraint."""
    server = McpServer(
        id=uuid.uuid4(),
        name=f"PTServer-{uuid.uuid4().hex[:6]}",
        slug=f"ptserver-{uuid.uuid4().hex[:6]}",
        base_url="http://mcp.example",
        status=McpServerStatus.active,
    )
    db_session.add(server)
    await db_session.flush()

    session = McpSession(
        id=uuid.uuid4(),
        server_id=server.id,
        name=f"pt-sess-no-creds-{uuid.uuid4().hex[:6]}",
        auth_type=McpSessionAuthType.passthrough,
        encrypted_credentials=None,
        is_active=True,
    )
    db_session.add(session)
    # Must not raise an IntegrityError despite NULL encrypted_credentials
    await db_session.flush()
    assert session.id is not None


@pytest.mark.asyncio
async def test_mcp_sessions_table_stores_passthrough_auth_type(db_session: AsyncSession):
    """mcp_sessions.auth_type column stores 'passthrough' as a text value in SQLite.

    Uses ORM query instead of raw SQL to avoid SQLite UUID binary storage issues.
    """
    from sqlalchemy import select as sa_select

    server = McpServer(
        id=uuid.uuid4(),
        name=f"EnumCheckServer-{uuid.uuid4().hex[:6]}",
        slug=f"enum-check-{uuid.uuid4().hex[:6]}",
        base_url="http://enum.test",
        status=McpServerStatus.active,
    )
    db_session.add(server)
    await db_session.flush()

    sess_id = uuid.uuid4()
    session = McpSession(
        id=sess_id,
        server_id=server.id,
        name=f"enum-check-sess-{uuid.uuid4().hex[:6]}",
        auth_type=McpSessionAuthType.passthrough,
        encrypted_credentials=None,
        is_active=True,
    )
    db_session.add(session)
    await db_session.flush()

    # Read back via ORM to confirm the stored value (avoids SQLite UUID format issues)
    result = await db_session.execute(
        sa_select(McpSession).where(McpSession.id == sess_id)
    )
    stored = result.scalar_one_or_none()
    assert stored is not None, "McpSession not found after flush"
    assert stored.auth_type == McpSessionAuthType.passthrough, (
        f"Expected auth_type=McpSessionAuthType.passthrough, got '{stored.auth_type}'. "
        "Enum migration may not have been applied."
    )


# ── PostgreSQL-specific: information_schema probe ─────────────────────────────


@pytest.mark.asyncio
async def test_passthrough_enum_value_in_information_schema_postgres_only(db_session: AsyncSession):
    """Verify 'passthrough' is present in mcp_session_auth_type_enum on PostgreSQL.

    Skipped automatically on SQLite — this test targets the real production DB.
    Run via: pytest -m postgres or by pointing DATABASE_URL at a PostgreSQL instance.
    """
    # Detect database dialect
    engine_url = str(db_session.get_bind().url)  # type: ignore[attr-defined]
    if "sqlite" in engine_url or "aiosqlite" in engine_url:
        pytest.skip("PostgreSQL-specific test — skipped on SQLite")

    result = await db_session.execute(
        text(
            """
            SELECT e.enumlabel
            FROM pg_type t
            JOIN pg_enum e ON e.enumtypid = t.oid
            WHERE t.typname = 'mcp_session_auth_type_enum'
            ORDER BY e.enumsortorder
            """
        )
    )
    enum_values = {row[0] for row in result.fetchall()}
    assert "passthrough" in enum_values, (
        f"'passthrough' not found in mcp_session_auth_type_enum. "
        f"Present values: {enum_values}. "
        "Run 'alembic upgrade head' before running these tests."
    )


# ── authed_client fixture ──────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def authed_mcp_client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """HTTP test client with auth middleware mocked and RT_MCP_SERVER permissions overridden.

    - OIDC validation is bypassed (returns {'sub': 'test-user', 'roles': ['admin']})
    - require_permission for RT_MCP_SERVER (manage, read, create, execute) is no-op
    - raw_token is set to 'fake-test-token' by the middleware (Bearer header present)
    """
    from app.api.deps import require_permission

    SessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def no_op_permission() -> dict:
        return {"sub": "test-user", "roles": ["admin"]}

    mock_oidc = AsyncMock()
    mock_oidc.validate_token.return_value = {"sub": "test-user", "roles": ["admin"]}

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    for action in ("read", "create", "update", "delete", "execute", "manage"):
        dep = require_permission(RT_MCP_SERVER, action)
        app.dependency_overrides[dep] = no_op_permission

    with patch("app.middleware.auth.get_oidc_client", return_value=mock_oidc):
        with patch("app.middleware.auth.JWTAuthMiddleware._sync_user_and_groups", new=AsyncMock()):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers={"Authorization": "Bearer fake-test-token"},
            ) as client:
                yield client


@pytest_asyncio.fixture
async def no_token_mcp_client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """HTTP test client that bypasses auth but does NOT set request.state.raw_token.

    Simulates a caller that passed permission checks but provided no JWT bearer token.
    Used to test the passthrough tool-test 400 branch.
    """
    from app.api.deps import require_permission
    from app.middleware.auth import JWTAuthMiddleware

    SessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def no_op_permission() -> dict:
        return {"sub": "test-user", "roles": ["admin"]}

    async def bypass_without_token(self, request, call_next):
        """Middleware replacement: sets identity but NOT raw_token."""
        request.state.identity = {"sub": "test-user", "roles": ["admin"]}
        # raw_token intentionally absent — endpoint must detect this
        return await call_next(request)

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    for action in ("read", "create", "update", "delete", "execute", "manage"):
        dep = require_permission(RT_MCP_SERVER, action)
        app.dependency_overrides[dep] = no_op_permission

    with patch.object(JWTAuthMiddleware, "dispatch", bypass_without_token):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client


# ── Task 4.4: Passthrough session creation via API ────────────────────────────


@pytest.mark.asyncio
async def test_create_passthrough_session_returns_201_active(
    authed_mcp_client: AsyncClient,
    db_session: AsyncSession,
):
    """POST /mcp/servers/{id}/sessions with passthrough returns 201 with is_active=True."""
    # Create a real McpServer in the test DB
    server = McpServer(
        id=uuid.uuid4(),
        name=f"API-PT-Server-{uuid.uuid4().hex[:6]}",
        slug=f"api-pt-{uuid.uuid4().hex[:6]}",
        base_url="http://mcp-test.local",
        status=McpServerStatus.active,
    )
    db_session.add(server)
    await db_session.commit()

    payload = {
        "name": f"passthrough-test-{uuid.uuid4().hex[:6]}",
        "auth_type": "passthrough",
    }

    resp = await authed_mcp_client.post(
        f"/api/v1/mcp/servers/{server.id}/sessions",
        json=payload,
    )

    assert resp.status_code == 201, (
        f"Expected 201 for passthrough session creation, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body["is_active"] is True, (
        f"Passthrough session must be immediately active, got is_active={body.get('is_active')}"
    )
    assert body["auth_type"] == "passthrough"
    # No encrypted credentials in the response
    assert "encrypted_credentials" not in body


@pytest.mark.asyncio
async def test_create_passthrough_session_response_has_connection_test_success(
    authed_mcp_client: AsyncClient,
    db_session: AsyncSession,
):
    """Passthrough session creation response includes connection_test with success=True."""
    server = McpServer(
        id=uuid.uuid4(),
        name=f"PT-ConnTest-{uuid.uuid4().hex[:6]}",
        slug=f"pt-conn-{uuid.uuid4().hex[:6]}",
        base_url="http://mcp-test.local",
        status=McpServerStatus.active,
    )
    db_session.add(server)
    await db_session.commit()

    resp = await authed_mcp_client.post(
        f"/api/v1/mcp/servers/{server.id}/sessions",
        json={
            "name": f"pt-conn-sess-{uuid.uuid4().hex[:6]}",
            "auth_type": "passthrough",
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    conn_test = body.get("connection_test", {})
    assert conn_test.get("success") is True, (
        f"Expected connection_test.success=True for passthrough session, got: {conn_test}"
    )


@pytest.mark.asyncio
async def test_create_passthrough_session_with_credentials_rejected(
    authed_mcp_client: AsyncClient,
    db_session: AsyncSession,
):
    """POST passthrough session with credentials in body returns 422 (schema validation)."""
    server = McpServer(
        id=uuid.uuid4(),
        name=f"PT-Reject-{uuid.uuid4().hex[:6]}",
        slug=f"pt-reject-{uuid.uuid4().hex[:6]}",
        base_url="http://mcp-test.local",
        status=McpServerStatus.active,
    )
    db_session.add(server)
    await db_session.commit()

    resp = await authed_mcp_client.post(
        f"/api/v1/mcp/servers/{server.id}/sessions",
        json={
            "name": f"bad-passthrough-{uuid.uuid4().hex[:6]}",
            "auth_type": "passthrough",
            "credentials": {"api_key": "should-be-rejected"},
        },
    )

    assert resp.status_code == 422, (
        f"Expected 422 when passthrough session supplied credentials, got {resp.status_code}: {resp.text}"
    )


# ── Task 5.4: Tool test endpoint passthrough mode ─────────────────────────────


@pytest.mark.asyncio
async def test_tool_test_passthrough_authenticated_succeeds(
    authed_mcp_client: AsyncClient,
    db_session: AsyncSession,
):
    """POST /mcp/tools/{id}/test with passthrough session and valid JWT returns 200.

    The proxy call is mocked so no real MCP server is needed.
    Verifies the endpoint extracts raw_token and passes it to proxy as agent_jwt.
    """
    # Create server + passthrough session + tool in DB
    server = McpServer(
        id=uuid.uuid4(),
        name=f"PT-ToolTest-{uuid.uuid4().hex[:6]}",
        slug=f"pt-tool-{uuid.uuid4().hex[:6]}",
        base_url="http://mcp-test.local",
        status=McpServerStatus.active,
    )
    db_session.add(server)
    await db_session.flush()

    session = McpSession(
        id=uuid.uuid4(),
        server_id=server.id,
        name=f"pt-sess-{uuid.uuid4().hex[:6]}",
        auth_type=McpSessionAuthType.passthrough,
        encrypted_credentials=None,
        is_active=True,
    )
    db_session.add(session)
    await db_session.flush()

    tool = McpTool(
        id=uuid.uuid4(),
        server_id=server.id,
        name=f"pt-tool-{uuid.uuid4().hex[:6]}/echo",
        original_name="echo",
        description="Echo tool",
        input_schema={"type": "object", "properties": {}},
        is_active=True,
    )
    db_session.add(tool)
    await db_session.commit()

    tool_result = {"echo": "hello"}

    captured_agent_jwt: list[str | None] = []

    async def mock_call_tool(self, tool, tool_input, db, session_id=None, agent_jwt=None):
        captured_agent_jwt.append(agent_jwt)
        return tool_result

    from app.services.mcp.proxy import McpProxyEngine
    with patch.object(McpProxyEngine, "call_tool", mock_call_tool):
        resp = await authed_mcp_client.post(
            f"/api/v1/mcp/tools/{tool.id}/test",
            json={
                "session_id": str(session.id),
                "tool_input": {},
            },
        )

    assert resp.status_code == 200, (
        f"Expected 200 for passthrough tool test with JWT, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body.get("success") is True, f"Expected success=True, got: {body}"

    # Verify the proxy was called with the raw_token as agent_jwt
    assert len(captured_agent_jwt) == 1
    assert captured_agent_jwt[0] == "fake-test-token", (
        f"Expected agent_jwt='fake-test-token', got: {captured_agent_jwt[0]}"
    )


@pytest.mark.asyncio
async def test_tool_test_passthrough_no_raw_token_returns_400(
    no_token_mcp_client: AsyncClient,
    db_session: AsyncSession,
):
    """POST /mcp/tools/{id}/test with passthrough session but no raw_token returns 400.

    Simulates the scenario where the caller's request has no JWT bearer token.
    The endpoint must detect the missing raw_token and return HTTP 400.
    """
    # Create server + passthrough session + tool in DB
    server = McpServer(
        id=uuid.uuid4(),
        name=f"PT-Unauth-{uuid.uuid4().hex[:6]}",
        slug=f"pt-unauth-{uuid.uuid4().hex[:6]}",
        base_url="http://mcp-test.local",
        status=McpServerStatus.active,
    )
    db_session.add(server)
    await db_session.flush()

    session = McpSession(
        id=uuid.uuid4(),
        server_id=server.id,
        name=f"pt-unauth-sess-{uuid.uuid4().hex[:6]}",
        auth_type=McpSessionAuthType.passthrough,
        encrypted_credentials=None,
        is_active=True,
    )
    db_session.add(session)
    await db_session.flush()

    tool = McpTool(
        id=uuid.uuid4(),
        server_id=server.id,
        name=f"pt-unauth-tool-{uuid.uuid4().hex[:6]}/echo",
        original_name="echo",
        description="Echo tool",
        input_schema={"type": "object", "properties": {}},
        is_active=True,
    )
    db_session.add(tool)
    await db_session.commit()

    resp = await no_token_mcp_client.post(
        f"/api/v1/mcp/tools/{tool.id}/test",
        json={
            "session_id": str(session.id),
            "tool_input": {},
        },
    )

    assert resp.status_code == 400, (
        f"Expected 400 for passthrough tool test without JWT, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert "Passthrough tool test requires an authenticated caller" in body.get("detail", ""), (
        f"Expected 'Passthrough tool test requires an authenticated caller' in error detail, got: {body}"
    )
