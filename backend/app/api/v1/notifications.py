"""Notifications API router — channel CRUD, test-send, and event history."""

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import require_permission
from app.core.credential_vault import get_vault
from app.core.resource_types import RT_NOTIFICATION
from app.db.models.notifications import NotificationChannel, NotificationEvent
from app.db.session import DbSession
from app.schemas.notifications import (
    NotificationChannelCreate,
    NotificationChannelRead,
    NotificationChannelUpdate,
    NotificationEventRead,
    TestNotificationRequest,
)
from app.services.notifications.dispatcher import NotificationDispatcher

logger = logging.getLogger(__name__)

NotificationRouter = APIRouter(prefix="/notifications", tags=["Notifications"])
_dispatcher = NotificationDispatcher()


@NotificationRouter.get("/channels", response_model=list[NotificationChannelRead])
async def list_channels(
    db: DbSession,
    _: dict = Depends(require_permission(RT_NOTIFICATION, "read")),
) -> list[NotificationChannel]:
    result = await db.execute(select(NotificationChannel).order_by(NotificationChannel.name))
    return list(result.scalars().all())


@NotificationRouter.post(
    "/channels",
    response_model=NotificationChannelRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_channel(
    body: NotificationChannelCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_NOTIFICATION, "manage")),
) -> NotificationChannel:
    encrypted_config = None
    if body.config:
        vault = get_vault()
        encrypted_config = vault.encrypt(json.dumps(body.config))

    channel = NotificationChannel(
        name=body.name,
        channel_type=body.channel_type,
        description=body.description,
        encrypted_config=encrypted_config,
    )
    db.add(channel)
    await db.flush()
    await db.refresh(channel)
    return channel


@NotificationRouter.put("/channels/{channel_id}", response_model=NotificationChannelRead)
async def update_channel(
    channel_id: uuid.UUID,
    body: NotificationChannelUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_NOTIFICATION, "manage")),
) -> NotificationChannel:
    channel = await db.get(NotificationChannel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Notification channel not found")

    update_data = body.model_dump(exclude_unset=True, exclude={"config"})
    for field, value in update_data.items():
        setattr(channel, field, value)

    if body.config is not None:
        vault = get_vault()
        channel.encrypted_config = vault.encrypt(json.dumps(body.config))

    await db.flush()
    await db.refresh(channel)
    return channel


@NotificationRouter.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_NOTIFICATION, "manage")),
) -> None:
    channel = await db.get(NotificationChannel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Notification channel not found")
    await db.delete(channel)


@NotificationRouter.post("/channels/{channel_id}/test", response_model=NotificationEventRead)
async def test_channel(
    channel_id: uuid.UUID,
    body: TestNotificationRequest,
    db: DbSession,
    _: dict = Depends(require_permission(RT_NOTIFICATION, "manage")),
) -> NotificationEvent:
    channel = await db.get(NotificationChannel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Notification channel not found")

    event = await _dispatcher.dispatch(
        channel=channel,
        subject=body.subject,
        body=body.body,
        recipient=body.recipient,
        db=db,
    )
    return event


@NotificationRouter.get("/events", response_model=list[NotificationEventRead])
async def list_events(
    db: DbSession,
    _: dict = Depends(require_permission(RT_NOTIFICATION, "read")),
    channel_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[NotificationEvent]:
    query = select(NotificationEvent).order_by(NotificationEvent.created_at.desc()).limit(limit)
    if channel_id:
        query = query.where(NotificationEvent.channel_id == channel_id)
    result = await db.execute(query)
    return list(result.scalars().all())
