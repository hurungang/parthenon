"""SMTP channel provider — sends email via smtplib wrapped in asyncio.to_thread."""
from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from opentelemetry import trace

from .base import BaseChannelProvider, ChannelDeliveryResult

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class SMTPChannelProvider(BaseChannelProvider):
    """
    Dispatches email notifications via SMTP.

    Expected property keys:
      smtp_host      — SMTP server hostname (default: localhost)
      smtp_port      — SMTP server port (default: 587)
      smtp_username  — SMTP auth username
      smtp_password  — SMTP auth password (secret)
      from_address   — Sender address
      use_tls        — "true" / "false" (default: "true")
    """

    async def send(
        self,
        recipients: list[str],
        subject: str | None,
        body: str,
        properties: dict[str, str],
    ) -> ChannelDeliveryResult:
        with tracer.start_as_current_span(
            "notification.smtp.send",
            attributes={
                "channel.type": "SMTP",
                "notification.recipient_count": len(recipients),
            },
        ):
            try:
                result = await asyncio.to_thread(
                    self._send_sync, recipients, subject or "Notification", body, properties
                )
                return result
            except Exception as exc:
                logger.error("SMTPChannelProvider.send failed: %s", exc)
                return ChannelDeliveryResult(success=False, error=str(exc))

    def _send_sync(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        properties: dict[str, str],
    ) -> ChannelDeliveryResult:
        smtp_host = properties.get("smtp_host", "localhost")
        smtp_port = int(properties.get("smtp_port", "587"))
        username = properties.get("smtp_username", "")
        password = properties.get("smtp_password", "")
        from_address = properties.get("from_address") or username
        use_tls = properties.get("use_tls", "true").lower() != "false"

        if not recipients:
            return ChannelDeliveryResult(success=False, error="No recipients provided")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_address
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(body, "plain"))

        if use_tls:
            smtp_cls = smtplib.SMTP
            smtp = smtp_cls(smtp_host, smtp_port)
            smtp.starttls()
        else:
            smtp = smtplib.SMTP(smtp_host, smtp_port)

        try:
            if username and password:
                smtp.login(username, password)
            smtp.sendmail(from_address, recipients, msg.as_string())
            smtp.quit()
        except smtplib.SMTPException as exc:
            smtp.quit()
            raise

        return ChannelDeliveryResult(
            success=True,
            metadata={"recipients": recipients, "smtp_host": smtp_host},
        )
