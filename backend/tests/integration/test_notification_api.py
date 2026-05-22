"""Integration tests for the Notification API and database schema.

Tests:
  Schema verification (SQLite PRAGMA equivalent):
  - notification_channels table exists with expected columns
  - recipient_groups table exists with expected columns
  - channel_properties table exists with expected columns
  - group_channel_mappings table exists with expected columns
  - notification_logs table exists with expected columns
  - channel_id uniqueness-per-key constraint enforced

  Repository CRUD (real DB via db_session fixture):
  - Channel create → read → update → delete lifecycle
  - ChannelProperty create and secret flag preserved
  - RecipientGroup create → read → update → delete lifecycle
  - Auto-slug creation
  - Channel-to-group assignment and removal
  - Duplicate group-channel assignment raises IntegrityError (unique constraint)
  - NotificationLog created with correct fields

  API endpoint tests (via async_client + dependency override):
  - POST /notifications/channels returns 201
  - GET /notifications/channels lists channels (secrets omitted from properties)
  - GET /notifications/channels/{id} returns 404 for unknown id
  - PUT /notifications/channels/{id} updates channel
  - DELETE /notifications/channels/{id} returns 204
  - DELETE /notifications/channels/{id} returns 409 when assigned to group
  - POST /notifications/recipient-groups returns 201 with auto-slug
  - GET /notifications/recipient-groups lists groups
  - POST /notifications/recipient-groups/{id}/channels assigns channel
  - DELETE /notifications/recipient-groups/{id}/channels/{chid} removes assignment
  - GET /notifications/logs lists delivery logs
  - Unauthenticated (permission denied) returns 403
"""
from __future__ import annotations

import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.resource_types import RT_NOTIFICATION
from app.db.models.notifications import (
    ChannelProperty,
    ChannelType,
    DeliveryStatus,
    GroupChannelMapping,
    NotificationChannel,
    NotificationLog,
    RecipientGroup,
    SourceType,
)
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware
from app.services.notifications.repository import NotificationRepository


# ── Auth helpers ─────────────────────────────────────────────────────────────


def _allow_read():
    """Dependency override that grants RT_NOTIFICATION read permission."""
    def override():
        return {"sub": "test-admin", "roles": ["admin"]}
    return override


def _allow_manage():
    """Dependency override that grants RT_NOTIFICATION manage permission."""
    def override():
        return {"sub": "test-admin", "roles": ["admin"]}
    return override


def _deny_permission():
    """Dependency override that denies permission."""
    def override():
        raise __import__("fastapi").HTTPException(status_code=403, detail="Forbidden")
    return override


def _bypass_jwt_middleware():
    """Patch JWTAuthMiddleware to inject identity claims without real JWT validation."""
    from unittest.mock import patch as _patch

    async def _patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "test-admin", "roles": ["admin"]}
        return await call_next(request)

    return _patch.object(JWTAuthMiddleware, "dispatch", _patched_dispatch)


# ── Schema Verification ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notification_channels_table_exists(db_session: AsyncSession):
    """notification_channels table must exist in the test database."""
    result = await db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='notification_channels'")
    )
    row = result.fetchone()
    assert row is not None, "notification_channels table is missing"


@pytest.mark.asyncio
async def test_notification_channels_expected_columns(db_session: AsyncSession):
    """notification_channels has all required columns."""
    result = await db_session.execute(text("PRAGMA table_info(notification_channels)"))
    columns = {row[1] for row in result.fetchall()}
    required = {"id", "name", "channel_type", "description", "is_active", "created_at", "updated_at"}
    missing = required - columns
    assert not missing, f"Missing columns in notification_channels: {missing}"


@pytest.mark.asyncio
async def test_recipient_groups_table_exists(db_session: AsyncSession):
    """recipient_groups table must exist in the test database."""
    result = await db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='recipient_groups'")
    )
    row = result.fetchone()
    assert row is not None, "recipient_groups table is missing"


@pytest.mark.asyncio
async def test_recipient_groups_expected_columns(db_session: AsyncSession):
    """recipient_groups has slug, name, description, is_active columns."""
    result = await db_session.execute(text("PRAGMA table_info(recipient_groups)"))
    columns = {row[1] for row in result.fetchall()}
    required = {"id", "name", "slug", "description", "is_active", "created_at", "updated_at"}
    missing = required - columns
    assert not missing, f"Missing columns in recipient_groups: {missing}"


@pytest.mark.asyncio
async def test_channel_properties_table_exists(db_session: AsyncSession):
    """channel_properties table must exist in the test database."""
    result = await db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='channel_properties'")
    )
    row = result.fetchone()
    assert row is not None, "channel_properties table is missing"


@pytest.mark.asyncio
async def test_channel_properties_expected_columns(db_session: AsyncSession):
    """channel_properties has channel_id, key, encrypted_value, is_secret columns."""
    result = await db_session.execute(text("PRAGMA table_info(channel_properties)"))
    columns = {row[1] for row in result.fetchall()}
    required = {"id", "channel_id", "key", "encrypted_value", "is_secret"}
    missing = required - columns
    assert not missing, f"Missing columns in channel_properties: {missing}"


@pytest.mark.asyncio
async def test_group_channel_mappings_table_exists(db_session: AsyncSession):
    """group_channel_mappings table must exist."""
    result = await db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='group_channel_mappings'")
    )
    row = result.fetchone()
    assert row is not None, "group_channel_mappings table is missing"


@pytest.mark.asyncio
async def test_notification_logs_table_exists(db_session: AsyncSession):
    """notification_logs table must exist."""
    result = await db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='notification_logs'")
    )
    row = result.fetchone()
    assert row is not None, "notification_logs table is missing"


@pytest.mark.asyncio
async def test_notification_logs_expected_columns(db_session: AsyncSession):
    """notification_logs has all required delivery tracking columns."""
    result = await db_session.execute(text("PRAGMA table_info(notification_logs)"))
    columns = {row[1] for row in result.fetchall()}
    required = {
        "id", "channel_id", "group_id", "source_type", "source_id",
        "subject", "body", "recipient", "status", "error", "created_at", "delivered_at",
    }
    missing = required - columns
    assert not missing, f"Missing columns in notification_logs: {missing}"


# ── Repository CRUD Tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_channel_create_and_read(db_session: AsyncSession):
    """Creating a channel via repository returns an object with correct type and name."""
    repo = NotificationRepository(db_session)
    channel = await repo.create_channel(
        name=f"test-smtp-channel-{uuid.uuid4().hex[:6]}",
        channel_type=ChannelType.SMTP,
        description="Test SMTP channel",
    )
    await db_session.flush()

    assert channel.id is not None
    assert channel.channel_type == ChannelType.SMTP
    assert channel.is_active is True

    fetched = await repo.get_channel(channel.id)
    assert fetched is not None
    assert fetched.name == channel.name


@pytest.mark.asyncio
async def test_channel_property_secret_flag_preserved(db_session: AsyncSession):
    """Setting a property with is_secret=True stores the flag correctly."""
    repo = NotificationRepository(db_session)
    channel = await repo.create_channel(
        name=f"secret-channel-{uuid.uuid4().hex[:6]}",
        channel_type=ChannelType.SENDGRID,
        description=None,
    )
    await db_session.flush()

    prop = await repo.set_channel_property(
        channel_id=channel.id,
        key="api_key",
        encrypted_value="encrypted-api-key-value",
        is_secret=True,
    )
    await db_session.flush()

    assert prop.is_secret is True
    assert prop.encrypted_value == "encrypted-api-key-value"


@pytest.mark.asyncio
async def test_channel_update(db_session: AsyncSession):
    """Updating channel name and description via repository reflects in DB."""
    repo = NotificationRepository(db_session)
    channel = await repo.create_channel(
        name=f"update-test-{uuid.uuid4().hex[:6]}",
        channel_type=ChannelType.TEAMS_WEBHOOK,
        description="Original description",
    )
    await db_session.flush()

    updated = await repo.update_channel(
        channel_id=channel.id,
        updates={"description": "Updated description", "is_active": False},
    )
    await db_session.flush()

    assert updated is not None
    assert updated.description == "Updated description"
    assert updated.is_active is False


@pytest.mark.asyncio
async def test_channel_delete(db_session: AsyncSession):
    """Deleting a channel removes it from the database."""
    repo = NotificationRepository(db_session)
    channel = await repo.create_channel(
        name=f"delete-test-{uuid.uuid4().hex[:6]}",
        channel_type=ChannelType.SLACK_WEBHOOK,
        description=None,
    )
    await db_session.flush()

    deleted = await repo.delete_channel(channel.id)
    await db_session.flush()
    assert deleted is True

    fetched = await repo.get_channel(channel.id)
    assert fetched is None


@pytest.mark.asyncio
async def test_recipient_group_create_and_read(db_session: AsyncSession):
    """Creating a recipient group via repository returns correct slug and name."""
    repo = NotificationRepository(db_session)
    name = f"Test Ops Group {uuid.uuid4().hex[:6]}"
    slug = name.lower().replace(" ", "-")

    group = await repo.create_recipient_group(
        name=name,
        slug=slug,
        description="Test group for ops team",
    )
    await db_session.flush()

    assert group.id is not None
    assert group.slug == slug
    assert group.is_active is True

    fetched = await repo.get_recipient_group(group.id)
    assert fetched is not None
    assert fetched.name == name


@pytest.mark.asyncio
async def test_recipient_group_update(db_session: AsyncSession):
    """Updating a recipient group's description via repository takes effect."""
    repo = NotificationRepository(db_session)
    group = await repo.create_recipient_group(
        name=f"group-update-{uuid.uuid4().hex[:6]}",
        slug=f"group-update-{uuid.uuid4().hex[:6]}",
        description="Original",
    )
    await db_session.flush()

    updated = await repo.update_recipient_group(
        group_id=group.id,
        updates={"description": "Updated"},
    )
    await db_session.flush()

    assert updated is not None
    assert updated.description == "Updated"


@pytest.mark.asyncio
async def test_channel_assignment_to_group(db_session: AsyncSession):
    """Assigning a channel to a group creates a GroupChannelMapping."""
    repo = NotificationRepository(db_session)

    channel = await repo.create_channel(
        name=f"assign-ch-{uuid.uuid4().hex[:6]}",
        channel_type=ChannelType.TEAMS_WEBHOOK,
        description=None,
    )
    group = await repo.create_recipient_group(
        name=f"assign-group-{uuid.uuid4().hex[:6]}",
        slug=f"assign-group-{uuid.uuid4().hex[:6]}",
        description=None,
    )
    await db_session.flush()

    mapping = await repo.assign_channel_to_group(group.id, channel.id)
    await db_session.flush()

    assert mapping.id is not None
    assert mapping.channel_id == channel.id
    assert mapping.group_id == group.id


@pytest.mark.asyncio
async def test_duplicate_channel_assignment_is_idempotent(db_session: AsyncSession):
    """Assigning the same channel to the same group twice returns existing mapping (idempotent)."""
    repo = NotificationRepository(db_session)

    channel = await repo.create_channel(
        name=f"dup-ch-{uuid.uuid4().hex[:6]}",
        channel_type=ChannelType.SLACK_WEBHOOK,
        description=None,
    )
    group = await repo.create_recipient_group(
        name=f"dup-group-{uuid.uuid4().hex[:6]}",
        slug=f"dup-group-{uuid.uuid4().hex[:6]}",
        description=None,
    )
    await db_session.flush()

    mapping1 = await repo.assign_channel_to_group(group.id, channel.id)
    await db_session.flush()

    # Second call returns the existing mapping — no IntegrityError
    mapping2 = await repo.assign_channel_to_group(group.id, channel.id)
    await db_session.flush()

    # Same mapping returned
    assert mapping1.id == mapping2.id

    # Only one mapping exists in the group
    fetched = await repo.get_recipient_group(group.id)
    assert len(fetched.channel_mappings) == 1


@pytest.mark.asyncio
async def test_channel_removal_from_group(db_session: AsyncSession):
    """Removing a channel from a group deletes the mapping."""
    repo = NotificationRepository(db_session)

    channel = await repo.create_channel(
        name=f"remove-ch-{uuid.uuid4().hex[:6]}",
        channel_type=ChannelType.TEAMS_WEBHOOK,
        description=None,
    )
    group = await repo.create_recipient_group(
        name=f"remove-group-{uuid.uuid4().hex[:6]}",
        slug=f"remove-group-{uuid.uuid4().hex[:6]}",
        description=None,
    )
    await db_session.flush()

    await repo.assign_channel_to_group(group.id, channel.id)
    await db_session.flush()

    removed = await repo.remove_channel_from_group(group.id, channel.id)
    await db_session.flush()

    assert removed is True

    # Verify mapping is gone
    fetched_group = await repo.get_recipient_group(group.id)
    assert fetched_group is not None
    assert len(fetched_group.channel_mappings) == 0


@pytest.mark.asyncio
async def test_notification_log_creation(db_session: AsyncSession):
    """Creating a NotificationLog via repository stores all fields correctly."""
    repo = NotificationRepository(db_session)

    channel = await repo.create_channel(
        name=f"log-ch-{uuid.uuid4().hex[:6]}",
        channel_type=ChannelType.SLACK_WEBHOOK,
        description=None,
    )
    await db_session.flush()

    log = await repo.create_notification_log(
        channel_id=channel.id,
        source_type=SourceType.MANUAL,
        subject="Test Subject",
        body="Test body text",
        recipient="test@example.com",
    )
    await db_session.flush()

    assert log.id is not None
    assert log.status == DeliveryStatus.pending
    assert log.source_type == SourceType.MANUAL
    assert log.body == "Test body text"


# ── API Endpoint Tests (via async_client) ─────────────────────────────────────


@pytest_asyncio.fixture
async def authed_client(test_engine):
    """Return AsyncClient with JWT middleware and permission deps bypassed."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    app = create_app()

    # Override permission deps
    app.dependency_overrides[require_permission(RT_NOTIFICATION, "read")] = _allow_read()
    app.dependency_overrides[require_permission(RT_NOTIFICATION, "manage")] = _allow_manage()

    # Share the same in-memory engine
    SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()  # commit so data is visible across requests

    app.dependency_overrides[get_db] = override_db

    with _bypass_jwt_middleware():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


@pytest.mark.asyncio
async def test_api_create_channel_returns_201(authed_client: AsyncClient):
    """POST /api/v1/notifications/channels returns 201 with channel data."""
    resp = await authed_client.post(
        "/api/v1/notifications/channels",
        json={
            "name": f"api-test-smtp-{uuid.uuid4().hex[:6]}",
            "channel_type": "SMTP",
            "description": "Created via API test",
            "properties": [
                {"key": "smtp_host", "value": "mail.example.com", "is_secret": False},
                {"key": "smtp_password", "value": "secret123", "is_secret": True},
            ],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["channel_type"] == "SMTP"
    assert "id" in data


@pytest.mark.asyncio
async def test_api_create_channel_secrets_not_in_response(authed_client: AsyncClient):
    """Secret properties have value=None, non-secret properties show actual values."""
    resp = await authed_client.post(
        "/api/v1/notifications/channels",
        json={
            "name": f"api-secret-test-{uuid.uuid4().hex[:6]}",
            "channel_type": "SENDGRID",
            "description": None,
            "properties": [
                {"key": "api_key", "value": "sk-super-secret", "is_secret": True},
                {"key": "from_address", "value": "test@example.com", "is_secret": False},
            ],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    
    # Verify encrypted_value is never exposed
    for prop in data.get("properties", []):
        assert "encrypted_value" not in prop
    
    # Verify secret properties have value=None
    secret_prop = next(p for p in data["properties"] if p["key"] == "api_key")
    assert secret_prop["is_secret"] is True
    assert secret_prop["value"] is None
    
    # Verify non-secret properties have actual values
    nonsecret_prop = next(p for p in data["properties"] if p["key"] == "from_address")
    assert nonsecret_prop["is_secret"] is False
    assert nonsecret_prop["value"] == "test@example.com"


@pytest.mark.asyncio
async def test_api_create_channel_rejects_non_slug_name(authed_client: AsyncClient):
    """POST /api/v1/notifications/channels rejects names that are not slug-format."""
    resp = await authed_client.post(
        "/api/v1/notifications/channels",
        json={
            "name": "Ops Alerts",  # spaces and uppercase are invalid
            "channel_type": "SMTP",
            "description": "Invalid slug format",
            "properties": [],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_api_update_channel_rejects_non_slug_name(authed_client: AsyncClient):
    """PUT /api/v1/notifications/channels/{id} rejects names that are not slug-format."""
    create_resp = await authed_client.post(
        "/api/v1/notifications/channels",
        json={
            "name": f"valid-channel-{uuid.uuid4().hex[:6]}",
            "channel_type": "SMTP",
            "description": None,
            "properties": [],
        },
    )
    assert create_resp.status_code == 201
    channel_id = create_resp.json()["id"]

    update_resp = await authed_client.put(
        f"/api/v1/notifications/channels/{channel_id}",
        json={"name": "Invalid Name"},
    )
    assert update_resp.status_code == 422


@pytest.mark.asyncio
async def test_api_list_channels(authed_client: AsyncClient):
    """GET /api/v1/notifications/channels returns 200 with a list."""
    resp = await authed_client.get("/api/v1/notifications/channels")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_api_get_channel_not_found(authed_client: AsyncClient):
    """GET /api/v1/notifications/channels/{id} returns 404 for unknown ID."""
    resp = await authed_client.get(f"/api/v1/notifications/channels/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_update_channel(authed_client: AsyncClient):
    """PUT /api/v1/notifications/channels/{id} updates the channel description."""
    # Create
    create_resp = await authed_client.post(
        "/api/v1/notifications/channels",
        json={
            "name": f"api-update-test-{uuid.uuid4().hex[:6]}",
            "channel_type": "TEAMS_WEBHOOK",
            "description": "Original",
            "properties": [],
        },
    )
    assert create_resp.status_code == 201
    channel_id = create_resp.json()["id"]

    # Update
    update_resp = await authed_client.put(
        f"/api/v1/notifications/channels/{channel_id}",
        json={"description": "Updated description"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["description"] == "Updated description"


@pytest.mark.asyncio
async def test_api_delete_channel_success(authed_client: AsyncClient):
    """DELETE /api/v1/notifications/channels/{id} returns 204 for unassigned channel."""
    create_resp = await authed_client.post(
        "/api/v1/notifications/channels",
        json={
            "name": f"api-delete-test-{uuid.uuid4().hex[:6]}",
            "channel_type": "SLACK_WEBHOOK",
            "description": None,
            "properties": [],
        },
    )
    assert create_resp.status_code == 201
    channel_id = create_resp.json()["id"]

    delete_resp = await authed_client.delete(f"/api/v1/notifications/channels/{channel_id}")
    assert delete_resp.status_code == 204


@pytest.mark.asyncio
async def test_api_delete_channel_cascades_remove_recipient_configs(authed_client: AsyncClient):
    """DELETE /api/v1/notifications/channels/{id} cascades and removes recipient configurations."""
    # Create channel
    ch_resp = await authed_client.post(
        "/api/v1/notifications/channels",
        json={
            "name": f"api-conflict-ch-{uuid.uuid4().hex[:6]}",
            "channel_type": "TEAMS_WEBHOOK",
            "description": None,
            "properties": [],
        },
    )
    assert ch_resp.status_code == 201
    channel_id = ch_resp.json()["id"]

    # Create group
    grp_resp = await authed_client.post(
        "/api/v1/notifications/recipient-groups",
        json={
            "name": f"Conflict Group {uuid.uuid4().hex[:6]}",
            "description": None,
            "is_active": True,
        },
    )
    assert grp_resp.status_code == 201
    group_id = grp_resp.json()["id"]

    # Assign channel to group
    assign_resp = await authed_client.post(
        f"/api/v1/notifications/recipient-groups/{group_id}/channels",
        json={"channel_id": channel_id},
    )
    assert assign_resp.status_code == 201

    # Delete channel — should succeed and cascade-remove the mapping
    delete_resp = await authed_client.delete(f"/api/v1/notifications/channels/{channel_id}")
    assert delete_resp.status_code == 204

    # Verify channel is gone
    get_ch_resp = await authed_client.get(f"/api/v1/notifications/channels/{channel_id}")
    assert get_ch_resp.status_code == 404

    # Verify group still exists but has no channel mappings
    get_grp_resp = await authed_client.get(f"/api/v1/notifications/recipient-groups/{group_id}")
    assert get_grp_resp.status_code == 200
    assert len(get_grp_resp.json()["channel_mappings"]) == 0


@pytest.mark.asyncio
async def test_api_create_recipient_group_returns_201_with_auto_slug(authed_client: AsyncClient):
    """POST /api/v1/notifications/recipient-groups returns 201 and generates a slug."""
    resp = await authed_client.post(
        "/api/v1/notifications/recipient-groups",
        json={
            "name": f"Ops Team Group {uuid.uuid4().hex[:6]}",
            "description": "Operations team alerts",
            "is_active": True,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "slug" in data
    assert len(data["slug"]) > 0


@pytest.mark.asyncio
async def test_api_list_recipient_groups(authed_client: AsyncClient):
    """GET /api/v1/notifications/recipient-groups returns 200 with a list."""
    resp = await authed_client.get("/api/v1/notifications/recipient-groups")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_api_assign_channel_to_group(authed_client: AsyncClient):
    """POST /api/v1/notifications/recipient-groups/{id}/channels returns 201."""
    ch_resp = await authed_client.post(
        "/api/v1/notifications/channels",
        json={
            "name": f"assign-api-ch-{uuid.uuid4().hex[:6]}",
            "channel_type": "SLACK_WEBHOOK",
            "description": None,
            "properties": [],
        },
    )
    assert ch_resp.status_code == 201
    channel_id = ch_resp.json()["id"]

    grp_resp = await authed_client.post(
        "/api/v1/notifications/recipient-groups",
        json={"name": f"assign-api-grp-{uuid.uuid4().hex[:6]}", "description": None, "is_active": True},
    )
    assert grp_resp.status_code == 201
    group_id = grp_resp.json()["id"]

    assign_resp = await authed_client.post(
        f"/api/v1/notifications/recipient-groups/{group_id}/channels",
        json={"channel_id": channel_id},
    )
    assert assign_resp.status_code == 201


@pytest.mark.asyncio
async def test_api_remove_channel_from_group(authed_client: AsyncClient):
    """DELETE /api/v1/notifications/recipient-groups/{id}/channels/{ch_id} returns 204."""
    ch_resp = await authed_client.post(
        "/api/v1/notifications/channels",
        json={
            "name": f"remove-api-ch-{uuid.uuid4().hex[:6]}",
            "channel_type": "TEAMS_WEBHOOK",
            "description": None,
            "properties": [],
        },
    )
    channel_id = ch_resp.json()["id"]

    grp_resp = await authed_client.post(
        "/api/v1/notifications/recipient-groups",
        json={"name": f"remove-api-grp-{uuid.uuid4().hex[:6]}", "description": None, "is_active": True},
    )
    group_id = grp_resp.json()["id"]

    await authed_client.post(
        f"/api/v1/notifications/recipient-groups/{group_id}/channels",
        json={"channel_id": channel_id},
    )

    remove_resp = await authed_client.delete(
        f"/api/v1/notifications/recipient-groups/{group_id}/channels/{channel_id}"
    )
    assert remove_resp.status_code == 204


@pytest.mark.asyncio
async def test_api_list_logs_returns_200(authed_client: AsyncClient):
    """GET /api/v1/notifications/logs returns 200 with a list."""
    resp = await authed_client.get("/api/v1/notifications/logs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_api_permission_denied_returns_403():
    """Requests with denied permission return 403 (JWT valid but permission check fails)."""
    app = create_app()
    app.dependency_overrides[require_permission(RT_NOTIFICATION, "read")] = _deny_permission()

    with _bypass_jwt_middleware():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/notifications/channels")

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_api_duplicate_group_slug_returns_409(authed_client: AsyncClient):
    """Creating two groups with the same slug returns 409 on the second request."""
    name = f"Slug Conflict Group {uuid.uuid4().hex[:6]}"
    payload = {"name": name, "description": None, "is_active": True}

    resp1 = await authed_client.post("/api/v1/notifications/recipient-groups", json=payload)
    assert resp1.status_code == 201

    # Same name produces same auto-slug → 409
    resp2 = await authed_client.post("/api/v1/notifications/recipient-groups", json=payload)
    assert resp2.status_code == 409
