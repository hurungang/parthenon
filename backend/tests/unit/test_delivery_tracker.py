"""Unit tests for DeliveryTracker.

Tests:
  - record() with delivered status sets delivered_at and logs info
  - record() with failed status does not set delivered_at and logs warning
  - OTEL counter incremented with correct channel_type and status labels
  - Error detail passed through when status is failed
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.db.models.notifications import DeliveryStatus


class TestDeliveryTracker:
    """Tests for DeliveryTracker.record()."""

    def _make_tracker(self):
        """Build a DeliveryTracker with a mocked repository."""
        from app.services.notifications.delivery_tracker import DeliveryTracker

        mock_repo = AsyncMock()
        mock_repo.update_log_status = AsyncMock()
        tracker = DeliveryTracker(mock_repo)
        return tracker, mock_repo

    @pytest.mark.asyncio
    async def test_update_log_status_called_with_delivered(self):
        """record() calls update_log_status with delivered status and sets delivered_at."""
        tracker, mock_repo = self._make_tracker()
        log_id = uuid.uuid4()

        await tracker.record(
            log_id=log_id,
            channel_type="TEAMS_WEBHOOK",
            status=DeliveryStatus.delivered,
        )

        mock_repo.update_log_status.assert_awaited_once()
        call_kwargs = mock_repo.update_log_status.call_args.kwargs
        assert call_kwargs["log_id"] == log_id
        assert call_kwargs["status"] == DeliveryStatus.delivered
        assert call_kwargs["delivered_at"] is not None  # must be set for delivered
        assert call_kwargs["error"] is None

    @pytest.mark.asyncio
    async def test_update_log_status_called_with_failed(self):
        """record() calls update_log_status with failed status and no delivered_at."""
        tracker, mock_repo = self._make_tracker()
        log_id = uuid.uuid4()

        await tracker.record(
            log_id=log_id,
            channel_type="SMTP",
            status=DeliveryStatus.failed,
            error="Connection refused",
        )

        call_kwargs = mock_repo.update_log_status.call_args.kwargs
        assert call_kwargs["status"] == DeliveryStatus.failed
        assert call_kwargs["delivered_at"] is None  # must NOT be set for failed
        assert call_kwargs["error"] == "Connection refused"

    @pytest.mark.asyncio
    async def test_otel_counter_incremented(self):
        """record() adds 1 to the OTEL counter with correct attributes."""
        tracker, _ = self._make_tracker()

        with patch(
            "app.services.notifications.delivery_tracker._sent_counter"
        ) as mock_counter:
            await tracker.record(
                log_id=uuid.uuid4(),
                channel_type="SENDGRID",
                status=DeliveryStatus.delivered,
            )

        mock_counter.add.assert_called_once_with(
            1,
            attributes={
                "channel_type": "SENDGRID",
                "status": DeliveryStatus.delivered.value,
            },
        )

    @pytest.mark.asyncio
    async def test_otel_counter_incremented_for_failed(self):
        """record() increments counter with failed status label."""
        tracker, _ = self._make_tracker()

        with patch(
            "app.services.notifications.delivery_tracker._sent_counter"
        ) as mock_counter:
            await tracker.record(
                log_id=uuid.uuid4(),
                channel_type="SLACK_WEBHOOK",
                status=DeliveryStatus.failed,
                error="Timeout",
            )

        call_attrs = mock_counter.add.call_args[1]["attributes"]
        assert call_attrs["status"] == "failed"

    @pytest.mark.asyncio
    async def test_metadata_passed_through_to_repo(self):
        """record() forwards metadata dict to update_log_status."""
        tracker, mock_repo = self._make_tracker()
        metadata = {"status_code": 200, "attempts": 1}

        await tracker.record(
            log_id=uuid.uuid4(),
            channel_type="TEAMS_WEBHOOK",
            status=DeliveryStatus.delivered,
            metadata=metadata,
        )

        call_kwargs = mock_repo.update_log_status.call_args.kwargs
        assert call_kwargs["metadata"] == metadata

    @pytest.mark.asyncio
    async def test_logger_info_called_on_delivered(self):
        """record() calls logger.info (not logger.warning) on delivered status."""
        tracker, _ = self._make_tracker()

        with patch("app.services.notifications.delivery_tracker.logger") as mock_logger:
            await tracker.record(
                log_id=uuid.uuid4(),
                channel_type="SMTP",
                status=DeliveryStatus.delivered,
            )

        mock_logger.info.assert_called_once()
        mock_logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_logger_warning_called_on_failed(self):
        """record() calls logger.warning (not logger.info) on failed status."""
        tracker, _ = self._make_tracker()

        with patch("app.services.notifications.delivery_tracker.logger") as mock_logger:
            await tracker.record(
                log_id=uuid.uuid4(),
                channel_type="SLACK_WEBHOOK",
                status=DeliveryStatus.failed,
                error="HTTP 503",
            )

        mock_logger.warning.assert_called_once()
        mock_logger.info.assert_not_called()
