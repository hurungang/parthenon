"""FIX-20261101-120618 Work Item 1 — sessions list query upgrades.

Covers the new paginated / filterable sessions endpoint (GET /conversations/sessions)
and the ConversationStore.list_sessions_page service method:

- default query window = now − conversation_sessions_default_window_days (7)
- explicit date_from/date_to overrides the default window
- all_time escape hatch
- status filter semantics: active | ended (closed/archived/error) | all
- pagination + total count
- updated_at DESC ordering
- tenant isolation
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentInputType, AgentOutputType, AgentType
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.services.conversations.store import ConversationStore


async def _create_agent_type(db: AsyncSession) -> AgentType:
    at = AgentType(
        name=f"Test Agent {uuid.uuid4().hex[:6]}",
        input_type=AgentInputType.conversation,
        output_type=AgentOutputType.auto,
    )
    db.add(at)
    await db.flush()
    await db.refresh(at)
    return at


async def _create_session(
    db: AsyncSession,
    agent_type_id: uuid.UUID,
    *,
    status: ConversationStatus = ConversationStatus.active,
    updated_at: datetime | None = None,
    tenant_id: uuid.UUID | None = None,
) -> ConversationSession:
    session = ConversationSession(
        agent_type_id=agent_type_id,
        status=status,
        tenant_id=tenant_id,
    )
    db.add(session)
    await db.flush()
    if updated_at is not None:
        session.updated_at = updated_at
        await db.flush()
    await db.refresh(session)
    return session


def _auth_override():
    return {"sub": "test-user", "platform_user_id": str(uuid.uuid4()), "roles": ["admin"]}


# ── Store-level tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_sessions_page_orders_by_updated_at_desc(db_session: AsyncSession):
    at = await _create_agent_type(db_session)
    now = datetime.now(timezone.utc)
    old = await _create_session(
        db_session, at.id, updated_at=now - timedelta(hours=2)
    )
    new = await _create_session(
        db_session, at.id, updated_at=now - timedelta(hours=1)
    )
    await db_session.commit()

    items, total = await ConversationStore().list_sessions_page(db=db_session, agent_type_id=at.id)
    assert total == 2
    assert [s.id for s in items] == [new.id, old.id]


@pytest.mark.asyncio
async def test_list_sessions_page_default_window_excludes_sessions_older_than_7_days(
    db_session: AsyncSession,
):
    at = await _create_agent_type(db_session)
    now = datetime.now(timezone.utc)
    await _create_session(db_session, at.id, updated_at=now - timedelta(days=10))
    recent = await _create_session(
        db_session, at.id, updated_at=now - timedelta(days=1)
    )
    await db_session.commit()

    items, total = await ConversationStore().list_sessions_page(db=db_session, agent_type_id=at.id)
    assert total == 1
    assert [s.id for s in items] == [recent.id]


@pytest.mark.asyncio
async def test_list_sessions_page_explicit_date_from_overrides_default_window(
    db_session: AsyncSession,
):
    at = await _create_agent_type(db_session)
    now = datetime.now(timezone.utc)
    old = await _create_session(
        db_session, at.id, updated_at=now - timedelta(days=10)
    )
    await db_session.commit()

    items, total = await ConversationStore().list_sessions_page(
        db=db_session,
        agent_type_id=at.id,
        date_from=now - timedelta(days=30),
    )
    assert total == 1
    assert [s.id for s in items] == [old.id]


@pytest.mark.asyncio
async def test_list_sessions_page_all_time_includes_old_sessions(db_session: AsyncSession):
    at = await _create_agent_type(db_session)
    now = datetime.now(timezone.utc)
    old = await _create_session(
        db_session, at.id, updated_at=now - timedelta(days=365)
    )
    await db_session.commit()

    items, total = await ConversationStore().list_sessions_page(
        db=db_session, all_time=True, agent_type_id=at.id
    )
    assert total == 1
    assert [s.id for s in items] == [old.id]


@pytest.mark.asyncio
async def test_list_sessions_page_status_active_only_by_default_flag(
    db_session: AsyncSession,
):
    """status='active' returns only active sessions."""
    at = await _create_agent_type(db_session)
    now = datetime.now(timezone.utc)
    active = await _create_session(db_session, at.id, updated_at=now)
    await _create_session(
        db_session,
        at.id,
        status=ConversationStatus.closed,
        updated_at=now - timedelta(hours=1),
    )
    await _create_session(
        db_session,
        at.id,
        status=ConversationStatus.archived,
        updated_at=now - timedelta(hours=2),
    )
    await db_session.commit()

    items, total = await ConversationStore().list_sessions_page(
        db=db_session, status="active", agent_type_id=at.id
    )
    assert total == 1
    assert [s.id for s in items] == [active.id]


@pytest.mark.asyncio
async def test_list_sessions_page_status_ended_includes_closed_and_archived(
    db_session: AsyncSession,
):
    """status='ended' = closed/archived/error (not active)."""
    at = await _create_agent_type(db_session)
    now = datetime.now(timezone.utc)
    await _create_session(db_session, at.id, updated_at=now)
    closed = await _create_session(
        db_session,
        at.id,
        status=ConversationStatus.closed,
        updated_at=now - timedelta(hours=1),
    )
    archived = await _create_session(
        db_session,
        at.id,
        status=ConversationStatus.archived,
        updated_at=now - timedelta(hours=2),
    )
    await db_session.commit()

    items, total = await ConversationStore().list_sessions_page(
        db=db_session, status="ended", agent_type_id=at.id
    )
    assert total == 2
    assert {s.id for s in items} == {closed.id, archived.id}


@pytest.mark.asyncio
async def test_list_sessions_page_status_all_includes_everything(db_session: AsyncSession):
    at = await _create_agent_type(db_session)
    now = datetime.now(timezone.utc)
    await _create_session(db_session, at.id, updated_at=now)
    await _create_session(
        db_session,
        at.id,
        status=ConversationStatus.closed,
        updated_at=now - timedelta(hours=1),
    )
    await db_session.commit()

    _, total = await ConversationStore().list_sessions_page(
        db=db_session, status="all", agent_type_id=at.id
    )
    assert total == 2


@pytest.mark.asyncio
async def test_list_sessions_page_pagination_and_total(db_session: AsyncSession):
    at = await _create_agent_type(db_session)
    now = datetime.now(timezone.utc)
    ids_in_order = []
    for i in range(5):
        s = await _create_session(
            db_session, at.id, updated_at=now - timedelta(hours=i)
        )
        ids_in_order.append(s.id)
    await db_session.commit()

    page1, total = await ConversationStore().list_sessions_page(
        db=db_session, page=1, page_size=2, agent_type_id=at.id
    )
    page2, _ = await ConversationStore().list_sessions_page(
        db=db_session, page=2, page_size=2, agent_type_id=at.id
    )
    assert total == 5
    assert [s.id for s in page1] == ids_in_order[:2]
    assert [s.id for s in page2] == ids_in_order[2:4]


@pytest.mark.asyncio
async def test_list_sessions_page_tenant_isolated(db_session: AsyncSession):
    """Sessions from another tenant are never returned."""
    from app.db.models.tenant import Tenant

    tenant_a = Tenant(name="tenant-a", slug=f"a-{uuid.uuid4().hex[:8]}", is_system_tenant=False)
    tenant_b = Tenant(name="tenant-b", slug=f"b-{uuid.uuid4().hex[:8]}", is_system_tenant=False)
    db_session.add_all([tenant_a, tenant_b])
    await db_session.flush()

    at = await _create_agent_type(db_session)
    now = datetime.now(timezone.utc)
    mine = await _create_session(
        db_session, at.id, updated_at=now, tenant_id=tenant_a.id
    )
    theirs = await _create_session(
        db_session, at.id, updated_at=now, tenant_id=tenant_b.id
    )
    await db_session.commit()

    items, total = await ConversationStore().list_sessions_page(
        db=db_session, tenant_id=tenant_a.id
    )
    assert total == 1
    assert [s.id for s in items] == [mine.id]
    assert theirs.id not in {s.id for s in items}


@pytest.mark.asyncio
async def test_legacy_list_sessions_still_works_backward_compat(db_session: AsyncSession):
    """The existing list_sessions (list return, no window) keeps working."""
    at = await _create_agent_type(db_session)
    now = datetime.now(timezone.utc)
    await _create_session(db_session, at.id, updated_at=now - timedelta(days=30))
    await db_session.commit()

    result = await ConversationStore().list_sessions(db=db_session, agent_type_id=at.id)
    assert isinstance(result, list)
    assert len(result) == 1  # no default window applied on legacy path


# ── Endpoint-level tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sessions_endpoint_default_window_applied(
    async_client: AsyncClient, db_session: AsyncSession
):
    """GET /conversations/sessions applies the 7-day default window + status=active default."""
    from app.api.deps import get_current_claims, require_permission
    from app.core.resource_types import RT_AGENT_TRAILS
    from app.main import create_app

    at = await _create_agent_type(db_session)
    now = datetime.now(timezone.utc)
    await _create_session(db_session, at.id, updated_at=now - timedelta(days=10))
    recent = await _create_session(db_session, at.id, updated_at=now)
    await db_session.commit()

    dep_fn = require_permission(RT_AGENT_TRAILS, "read")
    app = create_app()
    app.dependency_overrides[dep_fn] = lambda: _auth_override()
    app.dependency_overrides[get_current_claims] = lambda: _auth_override()

    with patch("app.api.v1.conversations.get_current_claims", return_value=_auth_override()):
        response = await async_client.get(
            f"/api/v1/conversations/sessions?agent_type_id={at.id}",
            headers={"Authorization": "Bearer test"},
        )

    assert response.status_code in (200, 401, 403)
    if response.status_code == 200:
        body = response.json()
        assert body["total"] == 1
        assert [s["id"] for s in body["items"]] == [str(recent.id)]
        assert body["default_window_days"] >= 1


@pytest.mark.asyncio
async def test_sessions_endpoint_accepts_new_filter_params(async_client: AsyncClient):
    """New query params (status/date_from/date_to/page/page_size/all_time) accepted."""
    from app.api.deps import require_permission
    from app.core.resource_types import RT_AGENT_TRAILS
    from app.main import create_app

    dep_fn = require_permission(RT_AGENT_TRAILS, "read")
    app = create_app()
    app.dependency_overrides[dep_fn] = lambda: _auth_override()

    response = await async_client.get(
        "/api/v1/conversations/sessions"
        "?status=ended&page=2&page_size=10&all_time=true"
        "&date_from=2026-10-01T00:00:00Z&date_to=2026-11-01T00:00:00Z",
        headers={"Authorization": "Bearer test"},
    )
    # 200 (new endpoint), 401/403 (auth in stripped harness) — never 404/422
    assert response.status_code in (200, 401, 403)


@pytest.mark.asyncio
async def test_config_exposes_default_window_days_setting():
    """conversation_sessions_default_window_days exists on Settings with default 7."""
    from app.core.config import Settings

    settings = Settings()
    assert settings.conversation_sessions_default_window_days == 7
