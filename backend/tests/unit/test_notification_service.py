"""Unit tests for NotificationService orchestration logic.

Tests:
  - send_to_group: group not found, inactive group, dispatches all active channels
  - send_to_group: partial failure — continues to remaining channels
  - send_to_group: skips inactive channels
  - test_channel: channel not found, success path
  - _load_decrypted_properties: success, decrypt error falls back to empty string
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.notifications import ChannelType, DeliveryStatus, SourceType


def _make_channel(channel_type=ChannelType.TEAMS_WEBHOOK, is_active=True):
    """Create a mock NotificationChannel ORM object."""
    ch = MagicMock()
    ch.id = uuid.uuid4()
    ch.channel_type = channel_type
    ch.is_active = is_active
    ch.name = f"{channel_type.value}-channel"
    return ch


def _make_mapping(channel=None):
    """Create a mock GroupChannelMapping ORM object."""
    mapping = MagicMock()
    mapping.channel = channel or _make_channel()
    return mapping


def _make_group(slug="test-group", is_active=True, mappings=None):
    """Create a mock RecipientGroup ORM object."""
    g = MagicMock()
    g.id = uuid.uuid4()
    g.slug = slug
    g.is_active = is_active
    g.channel_mappings = mappings or []
    return g


def _make_log(log_id=None):
    """Create a mock NotificationLog ORM object."""
    log = MagicMock()
    log.id = log_id or uuid.uuid4()
    return log


def _make_service_with_mocks(group=None, log=None):
    """
    Build a NotificationService with all internal dependencies mocked.

    Returns (service, mock_repo, mock_tracker, mock_vault).
    """
    from app.services.notifications.notification_service import NotificationService

    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_tracker = AsyncMock()
    mock_vault = MagicMock()

    if group is not None:
        mock_repo.get_recipient_group_by_slug = AsyncMock(return_value=group)
    else:
        mock_repo.get_recipient_group_by_slug = AsyncMock(return_value=None)

    mock_repo.create_notification_log = AsyncMock(return_value=log or _make_log())
    mock_repo.get_channel_properties = AsyncMock(return_value=[])

    with (
        patch(
            "app.services.notifications.notification_service.NotificationRepository",
            return_value=mock_repo,
        ),
        patch(
            "app.services.notifications.notification_service.DeliveryTracker",
            return_value=mock_tracker,
        ),
        patch(
            "app.services.notifications.notification_service.get_vault",
            return_value=mock_vault,
        ),
    ):
        svc = NotificationService(mock_session)

    svc._repo = mock_repo
    svc._tracker = mock_tracker
    svc._vault = mock_vault
    return svc, mock_repo, mock_tracker, mock_vault


# ── send_to_group ─────────────────────────────────────────────────────────────


class TestSendToGroup:
    """Tests for NotificationService.send_to_group."""

    @pytest.mark.asyncio
    async def test_raises_value_error_when_group_not_found(self):
        """send_to_group raises ValueError when the group slug does not exist."""
        svc, mock_repo, _, _ = _make_service_with_mocks(group=None)

        with pytest.raises(ValueError, match="not found"):
            await svc.send_to_group("nonexistent-slug", "body")

    @pytest.mark.asyncio
    async def test_raises_value_error_when_group_inactive(self):
        """send_to_group raises ValueError when the group is inactive."""
        inactive_group = _make_group(is_active=False)
        svc, mock_repo, _, _ = _make_service_with_mocks(group=inactive_group)

        with pytest.raises(ValueError, match="inactive"):
            await svc.send_to_group(inactive_group.slug, "body")

    @pytest.mark.asyncio
    async def test_dispatches_to_all_active_channels(self):
        """send_to_group dispatches a notification to all active channels in the group."""
        ch1 = _make_channel(channel_type=ChannelType.TEAMS_WEBHOOK, is_active=True)
        ch2 = _make_channel(channel_type=ChannelType.SLACK_WEBHOOK, is_active=True)
        group = _make_group(mappings=[_make_mapping(ch1), _make_mapping(ch2)])

        log1, log2 = _make_log(), _make_log()

        svc, mock_repo, mock_tracker, _ = _make_service_with_mocks(group=group)
        mock_repo.create_notification_log = AsyncMock(side_effect=[log1, log2])

        from app.services.notifications.providers.base import ChannelDeliveryResult

        with patch.object(
            svc,
            "_dispatch",
            new=AsyncMock(return_value=ChannelDeliveryResult(success=True)),
        ) as mock_dispatch:
            result = await svc.send_to_group(group.slug, "notification body")

        assert mock_dispatch.call_count == 2
        assert len(result.log_ids) == 2
        assert mock_tracker.record.call_count == 2

    @pytest.mark.asyncio
    async def test_continues_to_remaining_channels_after_failure(self):
        """send_to_group continues dispatching to other channels even when one fails."""
        ch1 = _make_channel(channel_type=ChannelType.SMTP, is_active=True)
        ch2 = _make_channel(channel_type=ChannelType.TEAMS_WEBHOOK, is_active=True)
        group = _make_group(mappings=[_make_mapping(ch1), _make_mapping(ch2)])

        log1, log2 = _make_log(), _make_log()

        svc, mock_repo, mock_tracker, _ = _make_service_with_mocks(group=group)
        mock_repo.create_notification_log = AsyncMock(side_effect=[log1, log2])

        from app.services.notifications.providers.base import ChannelDeliveryResult

        side_effects = [
            ChannelDeliveryResult(success=False, error="SMTP timeout"),
            ChannelDeliveryResult(success=True),
        ]
        with patch.object(
            svc,
            "_dispatch",
            new=AsyncMock(side_effect=side_effects),
        ) as mock_dispatch:
            result = await svc.send_to_group(group.slug, "body")

        # Both channels attempted
        assert mock_dispatch.call_count == 2
        # Both logs recorded (one failed, one succeeded)
        assert mock_tracker.record.call_count == 2

        results = result.channel_results
        assert results[0].success is False
        assert results[1].success is True

    @pytest.mark.asyncio
    async def test_skips_inactive_channels(self):
        """send_to_group skips channels that are inactive."""
        active_ch = _make_channel(is_active=True)
        inactive_ch = _make_channel(is_active=False)
        group = _make_group(
            mappings=[_make_mapping(inactive_ch), _make_mapping(active_ch)]
        )

        svc, mock_repo, mock_tracker, _ = _make_service_with_mocks(group=group)
        mock_repo.create_notification_log = AsyncMock(return_value=_make_log())

        from app.services.notifications.providers.base import ChannelDeliveryResult

        with patch.object(
            svc,
            "_dispatch",
            new=AsyncMock(return_value=ChannelDeliveryResult(success=True)),
        ) as mock_dispatch:
            result = await svc.send_to_group(group.slug, "body")

        # Only one dispatch — inactive channel was skipped
        assert mock_dispatch.call_count == 1
        assert len(result.log_ids) == 1

    @pytest.mark.asyncio
    async def test_source_type_agent_recorded(self):
        """send_to_group records SourceType.AGENT in the log when specified."""
        ch = _make_channel(is_active=True)
        group = _make_group(mappings=[_make_mapping(ch)])
        log = _make_log()

        svc, mock_repo, mock_tracker, _ = _make_service_with_mocks(group=group, log=log)

        from app.services.notifications.providers.base import ChannelDeliveryResult

        with patch.object(
            svc, "_dispatch", new=AsyncMock(return_value=ChannelDeliveryResult(success=True))
        ):
            await svc.send_to_group(
                group.slug, "body", source_type=SourceType.AGENT, source_id=uuid.uuid4()
            )

        call_kwargs = mock_repo.create_notification_log.call_args.kwargs
        assert call_kwargs["source_type"] == SourceType.AGENT

    @pytest.mark.asyncio
    async def test_empty_group_returns_no_logs(self):
        """send_to_group with no channels in the group returns empty results."""
        group = _make_group(mappings=[])
        svc, mock_repo, mock_tracker, _ = _make_service_with_mocks(group=group)

        from app.services.notifications.providers.base import ChannelDeliveryResult

        with patch.object(
            svc, "_dispatch", new=AsyncMock(return_value=ChannelDeliveryResult(success=True))
        ) as mock_dispatch:
            result = await svc.send_to_group(group.slug, "body")

        assert result.log_ids == []
        assert mock_dispatch.call_count == 0

    @pytest.mark.asyncio
    async def test_channel_selector_dispatches_only_matching_channel(self):
        """send_to_group(channel=...) dispatches only to matching channel in the group."""
        teams_ch = _make_channel(channel_type=ChannelType.TEAMS_WEBHOOK, is_active=True)
        teams_ch.name = "ops-teams"
        slack_ch = _make_channel(channel_type=ChannelType.SLACK_WEBHOOK, is_active=True)
        slack_ch.name = "ops-slack"
        group = _make_group(mappings=[_make_mapping(teams_ch), _make_mapping(slack_ch)])

        svc, mock_repo, _, _ = _make_service_with_mocks(group=group)
        mock_repo.create_notification_log = AsyncMock(return_value=_make_log())

        from app.services.notifications.providers.base import ChannelDeliveryResult

        with patch.object(
            svc,
            "_dispatch",
            new=AsyncMock(return_value=ChannelDeliveryResult(success=True)),
        ) as mock_dispatch:
            result = await svc.send_to_group(group.slug, "body", channel="ops-teams")

        assert mock_dispatch.call_count == 1
        assert len(result.log_ids) == 1


# ── test_channel ──────────────────────────────────────────────────────────────


class TestTestChannel:
    """Tests for NotificationService.test_channel."""

    @pytest.mark.asyncio
    async def test_returns_failure_when_channel_not_found(self):
        """test_channel returns failure result when channel ID does not exist."""
        svc, mock_repo, _, _ = _make_service_with_mocks()
        mock_repo.get_channel = AsyncMock(return_value=None)

        result = await svc.test_channel(uuid.uuid4(), "test@example.com")

        assert result.success is False
        assert "not found" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_returns_success_when_dispatch_succeeds(self):
        """test_channel returns dispatch result when channel exists."""
        channel = _make_channel(channel_type=ChannelType.TEAMS_WEBHOOK)
        svc, mock_repo, _, _ = _make_service_with_mocks()
        mock_repo.get_channel = AsyncMock(return_value=channel)

        from app.services.notifications.providers.base import ChannelDeliveryResult

        with patch.object(
            svc,
            "_dispatch",
            new=AsyncMock(return_value=ChannelDeliveryResult(success=True)),
        ):
            result = await svc.test_channel(channel.id, "test@example.com")

        assert result.success is True


# ── _load_decrypted_properties ────────────────────────────────────────────────


class TestLoadDecryptedProperties:
    """Tests for NotificationService._load_decrypted_properties."""

    @pytest.mark.asyncio
    async def test_returns_decrypted_dict(self):
        """Properties are decrypted and returned as a plain string dict."""
        prop = MagicMock()
        prop.key = "smtp_host"
        prop.encrypted_value = "ciphertext"

        svc, mock_repo, _, mock_vault = _make_service_with_mocks()
        mock_repo.get_channel_properties = AsyncMock(return_value=[prop])
        mock_vault.decrypt = MagicMock(return_value="mail.example.com")

        result = await svc._load_decrypted_properties(uuid.uuid4())

        assert result == {"smtp_host": "mail.example.com"}

    @pytest.mark.asyncio
    async def test_decrypt_error_falls_back_to_empty_string(self):
        """If decryption fails for a property, its value is replaced with empty string."""
        prop = MagicMock()
        prop.key = "api_key"
        prop.encrypted_value = "bad-ciphertext"

        svc, mock_repo, _, mock_vault = _make_service_with_mocks()
        mock_repo.get_channel_properties = AsyncMock(return_value=[prop])
        mock_vault.decrypt = MagicMock(side_effect=Exception("Decryption error"))

        result = await svc._load_decrypted_properties(uuid.uuid4())

        assert result == {"api_key": ""}

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_no_properties(self):
        """Returns empty dict when channel has no properties."""
        svc, mock_repo, _, _ = _make_service_with_mocks()
        mock_repo.get_channel_properties = AsyncMock(return_value=[])

        result = await svc._load_decrypted_properties(uuid.uuid4())

        assert result == {}
