"""Notification Hook — sends permission-domain notifications via the notification service."""
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.access_request import AccessRequest, AccessRequestStatus
from app.db.models.group import Group
from app.db.models.notifications import NotificationChannel, SourceType
from app.db.models.platform_user import PlatformUser
from app.services.notifications.notification_service import NotificationService
from app.services.notifications.repository import NotificationRepository

logger = logging.getLogger(__name__)


class NotificationHook:
    """Sends permission-domain notifications via the notification service."""

    async def notify_owner_new_request(
        self,
        db: AsyncSession,
        group_id: uuid.UUID,
        requester_id: uuid.UUID,
    ) -> None:
        """Notify the group owner that a new join request has been submitted.

        Silently no-ops when no notification channels are configured.
        """
        try:
            group = await db.get(Group, group_id)
            if group is None or group.owner_id is None:
                return

            owner = await db.get(PlatformUser, group.owner_id)
            requester = await db.get(PlatformUser, requester_id)
            if owner is None or requester is None:
                return

            channel = await self._get_any_active_channel(db)
            if channel is None:
                logger.debug("No active notification channel; skipping owner notification.")
                return

            body = (
                f"User '{requester.display_name}' ({requester.email}) has requested "
                f"to join the group '{group.name}'. Please review the request."
            )

            # Use service for direct channel dispatch without group routing
            svc = NotificationService(db)
            await svc.test_channel(
                channel_id=channel.id,
                test_recipient=owner.email or "",
            )
            # test_channel is a canned send; use _dispatch directly for custom content
            repo = NotificationRepository(db)
            props = await svc._load_decrypted_properties(channel.id)
            log = await repo.create_notification_log(
                channel_id=channel.id,
                source_type=SourceType.MANUAL,
                subject=f"New join request for group '{group.name}'",
                body=body,
                recipient=owner.email,
            )
            result = await svc._dispatch(
                channel_type=channel.channel_type,
                properties=props,
                subject=f"New join request for group '{group.name}'",
                body=body,
                recipients=[owner.email] if owner.email else [],
            )
            from app.db.models.notifications import DeliveryStatus
            from app.services.notifications.delivery_tracker import DeliveryTracker
            tracker = DeliveryTracker(repo)
            await tracker.record(
                log_id=log.id,
                channel_type=channel.channel_type.value,
                status=DeliveryStatus.delivered if result.success else DeliveryStatus.failed,
                error=result.error,
                metadata=result.metadata,
            )
        except Exception as exc:
            logger.error("NotificationHook.notify_owner_new_request failed: %s", exc)

    async def notify_requester_decision(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
    ) -> None:
        """Notify the requester that their access request was approved or rejected.

        Silently no-ops when no notification channels are configured.
        """
        try:
            request = await db.get(AccessRequest, request_id)
            if request is None:
                return

            requester = await db.get(PlatformUser, request.user_id)
            if requester is None:
                return

            group = await db.get(Group, request.group_id)
            group_name = group.name if group else str(request.group_id)

            channel = await self._get_any_active_channel(db)
            if channel is None:
                logger.debug("No active notification channel; skipping requester notification.")
                return

            if request.status == AccessRequestStatus.approved:
                subject = f"Access request approved: {group_name}"
                body = f"Your request to join '{group_name}' has been approved."
                if request.reviewer_reason:
                    body += f" Reviewer note: {request.reviewer_reason}"
            else:
                subject = f"Access request rejected: {group_name}"
                body = f"Your request to join '{group_name}' has been rejected."
                if request.reviewer_reason:
                    body += f" Reason: {request.reviewer_reason}"

            svc = NotificationService(db)
            repo = NotificationRepository(db)
            props = await svc._load_decrypted_properties(channel.id)
            log = await repo.create_notification_log(
                channel_id=channel.id,
                source_type=SourceType.MANUAL,
                subject=subject,
                body=body,
                recipient=requester.email,
            )
            result = await svc._dispatch(
                channel_type=channel.channel_type,
                properties=props,
                subject=subject,
                body=body,
                recipients=[requester.email] if requester.email else [],
            )
            from app.db.models.notifications import DeliveryStatus
            from app.services.notifications.delivery_tracker import DeliveryTracker
            tracker = DeliveryTracker(repo)
            await tracker.record(
                log_id=log.id,
                channel_type=channel.channel_type.value,
                status=DeliveryStatus.delivered if result.success else DeliveryStatus.failed,
                error=result.error,
                metadata=result.metadata,
            )
        except Exception as exc:
            logger.error("NotificationHook.notify_requester_decision failed: %s", exc)

    async def _get_any_active_channel(
        self, db: AsyncSession
    ) -> NotificationChannel | None:
        """Return any active notification channel, or None."""
        result = await db.execute(
            select(NotificationChannel)
            .where(NotificationChannel.is_active.is_(True))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def notify_owner_new_request(
        self,
        db: AsyncSession,
        group_id: uuid.UUID,
        requester_id: uuid.UUID,
    ) -> None:
        """Notify the group owner that a new join request has been submitted.

        Silently no-ops when no notification channels are configured.
        """
        try:
            group = await db.get(Group, group_id)
            if group is None or group.owner_id is None:
                return

            owner = await db.get(PlatformUser, group.owner_id)
            requester = await db.get(PlatformUser, requester_id)
            if owner is None or requester is None:
                return

            channel = await self._get_any_active_channel(db)
            if channel is None:
                logger.debug("No active notification channel; skipping owner notification.")
                return

            body = (
                f"User '{requester.display_name}' ({requester.email}) has requested "
                f"to join the group '{group.name}'. Please review the request."
            )
            await self._dispatcher.dispatch(
                channel=channel,
                subject=f"New join request for group '{group.name}'",
                body=body,
                recipient=owner.email,
                db=db,
            )
        except Exception as exc:
            logger.error("NotificationHook.notify_owner_new_request failed: %s", exc)

    async def notify_requester_decision(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
    ) -> None:
        """Notify the requester that their access request was approved or rejected.

        Silently no-ops when no notification channels are configured.
        """
        try:
            request = await db.get(AccessRequest, request_id)
            if request is None:
                return

            requester = await db.get(PlatformUser, request.user_id)
            if requester is None:
                return

            group = await db.get(Group, request.group_id)
            group_name = group.name if group else str(request.group_id)

            channel = await self._get_any_active_channel(db)
            if channel is None:
                logger.debug("No active notification channel; skipping requester notification.")
                return

            if request.status == AccessRequestStatus.approved:
                subject = f"Access request approved: {group_name}"
                body = f"Your request to join '{group_name}' has been approved."
                if request.reviewer_reason:
                    body += f" Reviewer note: {request.reviewer_reason}"
            else:
                subject = f"Access request rejected: {group_name}"
                body = f"Your request to join '{group_name}' has been rejected."
                if request.reviewer_reason:
                    body += f" Reason: {request.reviewer_reason}"

            await self._dispatcher.dispatch(
                channel=channel,
                subject=subject,
                body=body,
                recipient=requester.email,
                db=db,
            )
        except Exception as exc:
            logger.error("NotificationHook.notify_requester_decision failed: %s", exc)

    async def _get_any_active_channel(
        self, db: AsyncSession
    ) -> NotificationChannel | None:
        """Return any active notification channel, or None."""
        result = await db.execute(
            select(NotificationChannel)
            .where(NotificationChannel.is_active.is_(True))
            .limit(1)
        )
        return result.scalar_one_or_none()
