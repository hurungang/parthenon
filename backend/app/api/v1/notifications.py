"""Notifications API router — channel CRUD, recipient group CRUD, test-send, manual send, logs."""
import re
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import require_permission
from app.core.credential_vault import get_vault
from app.core.resource_types import RT_INTEGRATION_NOTIFICATIONS
from app.db.session import DbSession
from app.db.models.notifications import (
    DeliveryStatus,
    NotificationChannel,
    NotificationEvent,
    RecipientGroup,
    SourceType,
)
from app.schemas.notifications import (
    AssignChannelRequest,
    NotificationChannelCreate,
    NotificationChannelRead,
    NotificationChannelUpdate,
    NotificationEventRead,
    NotificationLogRead,
    RecipientGroupCreate,
    RecipientGroupRead,
    RecipientGroupUpdate,
    SendNotificationRequest,
    TestChannelRequest,
    TestChannelResponse,
)
from app.services.notifications.notification_service import NotificationService
from app.services.notifications.repository import NotificationRepository

logger = logging.getLogger(__name__)

NotificationRouter = APIRouter(prefix="/notifications", tags=["Notifications"])


def _slugify(name: str) -> str:
    """Convert a display name to a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:100]


def _enrich_channel_with_values(channel: NotificationChannel) -> dict:
    """Convert channel to dict and populate non-secret property values for editing.
    
    Secret properties (is_secret=True) will have value=None.
    Non-secret properties will have decrypted values populated.
    """
    vault = get_vault()
    
    # Convert base channel attributes
    result = {
        "id": str(channel.id),
        "name": channel.name,
        "channel_type": channel.channel_type.value,
        "description": channel.description,
        "is_active": channel.is_active,
        "created_at": channel.created_at.isoformat(),
        "updated_at": channel.updated_at.isoformat(),
        "properties": []
    }
    
    # Process properties - decrypt non-secret ones
    for prop in channel.properties:
        prop_dict = {
            "id": str(prop.id),
            "key": prop.key,
            "is_secret": prop.is_secret,
            "value": None if prop.is_secret else vault.decrypt(prop.encrypted_value)
        }
        result["properties"].append(prop_dict)
    
    return result


# ── Notification Channels ──────────────────────────────────────────────────────


@NotificationRouter.get("/channels", response_model=list[NotificationChannelRead])
async def list_channels(
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_NOTIFICATIONS, "read")),
    limit: int = 0,
    offset: int = 0,
):
    """List all notification channels with non-secret property values populated."""
    repo = NotificationRepository(db)
    channels = await repo.list_channels(limit=limit, offset=offset)
    return [_enrich_channel_with_values(ch) for ch in channels]


@NotificationRouter.post(
    "/channels",
    response_model=NotificationChannelRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_channel(
    body: NotificationChannelCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_NOTIFICATIONS, "manage")),
):
    """Create a notification channel with properties."""
    repo = NotificationRepository(db)
    vault = get_vault()

    channel = await repo.create_channel(
        name=body.name,
        channel_type=body.channel_type,
        description=body.description,
        is_active=True,
    )

    for prop in body.properties:
        encrypted = vault.encrypt(prop.value)
        await repo.set_channel_property(channel.id, prop.key, encrypted, prop.is_secret)

    channel = await repo.get_channel(channel.id)
    return _enrich_channel_with_values(channel)


@NotificationRouter.get("/channels/{channel_id}", response_model=NotificationChannelRead)
async def get_channel(
    channel_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_NOTIFICATIONS, "read")),
):
    """Get a notification channel with non-secret property values populated."""
    repo = NotificationRepository(db)
    channel = await repo.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Notification channel not found")
    return _enrich_channel_with_values(channel)


@NotificationRouter.put("/channels/{channel_id}", response_model=NotificationChannelRead)
async def update_channel(
    channel_id: uuid.UUID,
    body: NotificationChannelUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_NOTIFICATIONS, "manage")),
):
    """Update a notification channel with non-secret property values populated in response."""
    repo = NotificationRepository(db)
    vault = get_vault()

    updates = body.model_dump(exclude_unset=True, exclude={"properties"})
    channel = await repo.update_channel(channel_id, updates)
    if not channel:
        raise HTTPException(status_code=404, detail="Notification channel not found")

    if body.properties is not None:
        await repo.delete_channel_properties(channel_id)
        for prop in body.properties:
            encrypted = vault.encrypt(prop.value)
            await repo.set_channel_property(channel.id, prop.key, encrypted, prop.is_secret)

    channel = await repo.get_channel(channel.id)
    return _enrich_channel_with_values(channel)


@NotificationRouter.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_NOTIFICATIONS, "manage")),
) -> None:
    """Delete a notification channel and cascade-remove all recipient configurations."""
    repo = NotificationRepository(db)
    channel = await repo.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Notification channel not found")

    # Cascade deletion is handled by SQLAlchemy relationship configuration
    # (cascade="all, delete-orphan" on group_mappings relationship)
    await repo.delete_channel(channel_id)


@NotificationRouter.post("/channels/{channel_id}/test", response_model=TestChannelResponse)
async def test_channel(
    channel_id: uuid.UUID,
    body: TestChannelRequest,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_NOTIFICATIONS, "manage")),
) -> TestChannelResponse:
    svc = NotificationService(db)
    result = await svc.test_channel(channel_id, body.test_recipient)
    return TestChannelResponse(success=result.success, error=result.error)


# ── Recipient Groups ───────────────────────────────────────────────────────────


@NotificationRouter.get("/recipient-groups", response_model=list[RecipientGroupRead])
async def list_recipient_groups(
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_NOTIFICATIONS, "read")),
    limit: int = 0,
    offset: int = 0,
) -> list[RecipientGroup]:
    repo = NotificationRepository(db)
    return await repo.list_recipient_groups(limit=limit, offset=offset)


@NotificationRouter.post(
    "/recipient-groups",
    response_model=RecipientGroupRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_recipient_group(
    body: RecipientGroupCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_NOTIFICATIONS, "manage")),
) -> RecipientGroup:
    repo = NotificationRepository(db)
    slug = body.slug or _slugify(body.name)

    existing = await db.execute(select(RecipientGroup).where(RecipientGroup.slug == slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Recipient group slug '{slug}' already exists")

    group = await repo.create_recipient_group(
        name=body.name,
        slug=slug,
        description=body.description,
        is_active=body.is_active,
    )
    group = await repo.get_recipient_group(group.id)
    return group  # type: ignore[return-value]


@NotificationRouter.get("/recipient-groups/{group_id}", response_model=RecipientGroupRead)
async def get_recipient_group(
    group_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_NOTIFICATIONS, "read")),
) -> RecipientGroup:
    repo = NotificationRepository(db)
    group = await repo.get_recipient_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Recipient group not found")
    return group


@NotificationRouter.put("/recipient-groups/{group_id}", response_model=RecipientGroupRead)
async def update_recipient_group(
    group_id: uuid.UUID,
    body: RecipientGroupUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_NOTIFICATIONS, "manage")),
) -> RecipientGroup:
    repo = NotificationRepository(db)
    updates = body.model_dump(exclude_unset=True)
    group = await repo.update_recipient_group(group_id, updates)
    if not group:
        raise HTTPException(status_code=404, detail="Recipient group not found")
    group = await repo.get_recipient_group(group_id)
    return group  # type: ignore[return-value]


@NotificationRouter.delete(
    "/recipient-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_recipient_group(
    group_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_NOTIFICATIONS, "manage")),
) -> None:
    repo = NotificationRepository(db)
    deleted = await repo.delete_recipient_group(group_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Recipient group not found")


@NotificationRouter.post(
    "/recipient-groups/{group_id}/channels",
    status_code=status.HTTP_201_CREATED,
)
async def assign_channel_to_group(
    group_id: uuid.UUID,
    body: AssignChannelRequest,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_NOTIFICATIONS, "manage")),
) -> dict:
    repo = NotificationRepository(db)
    group = await repo.get_recipient_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Recipient group not found")

    channel = await repo.get_channel(body.channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Notification channel not found")

    mapping = await repo.assign_channel_to_group(
        group_id, body.channel_id, body.recipient_properties
    )
    return {
        "id": str(mapping.id),
        "group_id": str(group_id),
        "channel_id": str(body.channel_id),
        "recipient_properties": mapping.recipient_properties,
    }


@NotificationRouter.delete(
    "/recipient-groups/{group_id}/channels/{channel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_channel_from_group(
    group_id: uuid.UUID,
    channel_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_NOTIFICATIONS, "manage")),
) -> None:
    repo = NotificationRepository(db)
    removed = await repo.remove_channel_from_group(group_id, channel_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Channel assignment not found")


# ── Manual Send ────────────────────────────────────────────────────────────────


@NotificationRouter.post("/send", status_code=status.HTTP_202_ACCEPTED)
async def send_notification(
    body: SendNotificationRequest,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_NOTIFICATIONS, "manage")),
) -> dict:
    svc = NotificationService(db)
    try:
        result = await svc.send_to_group(
            group_slug=body.group_slug,
            body=body.body,
            source_type=body.source_type,
            subject=body.subject,
            source_id=body.source_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"notification_log_ids": [str(lid) for lid in result.log_ids]}


# ── Delivery Logs ──────────────────────────────────────────────────────────────


@NotificationRouter.get("/logs", response_model=list[NotificationLogRead])
async def list_notification_logs(
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_NOTIFICATIONS, "read")),
    group_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
    log_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list:
    repo = NotificationRepository(db)
    parsed_status: DeliveryStatus | None = None
    if log_status:
        try:
            parsed_status = DeliveryStatus(log_status)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid status: {log_status}")

    return await repo.list_logs(
        group_id=group_id,
        channel_id=channel_id,
        status=parsed_status,
        limit=limit,
        offset=offset,
    )


@NotificationRouter.get("/logs/{log_id}", response_model=NotificationLogRead)
async def get_notification_log(
    log_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_NOTIFICATIONS, "read")),
) -> object:
    repo = NotificationRepository(db)
    log = await repo.get_log(log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Notification log not found")
    return log


# ── Legacy events endpoint (backward compat) ───────────────────────────────────


@NotificationRouter.get("/events", response_model=list[NotificationEventRead])
async def list_events(
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_NOTIFICATIONS, "read")),
    channel_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[NotificationEvent]:
    query = select(NotificationEvent).order_by(NotificationEvent.created_at.desc()).limit(limit)
    if channel_id:
        query = query.where(NotificationEvent.channel_id == channel_id)
    result = await db.execute(query)
    return list(result.scalars().all())
