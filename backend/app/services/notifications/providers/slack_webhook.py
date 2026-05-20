"""Slack webhook provider — sends Block Kit messages to Slack channels."""
from __future__ import annotations

import logging

import httpx
from opentelemetry import trace

from .base import BaseChannelProvider, ChannelDeliveryResult

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class SlackWebhookChannelProvider(BaseChannelProvider):
    """
    Dispatches notifications to Slack via incoming webhook.

    Expected property keys:
      webhook_url    — Slack incoming webhook URL (secret)
      channel_name   — Target Slack channel name (optional, informational)
    
    Slack webhook docs: https://api.slack.com/messaging/webhooks
    """

    async def send(
        self,
        recipients: list[str],
        subject: str | None,
        body: str,
        properties: dict[str, str],
    ) -> ChannelDeliveryResult:
        with tracer.start_as_current_span(
            "notification.slack_webhook.send",
            attributes={
                "channel.type": "SLACK_WEBHOOK",
            },
        ):
            try:
                return await self._dispatch(subject, body, properties)
            except Exception as exc:
                logger.error("SlackWebhookChannelProvider.send failed: %s", exc)
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

        # Build Slack Block Kit payload
        blocks = []
        if subject:
            blocks.append(
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": subject, "emoji": True},
                }
            )
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": body},
            }
        )
        
        payload = {
            "blocks": blocks,
            "text": subject or body  # Fallback text for notifications
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
                metadata={"platform": "slack", "status_code": response.status_code},
            )
        
        return ChannelDeliveryResult(
            success=False,
            error=f"Slack webhook returned {response.status_code}: {response.text[:500]}",
        )
