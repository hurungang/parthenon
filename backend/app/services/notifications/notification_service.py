"""NotificationService — top-level orchestrator for notification dispatch."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.credential_vault import get_vault
from app.db.models.notifications import ChannelType, DeliveryStatus, SourceType
from app.services.notifications.delivery_tracker import DeliveryTracker
from app.services.notifications.providers.base import ChannelDeliveryResult
from app.services.notifications.providers.resend import ResendChannelProvider
from app.services.notifications.providers.sendgrid import SendGridChannelProvider
from app.services.notifications.providers.slack_webhook import SlackWebhookChannelProvider
from app.services.notifications.providers.smtp import SMTPChannelProvider
from app.services.notifications.providers.teams_webhook import TeamsWebhookChannelProvider
from app.services.notifications.repository import NotificationRepository

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class GroupSendResult:
    """Summary of a send_to_group call across all channels."""

    group_slug: str
    log_ids: list[uuid.UUID]
    channel_results: list[ChannelDeliveryResult]


class NotificationService:
    """
    Orchestrates the full notification send flow:
    group resolution → channel loading → secret decryption →
    provider dispatch → delivery tracking.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._repo = NotificationRepository(session)
        self._tracker = DeliveryTracker(self._repo)
        self._vault = get_vault()

    async def send_to_group(
        self,
        group_slug: str,
        body: str,
        source_type: SourceType = SourceType.MANUAL,
        subject: str | None = None,
        source_id: uuid.UUID | None = None,
        channel: str | None = None,
    ) -> GroupSendResult:
        """
        Dispatch a notification to all channels assigned to the given recipient group.

        Raises:
            ValueError: if the group is not found or is inactive.
        """
        with tracer.start_as_current_span(
            "notification.send_to_group",
            attributes={"notification.group_slug": group_slug},
        ):
            group = await self._repo.get_recipient_group_by_slug(group_slug)
            if group is None:
                raise ValueError(f"Recipient group '{group_slug}' not found")
            if not group.is_active:
                raise ValueError(f"Recipient group '{group_slug}' is inactive")

            selected_mappings = list(group.channel_mappings)
            if channel:
                selector = channel.strip().lower()
                selected_mappings = [
                    mapping
                    for mapping in selected_mappings
                    if self._channel_matches_selector(mapping.channel, selector)
                ]
                if not selected_mappings:
                    available = sorted(
                        {
                            mapping.channel.name
                            for mapping in group.channel_mappings
                            if getattr(mapping.channel, "name", None)
                        }
                    )
                    raise ValueError(
                        f"Channel '{channel}' not found in recipient group '{group_slug}'. "
                        f"Available channels: {available}"
                    )

            log_ids: list[uuid.UUID] = []
            results: list[ChannelDeliveryResult] = []

            for mapping in selected_mappings:
                channel = mapping.channel
                if not channel.is_active:
                    continue

                # Load and decrypt channel auth/config properties
                properties = await self._load_decrypted_properties(channel.id)

                # Get recipient data from the mapping (group-specific)
                recipient_props = mapping.recipient_properties or {}
                
                # Extract recipients based on channel type
                recipients: list[str] = []
                if channel.channel_type in (ChannelType.SMTP, ChannelType.SENDGRID, ChannelType.RESEND):
                    # Email channels: get recipients list
                    recipients = recipient_props.get("recipients", [])
                elif channel.channel_type in (ChannelType.TEAMS_WEBHOOK, ChannelType.SLACK_WEBHOOK):
                    # Webhook channels: recipients not needed (goes to channel)
                    recipients = []
                
                # Determine recipient string for logging
                recipient_str = ", ".join(recipients) if recipients else recipient_props.get("channel_id", "")

                # Create pending log
                log = await self._repo.create_notification_log(
                    channel_id=channel.id,
                    group_id=group.id,
                    source_type=source_type,
                    source_id=source_id,
                    subject=subject,
                    body=body,
                    recipient=recipient_str or None,
                )
                log_ids.append(log.id)

                # Dispatch
                result = await self._dispatch(channel.channel_type, properties, subject, body, recipients)
                results.append(result)

                # Record outcome
                await self._tracker.record(
                    log_id=log.id,
                    channel_type=channel.channel_type.value,
                    status=DeliveryStatus.delivered if result.success else DeliveryStatus.failed,
                    error=result.error,
                    metadata=result.metadata,
                )

            return GroupSendResult(
                group_slug=group_slug,
                log_ids=log_ids,
                channel_results=results,
            )

    @staticmethod
    def _channel_matches_selector(channel: object, selector: str) -> bool:
        """Match channel selector against id, name, or channel_type."""
        channel_id = getattr(channel, "id", None)
        channel_name = getattr(channel, "name", None)
        channel_type = getattr(channel, "channel_type", None)

        if channel_id is not None and str(channel_id).lower() == selector:
            return True
        if isinstance(channel_name, str) and channel_name.lower() == selector:
            return True
        if channel_type is not None:
            channel_type_value = getattr(channel_type, "value", str(channel_type))
            if str(channel_type_value).lower() == selector:
                return True
        return False

    async def test_channel(
        self,
        channel_id: uuid.UUID,
        test_recipient: str,
    ) -> ChannelDeliveryResult:
        """Send a canned test message through the channel. Does not create a log entry."""
        channel = await self._repo.get_channel(channel_id)
        if channel is None:
            return ChannelDeliveryResult(success=False, error="Channel not found")

        properties = await self._load_decrypted_properties(channel_id)
        # Override recipient for test
        if channel.channel_type in (ChannelType.SMTP, ChannelType.SENDGRID, ChannelType.RESEND):
            properties = {**properties, "test_recipient": test_recipient}

        return await self._dispatch(
            channel_type=channel.channel_type,
            properties=properties,
            subject="Test notification from Parthenon",
            body="This is a test notification to verify channel configuration.",
            recipients=[test_recipient],
        )

    async def _load_decrypted_properties(self, channel_id: uuid.UUID) -> dict[str, str]:
        """Load and decrypt all properties for a channel."""
        props = await self._repo.get_channel_properties(channel_id)
        decrypted: dict[str, str] = {}
        for prop in props:
            try:
                decrypted[prop.key] = self._vault.decrypt(prop.encrypted_value)
            except Exception as exc:
                logger.error(
                    "Failed to decrypt property '%s' for channel %s: %s",
                    prop.key,
                    channel_id,
                    exc,
                )
                decrypted[prop.key] = ""
        return decrypted

    async def _dispatch(
        self,
        channel_type: ChannelType,
        properties: dict[str, str],
        subject: str | None,
        body: str,
        recipients: list[str] | None = None,
    ) -> ChannelDeliveryResult:
        """Select the appropriate provider and dispatch."""
        if recipients is None:
            # Derive recipients from properties
            if channel_type in (ChannelType.SMTP, ChannelType.SENDGRID, ChannelType.RESEND):
                default_recipient = properties.get("default_recipient", "")
                recipients = [default_recipient] if default_recipient else []
            else:
                recipients = []

        if channel_type == ChannelType.SMTP:
            provider = SMTPChannelProvider()
        elif channel_type == ChannelType.SENDGRID:
            provider = SendGridChannelProvider()
        elif channel_type == ChannelType.RESEND:
            provider = ResendChannelProvider()
        elif channel_type == ChannelType.TEAMS_WEBHOOK:
            provider = TeamsWebhookChannelProvider()
        elif channel_type == ChannelType.SLACK_WEBHOOK:
            provider = SlackWebhookChannelProvider()
        else:
            return ChannelDeliveryResult(
                success=False,
                error=f"Unknown channel type: {channel_type}",
            )

        return await provider.send(
            recipients=recipients,
            subject=subject,
            body=body,
            properties=properties,
        )
