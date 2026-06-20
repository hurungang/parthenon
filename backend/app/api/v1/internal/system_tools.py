"""System tool endpoints for Control Center.

Provides MCP-like JSON-RPC endpoints for system tools:
- save_result: Save agent execution result
- send_notification: Send notification via recipient group  
- get_recipient_group: Get recipient group information
- human_intervene: Create a human intervene request for an agent session

All endpoints require mTLS certificate authentication.
These are called by Communication Hub when routing system tool calls.
"""
import logging
import uuid
from datetime import UTC
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_service_certificate
from app.db.models.agents import AgentOutputType
from app.db.session import get_db

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
    conversation_session_id: str | None = None


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
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.db.models.notifications import RecipientGroup

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


@router.post("/human-intervene", response_model=SystemToolResponse)
async def human_intervene_tool(
    body: SystemToolRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemToolResponse:
    """Create a human intervene request for an agent session.

    Called by Communication Hub when routing a ``human_intervene`` system tool
    call from Agent Runtime.  Persists an ``InterveneRequest`` and returns the
    ``request_id`` so the hub can relay it back to the waiting agent.

    Args:
        body: Tool request with session ID and arguments containing
            ``intervention_type``, ``reason``, optional ``choices`` and ``prompt``.
        db: Database session.

    Returns:
        SystemToolResponse with ``request_id`` and ``status``.

    Raises:
        HTTPException: 404 if session not found, 409 if request already pending.
    """
    logger.info("System tool: human_intervene for session %s", body.session_id)

    try:
        session_id = uuid.UUID(body.session_id)
        conversation_session_id = None
        if body.conversation_session_id:
            try:
                conversation_session_id = uuid.UUID(body.conversation_session_id)
            except ValueError:
                logger.warning("Invalid conversation_session_id: %s", body.conversation_session_id)
        intervention_type_str = body.tool_args.get("intervention_type")
        reason = body.tool_args.get("reason", "")
        choices = body.tool_args.get("choices")

        if not intervention_type_str:
            raise HTTPException(
                status_code=400, detail="intervention_type is required"
            )

        from app.db.models.agents import AgentJob
        from app.db.models.conversations import ConversationSession
        from app.db.models.intervene import InterventionType
        from app.services.agents.intervene_service import InterveneRequestStore

        result = await db.execute(
            select(AgentJob).where(AgentJob.id == session_id)
        )
        job = result.scalar_one_or_none()

        # For conversation-scoped interventions, resolve via ConversationSession
        conv_job = job
        if not job and conversation_session_id:
            conv_result = await db.execute(
                select(ConversationSession).where(
                    ConversationSession.id == conversation_session_id
                )
            )
            conv_session = conv_result.scalar_one_or_none()
            if conv_session and conv_session.agent_job_id:
                result = await db.execute(
                    select(AgentJob).where(AgentJob.id == conv_session.agent_job_id)
                )
                conv_job = result.scalar_one_or_none()

        if not conv_job:
            raise HTTPException(
                status_code=404, detail=f"Session {session_id} not found"
            )

        itype = InterventionType(intervention_type_str)
        store = InterveneRequestStore()

        # Get agent type name for dispatch metadata
        from app.db.models.agents import AgentType
        result_at = await db.execute(
            select(AgentType).where(AgentType.id == conv_job.agent_type_id)
        )
        agent_type_row = result_at.scalar_one_or_none()
        agent_type_name = agent_type_row.name if agent_type_row else "unknown"

        request = await store.create_request(
            db=db,
            agent_session_id=conv_job.id,
            agent_type_id=conv_job.agent_type_id,
            intervention_type=itype,
            reason=reason,
            choices=choices,
            conversation_session_id=conversation_session_id,
            delegation_depth=conv_job.delegation_depth if conv_job.delegation_depth else 0,
        )

        # Extract parent session ID from child's input_data BEFORE commit
        # (conv_job is expired by commit, so read what we need now)
        requester_session_id = None
        child_session_id = str(conv_job.id)
        input_data = conv_job.input_data if isinstance(conv_job.input_data, dict) else {}
        if isinstance(input_data, dict):
            raw = input_data.get("__requester_session_id")
            if raw:
                try:
                    requester_session_id = uuid.UUID(str(raw))
                except (ValueError, TypeError):
                    logger.warning("Invalid __requester_session_id: %s", raw)

        # Extract request attributes BEFORE commit for post-commit use.
        # After commit (or a subsequent rollback), ORM objects may be expired
        # and lazy-loading from sync attribute access triggers MissingGreenlet.
        request_id = request.id
        request_id_str = str(request.id)
        intervention_type_value = request.intervention_type.value
        request_reason = request.reason
        request_choices = request.choices
        request_delegation_depth = request.delegation_depth

        await db.commit()

        logger.info(
            "Created intervene request %s for session %s%s",
            request_id_str,
            session_id,
            f" (conversation: {conversation_session_id})" if conversation_session_id else "",
        )

        if requester_session_id is not None:
            try:
                from datetime import datetime

                from app.db.models.session_logs import (
                    ExecutionEventCategory,
                    ExecutionLogEntry,
                )
                log_entry = ExecutionLogEntry(
                    id=uuid.uuid4(),
                    session_id=requester_session_id,
                    event_type="human_intervene",
                    log_level="INFO",
                    message=(
                        f"Delegated agent {agent_type_name} requires "
                        f"human intervention: {reason}"
                    ),
                    data={
                        "request_id": request_id_str,
                        "intervention_type": intervention_type_value,
                        "child_session_id": child_session_id,
                        "agent_type": agent_type_name,
                    },
                    event_category=ExecutionEventCategory.functional,
                    timestamp=datetime.now(UTC),
                )
                db.add(log_entry)
                await db.flush()
                logger.info(
                    "Propagated intervene_request to parent session %s",
                    requester_session_id,
                )
            except Exception as propagate_exc:
                logger.warning(
                    "Failed to propagate intervene_request to parent session: %s",
                    propagate_exc,
                )
                await db.rollback()

        # Dispatch to Communication Hub when this is a conversation-scoped intervention
        if conversation_session_id:
            try:
                from app.services.control_center.comm_hub_client import CommunicationHubClient
                ch_client = CommunicationHubClient()
                await ch_client.dispatch_message(
                    session_id=conversation_session_id,
                    message_type="intervene_request",
                    content={
                        "request_id": request_id_str,
                        "conversation_session_id": str(conversation_session_id),
                        "intervention_type": intervention_type_value,
                        "reason": request_reason,
                        "choices": request_choices,
                        "agent_type": agent_type_name,
                        "delegation_depth": request_delegation_depth,
                    },
                )
                logger.info(
                    "Dispatched intervene_request to CH for conversation %s",
                    conversation_session_id,
                )
            except Exception as dispatch_exc:
                logger.warning(
                    "Failed to dispatch intervene_request to CH: %s (intervention %s still created)",
                    dispatch_exc,
                    request_id_str,
                )

        # Attempt to dispatch a notification for the new intervene request.
        # This is best-effort — if no recipient group is configured for
        # intervene notifications, the call fails gracefully with a warning.
        try:
            from app.db.models.notifications import SourceType
            from app.services.notifications.notification_service import (
                NotificationService,
            )
            nsvc = NotificationService(db)
            await nsvc.send_to_group(
                group_slug="intervene-notifications",
                body=f"Human intervention required: {request_reason}",
                subject=f"Intervene Request ({intervention_type_value})",
                source_type=SourceType.INTERVENE_REQUEST_CREATED,
                source_id=request_id,
            )
        except Exception:
            logger.warning(
                "Failed to dispatch notification for intervene request %s "
                "(no recipient group 'intervene-notifications' configured?)",
                request_id_str,
            )

        return SystemToolResponse(
            result={"request_id": request_id_str, "status": "pending"}
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=409, detail=str(exc)
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to create intervene request")
        raise HTTPException(
            status_code=500, detail=f"Failed to create intervene request: {exc}"
        )
