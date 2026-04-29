"""
Test NotificationDispatcher: dispatch() creates a NotificationEvent and attempts delivery.
Also verifies MCP_TOOLS definitions contain all four channel types.
"""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_notification_dispatcher_creates_event_on_dispatch():
    """NotificationDispatcher.dispatch() adds a NotificationEvent to the DB."""
    from app.services.notifications.dispatcher import NotificationDispatcher
    from app.db.models.notifications import ChannelType, DeliveryStatus, NotificationChannel, NotificationEvent

    channel = MagicMock(spec=NotificationChannel)
    channel.id = uuid.uuid4()
    channel.channel_type = ChannelType.webhook
    channel.encrypted_config = None  # no config

    event = MagicMock(spec=NotificationEvent)
    event.id = uuid.uuid4()
    event.status = DeliveryStatus.pending

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()

    with patch("app.services.notifications.dispatcher.NotificationEvent", return_value=event):
        with patch.object(NotificationDispatcher, "_send_webhook", new=AsyncMock()):
            dispatcher = NotificationDispatcher()
            result = await dispatcher.dispatch(
                channel=channel,
                subject="Test",
                body="Hello from test",
                recipient="https://webhook.example.com",
                db=mock_db,
            )

    mock_db.add.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_notification_dispatcher_webhook_makes_http_call():
    """NotificationDispatcher._send_webhook() posts to the configured webhook URL."""
    from app.services.notifications.dispatcher import NotificationDispatcher

    dispatcher = NotificationDispatcher()
    config = {"url": "https://webhook.example.com/hook"}  # uses "url" key per implementation
    body = "Test notification body"

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_http.request = AsyncMock(return_value=mock_response)

        await dispatcher._send_webhook(config, body, recipient=None)

    mock_http.request.assert_called_once()
    call_url = mock_http.request.call_args[0][1]
    assert call_url == "https://webhook.example.com/hook"


def test_notification_dispatcher_mcp_tools_cover_all_channels():
    """NotificationDispatcher.MCP_TOOLS has definitions for email, slack, teams, webhook."""
    from app.services.notifications.dispatcher import NotificationDispatcher

    tool_names = {t["name"] for t in NotificationDispatcher.MCP_TOOLS}
    assert "notify_email" in tool_names
    assert "notify_slack" in tool_names
    assert "notify_teams" in tool_names
    assert "notify_webhook" in tool_names
