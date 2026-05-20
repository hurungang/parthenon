"""Resend email API provider — specific implementation for Resend."""
from __future__ import annotations

import logging

import httpx
from opentelemetry import trace

from .base import BaseChannelProvider, ChannelDeliveryResult

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class ResendChannelProvider(BaseChannelProvider):
    """
    Dispatches email notifications via Resend API.

    Expected property keys:
      api_key        — Resend API key (secret)
      from_address   — Verified sender email address (e.g., "noreply@yourdomain.com")
    
    Resend API docs: https://resend.com/docs/api-reference/emails/send-email
    """

    RESEND_API_URL = "https://api.resend.com/emails"

    async def send(
        self,
        recipients: list[str],
        subject: str | None,
        body: str,
        properties: dict[str, str],
    ) -> ChannelDeliveryResult:
        with tracer.start_as_current_span(
            "notification.resend.send",
            attributes={
                "channel.type": "RESEND",
                "notification.recipient_count": len(recipients),
            },
        ):
            try:
                return await self._dispatch(recipients, subject, body, properties)
            except Exception as exc:
                logger.error("ResendChannelProvider.send failed: %s", exc)
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

        if not api_key:
            return ChannelDeliveryResult(success=False, error="api_key is required")
        if not from_address:
            return ChannelDeliveryResult(success=False, error="from_address is required")
        if not recipients:
            return ChannelDeliveryResult(success=False, error="No recipients provided")

        # Resend API payload structure
        # Note: Resend uses "to" as array of strings (not objects like SendGrid)
        payload = {
            "from": from_address,
            "to": recipients,
            "subject": subject or "Notification",
            "text": body,
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.RESEND_API_URL, json=payload, headers=headers)

        if response.is_success:
            return ChannelDeliveryResult(
                success=True,
                metadata={"provider": "resend", "status_code": response.status_code},
            )
        
        return ChannelDeliveryResult(
            success=False,
            error=f"Resend API returned {response.status_code}: {response.text[:500]}",
        )
