"""Abstract base class for notification channel providers."""
from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass
class ChannelDeliveryResult:
    """Typed result returned by all channel providers after a send attempt."""

    success: bool
    error: str | None = None
    metadata: dict | None = None


class BaseChannelProvider(abc.ABC):
    """
    Contract that all concrete notification channel providers must implement.

    A provider is responsible for dispatching a notification to one or more
    recipients via its specific transport (SMTP, REST API, webhook, messenger).
    """

    @abc.abstractmethod
    async def send(
        self,
        recipients: list[str],
        subject: str | None,
        body: str,
        properties: dict[str, str],
    ) -> ChannelDeliveryResult:
        """
        Send a notification to the given recipients.

        Args:
            recipients: List of destination addresses (email, webhook URL, etc.).
            subject: Optional subject line.
            body: Notification body text.
            properties: Decrypted channel property key-value pairs.

        Returns:
            ChannelDeliveryResult with success flag, optional error, and metadata.
        """
