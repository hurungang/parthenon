"""Unit tests for notification MCP tool handlers.

Tests for handle_send_notification:
  - Missing group_slug returns error dict (no exception)
  - Missing body returns error dict
  - Invalid/unknown group_slug returns error dict (ValueError from service)
  - Successful send returns delivery summary with correct keys
  - source_type=AGENT is always used regardless of caller
  - source_id extracted from caller_identity.agent_id
  - source_id extracted from caller_identity.sub when agent_id absent
  - Unexpected service exception returns error dict

Tests for handle_get_recipient_group:
  - Missing group_slug returns error dict
  - Unknown group_slug returns error dict
  - Successful retrieval returns group details and channel list
  - Unexpected exception returns error dict
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_db_session():
    """Minimal async session mock."""
    return AsyncMock()


class TestHandleSendNotification:
    """Tests for mcp_tool.handle_send_notification."""

    @pytest.mark.asyncio
    async def test_missing_group_slug_returns_error(self, mock_db_session):
        """Returns {'error': ...} when group_slug is absent from args."""
        from app.services.notifications.mcp_tool import handle_send_notification

        result = await handle_send_notification(
            args={"body": "Hello"},
            db_session=mock_db_session,
        )

        assert "error" in result
        assert "group_slug" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_body_returns_error(self, mock_db_session):
        """Returns {'error': ...} when body is absent from args."""
        from app.services.notifications.mcp_tool import handle_send_notification

        result = await handle_send_notification(
            args={"group_slug": "ops-alerts"},
            db_session=mock_db_session,
        )

        assert "error" in result
        assert "body" in result["error"]

    @pytest.mark.asyncio
    async def test_unknown_group_slug_returns_error(self, mock_db_session):
        """Returns {'error': ...} when NotificationService raises ValueError (group not found)."""
        from app.services.notifications.mcp_tool import handle_send_notification

        with patch(
            "app.services.notifications.mcp_tool.NotificationService"
        ) as MockService:
            instance = MockService.return_value
            instance.send_to_group = AsyncMock(
                side_effect=ValueError("Recipient group 'nonexistent' not found")
            )

            result = await handle_send_notification(
                args={"group_slug": "nonexistent", "body": "Alert"},
                db_session=mock_db_session,
            )

        assert "error" in result
        assert "nonexistent" in result["error"]

    @pytest.mark.asyncio
    async def test_successful_send_returns_summary(self, mock_db_session):
        """Returns summary dict with channels_attempted, channels_delivered, log_ids on success."""
        from app.services.notifications.mcp_tool import handle_send_notification
        from app.services.notifications.notification_service import GroupSendResult
        from app.services.notifications.providers.base import ChannelDeliveryResult

        log_id = uuid.uuid4()
        mock_result = GroupSendResult(
            group_slug="ops-alerts",
            log_ids=[log_id],
            channel_results=[ChannelDeliveryResult(success=True)],
        )

        with patch(
            "app.services.notifications.mcp_tool.NotificationService"
        ) as MockService:
            instance = MockService.return_value
            instance.send_to_group = AsyncMock(return_value=mock_result)

            result = await handle_send_notification(
                args={"group_slug": "ops-alerts", "body": "All good"},
                db_session=mock_db_session,
            )

        assert "channels_attempted" in result
        assert "channels_delivered" in result
        assert "channels_failed" in result
        assert "log_ids" in result
        assert result["channels_attempted"] == 1
        assert result["channels_delivered"] == 1
        assert result["channels_failed"] == 0
        assert str(log_id) in result["log_ids"]

    @pytest.mark.asyncio
    async def test_source_type_agent_always_used(self, mock_db_session):
        """handle_send_notification always passes SourceType.AGENT to send_to_group."""
        from app.services.notifications.mcp_tool import handle_send_notification
        from app.services.notifications.notification_service import GroupSendResult
        from app.db.models.notifications import SourceType

        mock_result = GroupSendResult(
            group_slug="ops-alerts",
            log_ids=[],
            channel_results=[],
        )

        with patch(
            "app.services.notifications.mcp_tool.NotificationService"
        ) as MockService:
            instance = MockService.return_value
            instance.send_to_group = AsyncMock(return_value=mock_result)

            await handle_send_notification(
                args={"group_slug": "ops-alerts", "body": "Message"},
                db_session=mock_db_session,
                caller_identity={"sub": "agent-user-id"},
            )

            call_kwargs = instance.send_to_group.call_args.kwargs
            assert call_kwargs["source_type"] == SourceType.AGENT

    @pytest.mark.asyncio
    async def test_source_id_from_agent_id_in_caller_identity(self, mock_db_session):
        """source_id is derived from caller_identity.agent_id when present."""
        from app.services.notifications.mcp_tool import handle_send_notification
        from app.services.notifications.notification_service import GroupSendResult

        agent_id = uuid.uuid4()
        mock_result = GroupSendResult(
            group_slug="ops-alerts",
            log_ids=[],
            channel_results=[],
        )

        with patch(
            "app.services.notifications.mcp_tool.NotificationService"
        ) as MockService:
            instance = MockService.return_value
            instance.send_to_group = AsyncMock(return_value=mock_result)

            await handle_send_notification(
                args={"group_slug": "ops-alerts", "body": "Message"},
                db_session=mock_db_session,
                caller_identity={"agent_id": str(agent_id), "sub": "other-sub"},
            )

            call_kwargs = instance.send_to_group.call_args.kwargs
            assert call_kwargs["source_id"] == agent_id

    @pytest.mark.asyncio
    async def test_source_id_falls_back_to_sub(self, mock_db_session):
        """source_id is derived from caller_identity.sub when agent_id is absent."""
        from app.services.notifications.mcp_tool import handle_send_notification
        from app.services.notifications.notification_service import GroupSendResult

        sub_id = uuid.uuid4()
        mock_result = GroupSendResult(
            group_slug="ops-alerts",
            log_ids=[],
            channel_results=[],
        )

        with patch(
            "app.services.notifications.mcp_tool.NotificationService"
        ) as MockService:
            instance = MockService.return_value
            instance.send_to_group = AsyncMock(return_value=mock_result)

            await handle_send_notification(
                args={"group_slug": "ops-alerts", "body": "Message"},
                db_session=mock_db_session,
                caller_identity={"sub": str(sub_id)},
            )

            call_kwargs = instance.send_to_group.call_args.kwargs
            assert call_kwargs["source_id"] == sub_id

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_error(self, mock_db_session):
        """Unexpected exceptions from send_to_group are caught and returned as error dict."""
        from app.services.notifications.mcp_tool import handle_send_notification

        with patch(
            "app.services.notifications.mcp_tool.NotificationService"
        ) as MockService:
            instance = MockService.return_value
            instance.send_to_group = AsyncMock(
                side_effect=RuntimeError("Database connection lost")
            )

            result = await handle_send_notification(
                args={"group_slug": "ops-alerts", "body": "Alert"},
                db_session=mock_db_session,
            )

        assert "error" in result

    @pytest.mark.asyncio
    async def test_partial_failure_counts_correctly(self, mock_db_session):
        """channels_failed count matches the number of failed channel results."""
        from app.services.notifications.mcp_tool import handle_send_notification
        from app.services.notifications.notification_service import GroupSendResult
        from app.services.notifications.providers.base import ChannelDeliveryResult

        mock_result = GroupSendResult(
            group_slug="ops-alerts",
            log_ids=[uuid.uuid4(), uuid.uuid4(), uuid.uuid4()],
            channel_results=[
                ChannelDeliveryResult(success=True),
                ChannelDeliveryResult(success=False, error="Timeout"),
                ChannelDeliveryResult(success=True),
            ],
        )

        with patch(
            "app.services.notifications.mcp_tool.NotificationService"
        ) as MockService:
            instance = MockService.return_value
            instance.send_to_group = AsyncMock(return_value=mock_result)

            result = await handle_send_notification(
                args={"group_slug": "ops-alerts", "body": "Alert"},
                db_session=mock_db_session,
            )

        assert result["channels_attempted"] == 3
        assert result["channels_delivered"] == 2
        assert result["channels_failed"] == 1


class TestHandleGetRecipientGroup:
    """Tests for mcp_tool.handle_get_recipient_group."""

    @pytest.mark.asyncio
    async def test_missing_group_slug_returns_error(self, mock_db_session):
        """Returns {'error': ...} when group_slug is absent from args."""
        from app.services.notifications.mcp_tool import handle_get_recipient_group

        result = await handle_get_recipient_group(
            args={},
            db_session=mock_db_session,
        )

        assert "error" in result
        assert "group_slug" in result["error"]

    @pytest.mark.asyncio
    async def test_unknown_group_slug_returns_error(self, mock_db_session):
        """Returns {'error': ...} when group is not found in database."""
        from app.services.notifications.mcp_tool import handle_get_recipient_group

        # Mock db.execute to return empty result
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await handle_get_recipient_group(
            args={"group_slug": "nonexistent"},
            db_session=mock_db_session,
        )

        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_successful_retrieval_returns_group_details(self, mock_db_session):
        """Returns group details with channel list when group exists."""
        from app.services.notifications.mcp_tool import handle_get_recipient_group
        from app.db.models.notifications import RecipientGroup, ChannelType

        # Create mock group with channel mappings
        mock_channel1 = MagicMock()
        mock_channel1.id = uuid.uuid4()
        mock_channel1.name = "Email Channel"
        mock_channel1.channel_type = ChannelType.SENDGRID

        mock_channel2 = MagicMock()
        mock_channel2.id = uuid.uuid4()
        mock_channel2.name = "Slack Channel"
        mock_channel2.channel_type = ChannelType.SLACK_WEBHOOK

        mock_mapping1 = MagicMock()
        mock_mapping1.channel = mock_channel1
        mock_mapping1.recipient_properties = {"recipients": ["user@example.com"]}

        mock_mapping2 = MagicMock()
        mock_mapping2.channel = mock_channel2
        mock_mapping2.recipient_properties = {"channel_id": "C123456"}

        mock_group = MagicMock(spec=RecipientGroup)
        mock_group.slug = "ops-alerts"
        mock_group.name = "Operations Alerts"
        mock_group.description = "Alert group for ops team"
        mock_group.is_active = True
        mock_group.channel_mappings = [mock_mapping1, mock_mapping2]

        # Mock db.execute to return the group
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_group
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await handle_get_recipient_group(
            args={"group_slug": "ops-alerts"},
            db_session=mock_db_session,
        )

        assert "error" not in result
        assert result["group_slug"] == "ops-alerts"
        assert result["group_name"] == "Operations Alerts"
        assert result["description"] == "Alert group for ops team"
        assert result["is_active"] is True
        assert len(result["channels"]) == 2

        # Verify channel details
        channel1 = result["channels"][0]
        assert channel1["channel_name"] == "Email Channel"
        assert channel1["channel_type"] == "SENDGRID"
        assert channel1["recipient_properties"] == {"recipients": ["user@example.com"]}

        channel2 = result["channels"][1]
        assert channel2["channel_name"] == "Slack Channel"
        assert channel2["channel_type"] == "SLACK_WEBHOOK"
        assert channel2["recipient_properties"] == {"channel_id": "C123456"}

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_error(self, mock_db_session):
        """Unexpected exceptions from database query are caught and returned as error dict."""
        from app.services.notifications.mcp_tool import handle_get_recipient_group

        mock_db_session.execute = AsyncMock(
            side_effect=RuntimeError("Database connection lost")
        )

        result = await handle_get_recipient_group(
            args={"group_slug": "ops-alerts"},
            db_session=mock_db_session,
        )

        assert "error" in result
        assert "Failed to retrieve group" in result["error"]

