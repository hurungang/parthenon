"""Unit tests for all notification channel providers.

Tests:
  - SMTPChannelProvider: TLS/plain modes, auth, no recipients, exception propagation
  - SendGridChannelProvider: API payload format, missing api_key, HTTP errors
  - ResendChannelProvider: API payload format, missing api_key, HTTP errors
  - TeamsWebhookChannelProvider: Adaptive card format, missing webhook_url, HTTP errors
  - SlackWebhookChannelProvider: Block Kit format, missing webhook_url, HTTP errors
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── SMTP Provider ────────────────────────────────────────────────────────────


class TestSMTPChannelProvider:
    """Tests for SMTPChannelProvider."""

    @pytest.mark.asyncio
    async def test_send_success_with_tls(self):
        """send() returns success when smtplib delivers without error (TLS mode)."""
        from app.services.notifications.providers.smtp import SMTPChannelProvider
        from app.services.notifications.providers.base import ChannelDeliveryResult

        expected = ChannelDeliveryResult(
            success=True, metadata={"recipients": ["test@example.com"], "smtp_host": "mail.example.com"}
        )

        with patch("asyncio.to_thread", new=AsyncMock(return_value=expected)):
            provider = SMTPChannelProvider()
            result = await provider.send(
                recipients=["test@example.com"],
                subject="Hello",
                body="Test body",
                properties={
                    "smtp_host": "mail.example.com",
                    "smtp_port": "587",
                    "smtp_username": "user@example.com",
                    "smtp_password": "secret",
                    "from_address": "noreply@example.com",
                    "use_tls": "true",
                },
            )

        assert result.success is True
        assert result.metadata is not None
        assert "smtp_host" in result.metadata

    @pytest.mark.asyncio
    async def test_send_no_recipients_returns_failure(self):
        """_send_sync returns failure when recipients list is empty."""
        from app.services.notifications.providers.smtp import SMTPChannelProvider

        provider = SMTPChannelProvider()
        # Call _send_sync directly to test the guard without asyncio.to_thread
        result = provider._send_sync(
            recipients=[],
            subject="Hello",
            body="Test body",
            properties={},
        )

        assert result.success is False
        assert "No recipients" in (result.error or "")

    @pytest.mark.asyncio
    async def test_send_exception_returns_failure(self):
        """send() catches exceptions and returns a failure result."""
        from app.services.notifications.providers.smtp import SMTPChannelProvider

        with patch("asyncio.to_thread", new=AsyncMock(side_effect=Exception("SMTP connection failed"))):
            provider = SMTPChannelProvider()
            result = await provider.send(
                recipients=["user@example.com"],
                subject="Hello",
                body="Body",
                properties={"smtp_host": "bad.host"},
            )

        assert result.success is False
        assert "SMTP connection failed" in (result.error or "")

    def test_send_sync_uses_tls_when_use_tls_true(self):
        """_send_sync calls smtp.starttls() when use_tls is 'true'."""
        from app.services.notifications.providers.smtp import SMTPChannelProvider
        import smtplib

        mock_smtp = MagicMock(spec=smtplib.SMTP)
        mock_smtp.sendmail = MagicMock()
        mock_smtp.quit = MagicMock()

        with patch("smtplib.SMTP", return_value=mock_smtp):
            provider = SMTPChannelProvider()
            result = provider._send_sync(
                recipients=["to@example.com"],
                subject="Subject",
                body="Body",
                properties={
                    "smtp_host": "smtp.example.com",
                    "smtp_port": "587",
                    "smtp_username": "user",
                    "smtp_password": "pass",
                    "from_address": "from@example.com",
                    "use_tls": "true",
                },
            )

        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once_with("user", "pass")
        mock_smtp.sendmail.assert_called_once()
        assert result.success is True

    def test_send_sync_skips_tls_when_use_tls_false(self):
        """_send_sync does NOT call smtp.starttls() when use_tls is 'false'."""
        from app.services.notifications.providers.smtp import SMTPChannelProvider
        import smtplib

        mock_smtp = MagicMock(spec=smtplib.SMTP)
        mock_smtp.sendmail = MagicMock()
        mock_smtp.quit = MagicMock()

        with patch("smtplib.SMTP", return_value=mock_smtp):
            provider = SMTPChannelProvider()
            provider._send_sync(
                recipients=["to@example.com"],
                subject="Subject",
                body="Body",
                properties={
                    "use_tls": "false",
                    "from_address": "from@example.com",
                },
            )

        mock_smtp.starttls.assert_not_called()

    def test_send_sync_uses_from_address_from_username_fallback(self):
        """_send_sync uses smtp_username as from_address when from_address is absent."""
        from app.services.notifications.providers.smtp import SMTPChannelProvider
        import smtplib

        captured_sendmail_args: list = []

        mock_smtp = MagicMock(spec=smtplib.SMTP)
        mock_smtp.sendmail.side_effect = lambda f, t, msg: captured_sendmail_args.extend([f, t])
        mock_smtp.quit = MagicMock()

        with patch("smtplib.SMTP", return_value=mock_smtp):
            provider = SMTPChannelProvider()
            provider._send_sync(
                recipients=["to@example.com"],
                subject="Subject",
                body="Body",
                properties={
                    "smtp_username": "auto@example.com",
                    "use_tls": "false",
                },
            )

        # from_address should have fallen back to smtp_username
        assert captured_sendmail_args[0] == "auto@example.com"


# ── SendGrid Provider ────────────────────────────────────────────────────────


class TestSendGridChannelProvider:
    """Tests for SendGridChannelProvider."""

    @pytest.mark.asyncio
    async def test_sendgrid_payload_format(self):
        """SendGrid provider builds 'personalizations' payload and Bearer token header."""
        from app.services.notifications.providers.sendgrid import SendGridChannelProvider

        captured_request: dict = {}

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.status_code = 202

        async def mock_post(url, json=None, headers=None, **kwargs):
            captured_request["json"] = json
            captured_request["headers"] = headers
            return mock_response

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            provider = SendGridChannelProvider()
            result = await provider.send(
                recipients=["user@example.com"],
                subject="Test Subject",
                body="Test body",
                properties={
                    "api_key": "SG.test-key",
                    "from_address": "sender@example.com",
                    "from_name": "Test Sender",
                },
            )

        assert result.success is True
        payload = captured_request["json"]
        assert "personalizations" in payload
        assert payload["personalizations"][0]["to"][0]["email"] == "user@example.com"
        assert payload["from"]["email"] == "sender@example.com"
        assert payload["from"]["name"] == "Test Sender"
        assert captured_request["headers"]["Authorization"] == "Bearer SG.test-key"

    @pytest.mark.asyncio
    async def test_sendgrid_missing_api_key_returns_failure(self):
        """send() returns failure immediately when api_key is absent."""
        from app.services.notifications.providers.sendgrid import SendGridChannelProvider

        provider = SendGridChannelProvider()
        result = await provider.send(
            recipients=["user@example.com"],
            subject="Subject",
            body="Body",
            properties={"from_address": "sender@example.com"},  # no api_key
        )

        assert result.success is False
        assert "api_key" in (result.error or "")

    @pytest.mark.asyncio
    async def test_sendgrid_missing_from_address_returns_failure(self):
        """send() returns failure when from_address is absent."""
        from app.services.notifications.providers.sendgrid import SendGridChannelProvider

        provider = SendGridChannelProvider()
        result = await provider.send(
            recipients=["user@example.com"],
            subject="Subject",
            body="Body",
            properties={"api_key": "SG.key"},  # no from_address
        )

        assert result.success is False
        assert "from_address" in (result.error or "")

    @pytest.mark.asyncio
    async def test_sendgrid_no_recipients_returns_failure(self):
        """send() returns failure when recipients list is empty."""
        from app.services.notifications.providers.sendgrid import SendGridChannelProvider

        provider = SendGridChannelProvider()
        result = await provider.send(
            recipients=[],
            subject="Subject",
            body="Body",
            properties={"api_key": "SG.key", "from_address": "sender@example.com"},
        )

        assert result.success is False
        assert "No recipients" in (result.error or "")

    @pytest.mark.asyncio
    async def test_sendgrid_http_error_response_returns_failure(self):
        """send() returns failure when SendGrid API returns a non-success HTTP status."""
        from app.services.notifications.providers.sendgrid import SendGridChannelProvider

        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            provider = SendGridChannelProvider()
            result = await provider.send(
                recipients=["user@example.com"],
                subject="Subject",
                body="Body",
                properties={"api_key": "SG.key", "from_address": "sender@example.com"},
            )

        assert result.success is False
        assert "401" in (result.error or "")


# ── Resend Provider ──────────────────────────────────────────────────────────


class TestResendChannelProvider:
    """Tests for ResendChannelProvider."""

    @pytest.mark.asyncio
    async def test_resend_payload_format(self):
        """Resend provider builds flat 'from'/'to'/'text' payload."""
        from app.services.notifications.providers.resend import ResendChannelProvider

        captured_request: dict = {}

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.status_code = 200

        async def mock_post(url, json=None, headers=None, **kwargs):
            captured_request["json"] = json
            captured_request["headers"] = headers
            return mock_response

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            provider = ResendChannelProvider()
            result = await provider.send(
                recipients=["user@example.com", "admin@example.com"],
                subject="Resend Subject",
                body="Resend body",
                properties={
                    "api_key": "re_test-key",
                    "from_address": "noreply@example.com",
                },
            )

        assert result.success is True
        payload = captured_request["json"]
        assert payload["from"] == "noreply@example.com"
        assert "user@example.com" in payload["to"]
        assert "admin@example.com" in payload["to"]
        assert payload["text"] == "Resend body"
        assert captured_request["headers"]["Authorization"] == "Bearer re_test-key"

    @pytest.mark.asyncio
    async def test_resend_missing_api_key_returns_failure(self):
        """send() returns failure when api_key is absent."""
        from app.services.notifications.providers.resend import ResendChannelProvider

        provider = ResendChannelProvider()
        result = await provider.send(
            recipients=["user@example.com"],
            subject="Subject",
            body="Body",
            properties={"from_address": "sender@example.com"},  # no api_key
        )

        assert result.success is False
        assert "api_key" in (result.error or "")

    @pytest.mark.asyncio
    async def test_resend_missing_from_address_returns_failure(self):
        """send() returns failure when from_address is absent."""
        from app.services.notifications.providers.resend import ResendChannelProvider

        provider = ResendChannelProvider()
        result = await provider.send(
            recipients=["user@example.com"],
            subject="Subject",
            body="Body",
            properties={"api_key": "re_key"},  # no from_address
        )

        assert result.success is False
        assert "from_address" in (result.error or "")

    @pytest.mark.asyncio
    async def test_resend_http_error_returns_failure(self):
        """send() returns failure when Resend API returns non-success status."""
        from app.services.notifications.providers.resend import ResendChannelProvider

        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 403
        mock_response.text = "Forbidden"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            provider = ResendChannelProvider()
            result = await provider.send(
                recipients=["user@example.com"],
                subject="Subject",
                body="Body",
                properties={"api_key": "re_key", "from_address": "sender@example.com"},
            )

        assert result.success is False
        assert "403" in (result.error or "")


# ── Teams Webhook Provider ───────────────────────────────────────────────────


class TestTeamsWebhookChannelProvider:
    """Tests for TeamsWebhookChannelProvider."""

    @pytest.mark.asyncio
    async def test_teams_adaptive_card_payload(self):
        """send() builds a Teams Adaptive Card payload with title and body."""
        from app.services.notifications.providers.teams_webhook import TeamsWebhookChannelProvider

        captured_payload: dict = {}

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.status_code = 200

        async def mock_post(url, json=None, headers=None, **kwargs):
            captured_payload.update(json or {})
            return mock_response

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            provider = TeamsWebhookChannelProvider()
            result = await provider.send(
                recipients=[],
                subject="Alert Title",
                body="Alert body text",
                properties={"webhook_url": "https://outlook.office.com/webhook/xxx"},
            )

        assert result.success is True
        assert captured_payload["type"] == "message"
        assert "attachments" in captured_payload
        card_content = captured_payload["attachments"][0]["content"]
        assert card_content["type"] == "AdaptiveCard"
        assert card_content["body"][0]["text"] == "Alert Title"
        assert card_content["body"][1]["text"] == "Alert body text"

    @pytest.mark.asyncio
    async def test_teams_missing_webhook_url_returns_failure(self):
        """send() returns failure when webhook_url is absent."""
        from app.services.notifications.providers.teams_webhook import TeamsWebhookChannelProvider

        provider = TeamsWebhookChannelProvider()
        result = await provider.send(
            recipients=[],
            subject="Subject",
            body="Body",
            properties={},  # no webhook_url
        )

        assert result.success is False
        assert "webhook_url" in (result.error or "")

    @pytest.mark.asyncio
    async def test_teams_http_error_returns_failure(self):
        """send() returns failure when Teams webhook returns non-success status."""
        from app.services.notifications.providers.teams_webhook import TeamsWebhookChannelProvider

        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            provider = TeamsWebhookChannelProvider()
            result = await provider.send(
                recipients=[],
                subject="Subject",
                body="Body",
                properties={"webhook_url": "https://outlook.office.com/webhook/xxx"},
            )

        assert result.success is False
        assert "400" in (result.error or "")


# ── Slack Webhook Provider ────────────────────────────────────────────────────


class TestSlackWebhookChannelProvider:
    """Tests for SlackWebhookChannelProvider."""

    @pytest.mark.asyncio
    async def test_slack_block_kit_payload(self):
        """send() builds a Slack Block Kit payload with header and section."""
        from app.services.notifications.providers.slack_webhook import SlackWebhookChannelProvider

        captured_payload: dict = {}

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.status_code = 200

        async def mock_post(url, json=None, headers=None, **kwargs):
            captured_payload.update(json or {})
            return mock_response

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            provider = SlackWebhookChannelProvider()
            result = await provider.send(
                recipients=[],
                subject="Deployment Complete",
                body="Version 1.2.3 deployed successfully",
                properties={"webhook_url": "https://hooks.slack.com/services/xxx"},
            )

        assert result.success is True
        assert "blocks" in captured_payload
        blocks = captured_payload["blocks"]
        assert blocks[0]["type"] == "header"
        assert blocks[0]["text"]["text"] == "Deployment Complete"
        assert blocks[1]["type"] == "section"
        assert blocks[1]["text"]["text"] == "Version 1.2.3 deployed successfully"
        assert captured_payload["text"] == "Deployment Complete"  # Fallback text

    @pytest.mark.asyncio
    async def test_slack_missing_webhook_url_returns_failure(self):
        """send() returns failure when webhook_url is absent."""
        from app.services.notifications.providers.slack_webhook import SlackWebhookChannelProvider

        provider = SlackWebhookChannelProvider()
        result = await provider.send(
            recipients=[],
            subject="Subject",
            body="Body",
            properties={},  # no webhook_url
        )

        assert result.success is False
        assert "webhook_url" in (result.error or "")

    @pytest.mark.asyncio
    async def test_slack_http_error_returns_failure(self):
        """send() returns failure when Slack webhook returns non-success status."""
        from app.services.notifications.providers.slack_webhook import SlackWebhookChannelProvider

        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            provider = SlackWebhookChannelProvider()
            result = await provider.send(
                recipients=[],
                subject="Subject",
                body="Body",
                properties={"webhook_url": "https://hooks.slack.com/services/xxx"},
            )

        assert result.success is False
        assert "500" in (result.error or "")

    @pytest.mark.asyncio
    async def test_slack_no_subject_uses_fallback(self):
        """send() with no subject still creates valid payload."""
        from app.services.notifications.providers.slack_webhook import SlackWebhookChannelProvider

        captured_payload: dict = {}

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.status_code = 200

        async def mock_post(url, json=None, headers=None, **kwargs):
            captured_payload.update(json or {})
            return mock_response

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            provider = SlackWebhookChannelProvider()
            result = await provider.send(
                recipients=[],
                subject=None,
                body="Just a body message",
                properties={"webhook_url": "https://hooks.slack.com/services/xxx"},
            )

        assert result.success is True
        assert "blocks" in captured_payload
        blocks = captured_payload["blocks"]
        # Should have only section block (no header when subject is None)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "section"
        assert captured_payload["text"] == "Just a body message"  # Fallback to body
