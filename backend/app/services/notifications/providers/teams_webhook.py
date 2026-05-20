"""Microsoft Teams webhook provider — sends adaptive cards to Teams channels."""
from __future__ import annotations

import logging

import httpx
from opentelemetry import trace

from .base import BaseChannelProvider, ChannelDeliveryResult

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class TeamsWebhookChannelProvider(BaseChannelProvider):
    """
    Dispatches notifications to Microsoft Teams via incoming webhook.

    Expected property keys:
      webhook_url    — Teams incoming webhook URL (secret)
      channel_name   — Target Teams channel name (optional, informational)
    
    Teams webhook docs: https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/add-incoming-webhook
    """

    async def send(
        self,
        recipients: list[str],
        subject: str | None,
        body: str,
        properties: dict[str, str],
    ) -> ChannelDeliveryResult:
        with tracer.start_as_current_span(
            "notification.teams_webhook.send",
            attributes={
                "channel.type": "TEAMS_WEBHOOK",
            },
        ):
            try:
                return await self._dispatch(subject, body, properties)
            except Exception as exc:
                logger.error("TeamsWebhookChannelProvider.send failed: %s", exc)
                return ChannelDeliveryResult(success=False, error=str(exc))

    async def _dispatch(
        self,
        subject: str | None,
        body: str,
        properties: dict[str, str],
    ) -> ChannelDeliveryResult:
        webhook_url = properties.get("webhook_url", "")
        
        if not webhook_url:
            return ChannelDeliveryResult(success=False, error="webhook_url is required")

        # Build Teams Adaptive Card payload
        title = subject or "Notification"
        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "contentUrl": None,
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": title,
                                "weight": "bolder",
                                "size": "medium",
                            },
                            {
                                "type": "TextBlock",
                                "text": body,
                                "wrap": True,
                            },
                        ],
                    },
                }
            ],
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )

        if response.is_success:
            return ChannelDeliveryResult(
                success=True,
                metadata={"platform": "teams", "status_code": response.status_code},
            )
        
        return ChannelDeliveryResult(
            success=False,
            error=f"Teams webhook returned {response.status_code}: {response.text[:500]}",
        )
