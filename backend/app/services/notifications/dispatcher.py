"""Notification Dispatcher — dispatches notifications via configured channels."""
import json
import logging
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.credential_vault import get_vault
from app.db.models.notifications import (
    ChannelType,
    DeliveryStatus,
    NotificationChannel,
    NotificationEvent,
)

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """
    Dispatches outbound notifications to configured channels:
    email, Slack, Teams, webhook.
    Each channel type is also exposed as an MCP tool.
    """

    MCP_TOOLS = [
        {
            "name": "notify_email",
            "description": "Send an email notification via a configured email channel.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "channel_id": {"type": "string"},
                    "recipient": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["channel_id", "recipient", "subject", "body"],
            },
        },
        {
            "name": "notify_slack",
            "description": "Send a Slack notification via a configured Slack channel.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "channel_id": {"type": "string"},
                    "body": {"type": "string"},
                    "recipient": {"type": "string", "description": "Slack channel or user ID"},
                },
                "required": ["channel_id", "body"],
            },
        },
        {
            "name": "notify_teams",
            "description": "Send a Microsoft Teams notification via a configured Teams channel.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "channel_id": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["channel_id", "body"],
            },
        },
        {
            "name": "notify_webhook",
            "description": "Send a webhook notification via a configured webhook channel.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "channel_id": {"type": "string"},
                    "body": {"type": "string"},
                    "recipient": {"type": "string", "description": "Override webhook URL"},
                },
                "required": ["channel_id", "body"],
            },
        },
    ]

    async def dispatch(
        self,
        channel: NotificationChannel,
        subject: str | None,
        body: str,
        recipient: str | None,
        db: AsyncSession,
    ) -> NotificationEvent:
        """
        Dispatch a notification through the given channel.
        Creates a NotificationEvent record and makes the delivery attempt.
        """
        event = NotificationEvent(
            channel_id=channel.id,
            subject=subject,
            body=body,
            recipient=recipient,
            status=DeliveryStatus.pending,
        )
        db.add(event)
        await db.flush()

        # Decrypt channel config
        config: dict[str, Any] = {}
        if channel.encrypted_config:
            try:
                vault = get_vault()
                config = json.loads(vault.decrypt(channel.encrypted_config))
            except Exception as exc:
                logger.error("Failed to decrypt channel config for %s: %s", channel.id, exc)
                event.status = DeliveryStatus.failed
                event.error = "Failed to decrypt channel configuration"
                await db.flush()
                return event

        try:
            if channel.channel_type == ChannelType.email:
                await self._send_email(config, subject or "Notification", body, recipient)
            elif channel.channel_type == ChannelType.slack:
                await self._send_slack(config, body, recipient)
            elif channel.channel_type == ChannelType.teams:
                await self._send_teams(config, body)
            elif channel.channel_type == ChannelType.webhook:
                await self._send_webhook(config, body, recipient)

            event.status = DeliveryStatus.delivered
            event.delivered_at = datetime.now(timezone.utc)
        except Exception as exc:
            logger.error(
                "Notification delivery failed for channel %s: %s", channel.id, exc
            )
            event.status = DeliveryStatus.failed
            event.error = str(exc)

        await db.flush()
        await db.refresh(event)
        return event

    async def _send_email(
        self,
        config: dict[str, Any],
        subject: str,
        body: str,
        recipient: str | None,
    ) -> None:
        """Send an email via SMTP."""
        smtp_host = config.get("smtp_host", "localhost")
        smtp_port = int(config.get("smtp_port", 587))
        username = config.get("username", "")
        password = config.get("password", "")
        from_addr = config.get("from_address", username)
        to_addr = recipient or config.get("default_recipient", "")

        if not to_addr:
            raise ValueError("No recipient email address provided")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg.attach(MIMEText(body, "plain"))

        import asyncio

        def send_sync() -> None:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                if username and password:
                    server.login(username, password)
                server.sendmail(from_addr, to_addr, msg.as_string())

        await asyncio.get_event_loop().run_in_executor(None, send_sync)
        logger.info("Email sent to %s via %s:%d", to_addr, smtp_host, smtp_port)

    async def _send_slack(
        self, config: dict[str, Any], body: str, recipient: str | None
    ) -> None:
        """Send a Slack message via Incoming Webhook or Bot API."""
        webhook_url = config.get("webhook_url")
        if webhook_url:
            payload = {"text": body}
            if recipient:
                payload["channel"] = recipient
            async with httpx.AsyncClient() as client:
                response = await client.post(webhook_url, json=payload)
                response.raise_for_status()
        else:
            raise ValueError("Slack channel requires a webhook_url in config")

    async def _send_teams(self, config: dict[str, Any], body: str) -> None:
        """Send a Microsoft Teams message via webhook."""
        webhook_url = config.get("webhook_url")
        if not webhook_url:
            raise ValueError("Teams channel requires a webhook_url in config")

        payload = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "text": body,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()

    async def _send_webhook(
        self, config: dict[str, Any], body: str, recipient: str | None
    ) -> None:
        """Send an HTTP POST to a configured webhook URL."""
        url = recipient or config.get("url")
        if not url:
            raise ValueError("Webhook channel requires a URL")

        method = config.get("method", "POST").upper()
        headers = config.get("headers", {"Content-Type": "application/json"})

        payload: Any
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"message": body}

        async with httpx.AsyncClient() as client:
            response = await client.request(method, url, json=payload, headers=headers)
            response.raise_for_status()
