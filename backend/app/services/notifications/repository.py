"""Notification repository — all async DB operations for the notification domain."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.notifications import (
    ChannelProperty,
    DeliveryStatus,
    GroupChannelMapping,
    NotificationChannel,
    NotificationLog,
    RecipientGroup,
    SourceType,
)

logger = logging.getLogger(__name__)


class NotificationRepository:
    """
    Encapsulates all async database operations for the notification domain.

    Accepts an AsyncSession and returns typed ORM instances.
    Never performs encryption — that responsibility belongs to the service layer.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    # ── Channel operations ─────────────────────────────────────────────────────

    async def get_channel(self, channel_id: uuid.UUID) -> NotificationChannel | None:
        result = await self._db.execute(
            select(NotificationChannel)
            .where(NotificationChannel.id == channel_id)
            .options(
                selectinload(NotificationChannel.properties),
                selectinload(NotificationChannel.group_mappings),
            )
        )
        return result.scalar_one_or_none()

    async def list_channels(self, limit: int = 0, offset: int = 0) -> list[NotificationChannel]:
        query = (
            select(NotificationChannel)
            .order_by(NotificationChannel.name)
            .options(selectinload(NotificationChannel.properties))
        )
        if limit:
            query = query.limit(limit).offset(offset)
        result = await self._db.execute(query)
        return list(result.scalars().all())

    async def create_channel(
        self,
        name: str,
        channel_type: str,
        description: str | None,
        is_active: bool = True,
    ) -> NotificationChannel:
        channel = NotificationChannel(
            name=name,
            channel_type=channel_type,
            description=description,
            is_active=is_active,
        )
        self._db.add(channel)
        await self._db.flush()
        await self._db.refresh(channel)
        return channel

    async def update_channel(
        self,
        channel_id: uuid.UUID,
        updates: dict,
    ) -> NotificationChannel | None:
        channel = await self._db.get(NotificationChannel, channel_id)
        if channel is None:
            return None
        for field, value in updates.items():
            setattr(channel, field, value)
        await self._db.flush()
        await self._db.refresh(channel)
        return channel

    async def delete_channel(self, channel_id: uuid.UUID) -> bool:
        channel = await self._db.get(NotificationChannel, channel_id)
        if channel is None:
            return False
        await self._db.delete(channel)
        await self._db.flush()
        return True

    # ── Channel property operations ────────────────────────────────────────────

    async def get_channel_properties(self, channel_id: uuid.UUID) -> list[ChannelProperty]:
        result = await self._db.execute(
            select(ChannelProperty).where(ChannelProperty.channel_id == channel_id)
        )
        return list(result.scalars().all())

    async def set_channel_property(
        self,
        channel_id: uuid.UUID,
        key: str,
        encrypted_value: str,
        is_secret: bool,
    ) -> ChannelProperty:
        """Upsert a channel property (insert or update by channel_id + key)."""
        result = await self._db.execute(
            select(ChannelProperty).where(
                ChannelProperty.channel_id == channel_id,
                ChannelProperty.key == key,
            )
        )
        prop = result.scalar_one_or_none()
        if prop is None:
            prop = ChannelProperty(
                channel_id=channel_id,
                key=key,
                encrypted_value=encrypted_value,
                is_secret=is_secret,
            )
            self._db.add(prop)
        else:
            prop.encrypted_value = encrypted_value
            prop.is_secret = is_secret
        await self._db.flush()
        await self._db.refresh(prop)
        return prop

    async def delete_channel_properties(self, channel_id: uuid.UUID) -> None:
        """Remove all properties for a channel (used before replacing the full set)."""
        props = await self.get_channel_properties(channel_id)
        for p in props:
            await self._db.delete(p)
        await self._db.flush()

    # ── Recipient group operations ─────────────────────────────────────────────

    async def get_recipient_group(self, group_id: uuid.UUID) -> RecipientGroup | None:
        result = await self._db.execute(
            select(RecipientGroup)
            .where(RecipientGroup.id == group_id)
            .options(
                selectinload(RecipientGroup.channel_mappings).selectinload(
                    GroupChannelMapping.channel
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_recipient_group_by_slug(self, slug: str) -> RecipientGroup | None:
        result = await self._db.execute(
            select(RecipientGroup)
            .where(RecipientGroup.slug == slug)
            .options(
                selectinload(RecipientGroup.channel_mappings).selectinload(
                    GroupChannelMapping.channel
                ).selectinload(NotificationChannel.properties)
            )
        )
        return result.scalar_one_or_none()

    async def list_recipient_groups(self, limit: int = 0, offset: int = 0) -> list[RecipientGroup]:
        query = (
            select(RecipientGroup)
            .order_by(RecipientGroup.name)
            .options(
                selectinload(RecipientGroup.channel_mappings).selectinload(
                    GroupChannelMapping.channel
                )
            )
        )
        if limit:
            query = query.limit(limit).offset(offset)
        result = await self._db.execute(query)
        return list(result.scalars().all())

    async def create_recipient_group(
        self,
        name: str,
        slug: str,
        description: str | None,
        is_active: bool = True,
    ) -> RecipientGroup:
        group = RecipientGroup(
            name=name,
            slug=slug,
            description=description,
            is_active=is_active,
        )
        self._db.add(group)
        await self._db.flush()
        await self._db.refresh(group)
        return group

    async def update_recipient_group(
        self,
        group_id: uuid.UUID,
        updates: dict,
    ) -> RecipientGroup | None:
        group = await self._db.get(RecipientGroup, group_id)
        if group is None:
            return None
        for field, value in updates.items():
            setattr(group, field, value)
        await self._db.flush()
        await self._db.refresh(group)
        return group

    async def delete_recipient_group(self, group_id: uuid.UUID) -> bool:
        group = await self._db.get(RecipientGroup, group_id)
        if group is None:
            return False
        await self._db.delete(group)
        await self._db.flush()
        return True

    # ── Group-channel mapping operations ──────────────────────────────────────

    async def assign_channel_to_group(
        self, group_id: uuid.UUID, channel_id: uuid.UUID, recipient_properties: dict | None = None
    ) -> GroupChannelMapping:
        # Check for existing mapping
        result = await self._db.execute(
            select(GroupChannelMapping).where(
                GroupChannelMapping.group_id == group_id,
                GroupChannelMapping.channel_id == channel_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            # Update recipient_properties if it exists
            if recipient_properties is not None:
                existing.recipient_properties = recipient_properties
                await self._db.flush()
                await self._db.refresh(existing)
            return existing
        mapping = GroupChannelMapping(
            group_id=group_id,
            channel_id=channel_id,
            recipient_properties=recipient_properties,
        )
        self._db.add(mapping)
        await self._db.flush()
        await self._db.refresh(mapping)
        return mapping

    async def remove_channel_from_group(
        self, group_id: uuid.UUID, channel_id: uuid.UUID
    ) -> bool:
        result = await self._db.execute(
            select(GroupChannelMapping).where(
                GroupChannelMapping.group_id == group_id,
                GroupChannelMapping.channel_id == channel_id,
            )
        )
        mapping = result.scalar_one_or_none()
        if mapping is None:
            return False
        await self._db.delete(mapping)
        await self._db.flush()
        return True

    # ── Notification log operations ────────────────────────────────────────────

    async def create_notification_log(
        self,
        channel_id: uuid.UUID,
        source_type: SourceType,
        body: str,
        group_id: uuid.UUID | None = None,
        source_id: uuid.UUID | None = None,
        subject: str | None = None,
        recipient: str | None = None,
    ) -> NotificationLog:
        log = NotificationLog(
            channel_id=channel_id,
            group_id=group_id,
            source_type=source_type,
            source_id=source_id,
            subject=subject,
            body=body,
            recipient=recipient,
            status=DeliveryStatus.pending,
        )
        self._db.add(log)
        await self._db.flush()
        await self._db.refresh(log)
        return log

    async def update_log_status(
        self,
        log_id: uuid.UUID,
        status: DeliveryStatus,
        error: str | None = None,
        delivered_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> NotificationLog | None:
        log = await self._db.get(NotificationLog, log_id)
        if log is None:
            return None
        log.status = status
        log.error = error
        if delivered_at is not None:
            log.delivered_at = delivered_at
        if metadata is not None:
            log.metadata_ = metadata
        await self._db.flush()
        await self._db.refresh(log)
        return log

    async def list_logs(
        self,
        group_id: uuid.UUID | None = None,
        channel_id: uuid.UUID | None = None,
        status: DeliveryStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[NotificationLog]:
        query = select(NotificationLog).order_by(NotificationLog.created_at.desc())
        if group_id:
            query = query.where(NotificationLog.group_id == group_id)
        if channel_id:
            query = query.where(NotificationLog.channel_id == channel_id)
        if status:
            query = query.where(NotificationLog.status == status)
        query = query.limit(limit).offset(offset)
        result = await self._db.execute(query)
        return list(result.scalars().all())

    async def get_log(self, log_id: uuid.UUID) -> NotificationLog | None:
        return await self._db.get(NotificationLog, log_id)
