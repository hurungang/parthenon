"""SendGrid email API provider — specific implementation for SendGrid."""
from __future__ import annotations

import logging

import httpx
from opentelemetry import trace

from .base import BaseChannelProvider, ChannelDeliveryResult

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class SendGridChannelProvider(BaseChannelProvider):
    """
    Dispatches email notifications via SendGrid API.

    Expected property keys:
      api_key        — SendGrid API key (secret)
      from_address   — Verified sender email address
      from_name      — Sender name (optional)
    
    SendGrid API docs: https://docs.sendgrid.com/api-reference/mail-send/mail-send
    """

    SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"

    async def send(
        self,
        recipients: list[str],
        subject: str | None,
        body: str,
        properties: dict[str, str],
    ) -> ChannelDeliveryResult:
        with tracer.start_as_current_span(
            "notification.sendgrid.send",
            attributes={
                "channel.type": "SENDGRID",
                "notification.recipient_count": len(recipients),
            },
        ):
            try:
                return await self._dispatch(recipients, subject, body, properties)
            except Exception as exc:
                logger.error("SendGridChannelProvider.send failed: %s", exc)
                return ChannelDeliveryResult(success=False, error=str(exc))

    async def _dispatch(
        self,
        recipients: list[str],
        subject: str | None,
        body: str,
        properties: dict[str, str],
    ) -> ChannelDeliveryResult:
        api_key = properties.get("api_key", "")
        from_address = properties.get("from_address", "")
        from_name = properties.get("from_name", "")

        if not api_key:
            return ChannelDeliveryResult(success=False, error="api_key is required")
        if not from_address:
            return ChannelDeliveryResult(success=False, error="from_address is required")
        if not recipients:
            return ChannelDeliveryResult(success=False, error="No recipients provided")

        # SendGrid API payload structure
        payload = {
            "personalizations": [
                {
                    "to": [{"email": email} for email in recipients]
                }
            ],
            "from": {
                "email": from_address,
                **({"name": from_name} if from_name else {}),
            },
            "subject": subject or "Notification",
            "content": [
                {
                    "type": "text/plain",
                    "value": body
                }
            ],
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.SENDGRID_API_URL, json=payload, headers=headers)

        if response.is_success:
            return ChannelDeliveryResult(
                success=True,
                metadata={"provider": "sendgrid", "status_code": response.status_code},
            )
        
        return ChannelDeliveryResult(
            success=False,
            error=f"SendGrid API returned {response.status_code}: {response.text[:500]}",
        )
