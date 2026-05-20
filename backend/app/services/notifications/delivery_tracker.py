"""DeliveryTracker — records delivery outcomes to DB and emits OpenTelemetry signals."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from opentelemetry import metrics, trace

from app.db.models.notifications import DeliveryStatus
from app.services.notifications.repository import NotificationRepository

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)
meter = metrics.get_meter(__name__)

_sent_counter = meter.create_counter(
    name="notifications.sent.total",
    description="Total notification send attempts, labelled by channel_type and status.",
    unit="1",
)


class DeliveryTracker:
    """
    Records delivery outcomes to NotificationLog via NotificationRepository
    and emits OpenTelemetry structured log events plus metrics.
    """

    def __init__(self, repository: NotificationRepository) -> None:
        self._repo = repository

    async def record(
        self,
        log_id: uuid.UUID,
        channel_type: str,
        status: DeliveryStatus,
        error: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """
        Persist delivery outcome to NotificationLog and emit OTEL signals.

        Args:
            log_id: ID of the NotificationLog row to update.
            channel_type: Channel type string for metric labels.
            status: Final delivery status.
            error: Error message if status is failed.
            metadata: Optional extra metadata from the provider.
        """
        delivered_at = (
            datetime.now(timezone.utc) if status == DeliveryStatus.delivered else None
        )
        await self._repo.update_log_status(
            log_id=log_id,
            status=status,
            error=error,
            delivered_at=delivered_at,
            metadata=metadata,
        )

        # OTEL counter
        _sent_counter.add(
            1,
            attributes={
                "channel_type": channel_type,
                "status": status.value,
            },
        )

        # Structured log event
        log_attrs = {
            "notification.log_id": str(log_id),
            "notification.channel_type": channel_type,
            "notification.status": status.value,
        }
        if error:
            log_attrs["notification.error"] = error

        if status == DeliveryStatus.delivered:
            logger.info("Notification delivered", extra=log_attrs)
        else:
            logger.warning("Notification delivery failed", extra=log_attrs)
