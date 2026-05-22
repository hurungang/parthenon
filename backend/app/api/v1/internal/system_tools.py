"""System tool endpoints for Control Center.

Provides MCP-like JSON-RPC endpoints for system tools:
- save_result: Save agent execution result
- send_notification: Send notification via recipient group  
- get_recipient_group: Get recipient group information

All endpoints require mTLS certificate authentication.
These are called by Communication Hub when routing system tool calls.
"""
import logging
import uuid
from typing import Any, Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import require_service_certificate
from app.db.session import get_db
from app.db.models.agents import AgentOutputType

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal/system-tools",
    tags=["Internal - System Tools"],
    dependencies=[Depends(require_service_certificate)],
)


class SystemToolRequest(BaseModel):
    """Request to execute a system tool."""

    session_id: str
    tool_args: dict[str, Any]


class SystemToolResponse(BaseModel):
    """Response from system tool execution."""

    result: dict[str, Any]


def _content_type_from_output_type(output_type: AgentOutputType | str, requested: str | None) -> str:
    """Resolve the persisted ResultRecord content_type.

    Priority:
    1) Explicit ``content_type`` from tool args (text|markdown|json or mime)
    2) Agent type output_type default
    """
    if requested:
        normalized = requested.strip().lower()
        aliases = {
            "text": "text/plain",
            "markdown": "text/markdown",
            "json": "application/json",
        }
        return aliases.get(normalized, requested)

    output_value = output_type.value if isinstance(output_type, AgentOutputType) else str(output_type)

    if output_value == AgentOutputType.markdown.value:
        return "text/markdown"
    if output_value == AgentOutputType.typed.value:
        return "application/json"
    return "text/plain"


def _payload_from_tool_args(tool_args: dict[str, Any], content_type: str) -> dict[str, Any]:
    """Normalize save_result payload shape for persistence.

    ResultRecord payload remains JSON object for repository compatibility.
    """
    if "data" in tool_args and tool_args["data"] is not None:
        data = tool_args["data"]
        if isinstance(data, dict):
            return data
        return {"value": data}

    content = tool_args.get("content", "")
    if content_type == "application/json":
        if isinstance(content, dict):
            return content
        return {"content": content}

    return {"content": content}


@router.post("/save-result", response_model=SystemToolResponse)
async def save_result_tool(
    body: SystemToolRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemToolResponse:
    """Save agent execution result to database.

    Updates ``AgentJob.output_data`` for backward compatibility and also persists
    a ``ResultRecord`` so the result appears in the Result Repository UI.

    Args:
        body: Tool request with session ID and arguments
        db: Database session

    Returns:
        Success status

    Raises:
        HTTPException: If save fails
    """
    logger.info("System tool: save_result for session %s", body.session_id)

    try:
        session_id = uuid.UUID(body.session_id)
        content = body.tool_args.get("content", "")
        title = body.tool_args.get("title", "") or f"Session {session_id} result"

        # Import here to avoid circular dependencies
        from app.db.models.agents import AgentJob, AgentType
        from app.services.results.store import ResultStore

        # Get the session
        result = await db.execute(select(AgentJob).where(AgentJob.id == session_id))
        job = result.scalar_one_or_none()

        if not job:
            logger.error("Session %s not found for save_result", session_id)
            raise HTTPException(
                status_code=404, detail=f"Session {session_id} not found"
            )

        # Update output_data (backward compat)
        output_data = job.output_data or {}
        output_data["result"] = content
        output_data["title"] = title
        job.output_data = output_data

        # Resolve content type from agent output definition, unless tool call specifies one.
        agent_type = await db.get(AgentType, job.agent_type_id)
        output_type = agent_type.output_type if agent_type else AgentOutputType.auto
        content_type = _content_type_from_output_type(
            output_type=output_type,
            requested=body.tool_args.get("content_type"),
        )
        payload = _payload_from_tool_args(body.tool_args, content_type)

        # Also persist to Result Repository so it appears in the UI
        store = ResultStore()
        await store.save(
            payload=payload,
            db=db,
            title=title,
            agent_type_id=job.agent_type_id,
            content_type=content_type,
            # conversation_session_id is None for task agent sessions
        )

        await db.commit()

        logger.info("Result saved for session %s (ResultRecord created)", session_id)
        return SystemToolResponse(result={"status": "saved", "session_id": str(session_id)})

    except ValueError as exc:
        logger.error("Invalid session ID: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid session ID format")
    except Exception as exc:
        logger.exception("Failed to save result for session %s", body.session_id)
        raise HTTPException(status_code=500, detail=f"Failed to save result: {exc}")


@router.post("/send-notification", response_model=SystemToolResponse)
async def send_notification_tool(
    body: SystemToolRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemToolResponse:
    """Send notification via recipient group.

    Args:
        body: Tool request with session ID and arguments
        db: Database session

    Returns:
        Notification send status

    Raises:
        HTTPException: If notification send fails
    """
    logger.info("System tool: send_notification for session %s", body.session_id)

    try:
        group_slug = body.tool_args.get("group_slug")
        channel = body.tool_args.get("channel")
        subject = body.tool_args.get("subject", "")
        message_body = body.tool_args.get("body", "")

        if not group_slug or not message_body:
            raise HTTPException(
                status_code=400,
                detail="group_slug and body are required parameters",
            )

        # Import notification service
        from app.services.notifications.notification_service import NotificationService

        service = NotificationService(db)
        await service.send_to_group(
            group_slug=group_slug,
            subject=subject,
            body=message_body,
            channel=channel,
        )

        logger.info("Notification sent to group %s", group_slug)
        return SystemToolResponse(
            result={"status": "sent", "group_slug": group_slug, "channel": channel}
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to send notification")
        raise HTTPException(
            status_code=500, detail=f"Failed to send notification: {exc}"
        )


@router.post("/get-recipient-group", response_model=SystemToolResponse)
async def get_recipient_group_tool(
    body: SystemToolRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemToolResponse:
    """Get recipient group information.

    Args:
        body: Tool request with session ID and arguments
        db: Database session

    Returns:
        Recipient group details

    Raises:
        HTTPException: If group not found
    """
    logger.info("System tool: get_recipient_group for session %s", body.session_id)

    try:
        group_slug = body.tool_args.get("group_slug")

        if not group_slug:
            raise HTTPException(
                status_code=400, detail="group_slug is a required parameter"
            )

        # Import models
        from app.db.models.notifications import RecipientGroup
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        # Get the group with channels
        result = await db.execute(
            select(RecipientGroup)
            .where(RecipientGroup.slug == group_slug)
            .options(selectinload(RecipientGroup.channels))
        )
        group = result.scalar_one_or_none()

        if not group:
            raise HTTPException(
                status_code=404, detail=f"Recipient group '{group_slug}' not found"
            )

        # Build response
        group_info = {
            "slug": group.slug,
            "name": group.name,
            "description": group.description,
            "channels": [
                {
                    "id": str(ch.id),
                    "name": ch.name,
                    "channel_type": ch.channel_type.value,
                }
                for ch in group.channels
            ],
        }

        logger.info("Retrieved recipient group %s", group_slug)
        return SystemToolResponse(result=group_info)

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to get recipient group")
        raise HTTPException(
            status_code=500, detail=f"Failed to get recipient group: {exc}"
        )
