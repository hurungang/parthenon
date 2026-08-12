"""MCP tool handlers for notifications — exposed via Communication Hub."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.notifications import RecipientGroup, SourceType
from app.services.notifications.notification_service import NotificationService
from app.services.notifications.repository import NotificationRepository

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# MCP tool descriptor for send_notification (used in tools/list response)
SEND_NOTIFICATION_TOOL = {
    "name": "send_notification",
    "description": (
        "Send a notification to a named recipient group. "
        "The group must be configured in the Parthenon notification admin. "
        "Returns a delivery summary for each channel in the group."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "group_slug": {
                "type": "string",
                "description": "Slug of the recipient group to send the notification to.",
            },
            "subject": {
                "type": "string",
                "description": "Optional subject line for email-type channels.",
            },
            "body": {
                "type": "string",
                "description": "Notification body text.",
            },
        },
        "required": ["group_slug", "body"],
    },
}

# MCP tool descriptor for get_recipient_group (used in tools/list response)
GET_RECIPIENT_GROUP_TOOL = {
    "name": "get_recipient_group",
    "description": (
        "Retrieve information about a recipient group, including which channels "
        "are configured and their recipient properties. Use this before sending "
        "notifications to verify the group exists and understand its delivery setup."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "group_slug": {
                "type": "string",
                "description": "Slug of the recipient group to retrieve.",
            },
        },
        "required": ["group_slug"],
    },
}


async def handle_send_notification(
    args: dict[str, Any],
    db_session: AsyncSession,
    caller_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    MCP tool handler for send_notification.

    Calls NotificationService.send_to_group with source_type=AGENT and
    source_id derived from caller_identity.

    Returns a delivery summary dict with:
      - group_slug: str
      - channels_attempted: int
      - channels_delivered: int
      - channels_failed: int
      - log_ids: list[str]
    """
    group_slug: str = args.get("group_slug", "")
    body: str = args.get("body", "")
    subject: str | None = args.get("subject")

    if not group_slug:
        return {"error": "group_slug is required"}
    if not body:
        return {"error": "body is required"}

    # Derive agent source_id from caller identity
    source_id: uuid.UUID | None = None
    if caller_identity:
        raw_id = caller_identity.get("agent_id") or caller_identity.get("sub")
        if raw_id:
            try:
                source_id = uuid.UUID(str(raw_id))
            except (ValueError, AttributeError):
                pass

    with tracer.start_as_current_span(
        "mcp.notification.send_notification",
        attributes={"notification.group_slug": group_slug},
    ):
        svc = NotificationService(db_session)
        try:
            result = await svc.send_to_group(
                group_slug=group_slug,
                body=body,
                subject=subject,
                source_type=SourceType.AGENT,
                source_id=source_id,
            )
        except ValueError as exc:
            logger.warning("send_notification tool: group not found: %s", exc)
            return {"error": str(exc)}
        except Exception as exc:
            logger.error("send_notification tool: unexpected error: %s", exc)
            return {"error": f"Dispatch failed: {exc}"}

    channels_delivered = sum(1 for r in result.channel_results if r.success)
    channels_failed = sum(1 for r in result.channel_results if not r.success)

    return {
        "group_slug": group_slug,
        "channels_attempted": len(result.channel_results),
        "channels_delivered": channels_delivered,
        "channels_failed": channels_failed,
        "log_ids": [str(lid) for lid in result.log_ids],
    }


async def handle_get_recipient_group(
    args: dict[str, Any],
    db_session: AsyncSession,
    caller_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    MCP tool handler for get_recipient_group.

    Returns recipient group information including configured channels and their properties.

    Returns a dict with:
      - group_slug: str
      - group_name: str
      - is_active: bool
      - channels: list of dicts with:
          - channel_id: str
          - channel_name: str
          - channel_type: str
          - recipient_properties: dict (e.g. {"recipients": [...]} or {"channel_id": "..."})
    """
    group_slug: str = args.get("group_slug", "")

    if not group_slug:
        return {"error": "group_slug is required"}

    with tracer.start_as_current_span(
        "mcp.notification.get_recipient_group",
        attributes={"notification.group_slug": group_slug},
    ):
        repo = NotificationRepository(db_session)
        try:
            # Query recipient group by slug
            result = await db_session.execute(
                select(RecipientGroup).where(RecipientGroup.slug == group_slug)
            )
            group = result.scalar_one_or_none()

            if not group:
                logger.warning("get_recipient_group tool: group not found: %s", group_slug)
                return {"error": f"Recipient group '{group_slug}' not found"}

            # Build channel info list
            channels_info = []
            for mapping in group.channel_mappings:
                channel = mapping.channel
                channels_info.append({
                    "channel_id": str(channel.id),
                    "channel_name": channel.name,
                    "channel_type": channel.channel_type.value,
                    "recipient_properties": mapping.recipient_properties or {},
                })

            return {
                "group_slug": group.slug,
                "group_name": group.name,
                "description": group.description,
                "is_active": group.is_active,
                "channels": channels_info,
            }

        except Exception as exc:
            logger.error("get_recipient_group tool: unexpected error: %s", exc)
            return {"error": f"Failed to retrieve group: {exc}"}
