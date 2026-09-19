"""System tool endpoints for Control Center.

Provides MCP-like JSON-RPC endpoints for system tools:
- send_notification: Send notification via recipient group  
- get_recipient_group: Get recipient group information
- human_intervene: Create a human intervene request for an agent session
- save_data: Save named intermediate data
- get_data: Query saved intermediate data
- get_output: Query historical final outputs

All endpoints require mTLS certificate authentication.
These are called by Communication Hub when routing system tool calls.
"""
import json
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
    agent_type_id: str | None = None
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


# save_result_tool endpoint removed — agents now use save_data_tool via CommHub.


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

        from app.db.models.notifications import GroupChannelMapping, RecipientGroup

        # Get the group with channel mappings (channels are accessed via GroupChannelMapping)
        result = await db.execute(
            select(RecipientGroup)
            .where(RecipientGroup.slug == group_slug)
            .options(
                selectinload(RecipientGroup.channel_mappings).selectinload(
                    GroupChannelMapping.channel
                )
            )
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
                    "id": str(mapping.channel.id),
                    "name": mapping.channel.name,
                    "channel_type": mapping.channel.channel_type.value,
                }
                for mapping in group.channel_mappings
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


@router.post("/query-result", response_model=SystemToolResponse)
async def query_result_tool(
    body: SystemToolRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemToolResponse:
    """Query past typed agent outputs by data type name.

    Resolves the ``data_type_name`` to an ``AgentDataType.id`` (by slug
    first, then by name), then queries ``AgentOutput`` records matching
    the optional filters.  Returns a list of matching output records
    conforming to the requested data type schema.

    Args:
        body: Tool request with ``data_type_name`` and optional filters
            (``date_from``, ``date_to``, ``field_filters``).
        db: Database session.

    Returns:
        SystemToolResponse with matching results as a JSON array.

    Raises:
        HTTPException: 404 if data type not found.
    """
    logger.info(
        "System tool: query_result — data_type_name=%s",
        body.tool_args.get("data_type_name"),
    )

    try:
        from app.db.models.agent_data_type import AgentDataType
        from app.db.models.agent_output import AgentOutput
        from app.schemas.agent_outputs import AgentOutputResponse as AgentOutputRespSchema
        from app.services.outputs.service import OutputService

        data_type_name = body.tool_args.get("data_type_name", "").strip()
        if not data_type_name:
            raise HTTPException(
                status_code=400,
                detail="data_type_name is required",
            )

        # Resolve data_type_name to AgentDataType.id
        # Try slug first (exact match), then name (exact match)
        result = await db.execute(
            select(AgentDataType).where(AgentDataType.slug == data_type_name)
        )
        data_type = result.scalar_one_or_none()

        if not data_type:
            result = await db.execute(
                select(AgentDataType).where(AgentDataType.name == data_type_name)
            )
            data_type = result.scalar_one_or_none()

        if not data_type:
            raise HTTPException(
                status_code=404,
                detail=f"Data type '{data_type_name}' not found",
            )

        # Build filters from tool_args
        filters_dict: dict[str, Any] = {
            "data_type_id": data_type.id,
            "page": 1,
            "page_size": 100,  # Allow retrieving up to 100 results
        }

        tool_filters = body.tool_args.get("filters") or {}
        if isinstance(tool_filters, dict):
            date_from = tool_filters.get("date_from")
            if date_from:
                filters_dict["date_from"] = date_from
            date_to = tool_filters.get("date_to")
            if date_to:
                filters_dict["date_to"] = date_to

        # Query outputs using OutputService
        output_service = OutputService()
        items, total = await output_service.list_outputs(
            db=db, filters=filters_dict
        )

        # Build response
        results_list: list[dict[str, Any]] = []
        for output in items:
            data_type_name_resolved = (
                output.data_type.name if output.data_type else None
            )
            agent_type_name_resolved = (
                output.agent_type.name if output.agent_type else None
            )

            results_list.append({
                "id": str(output.id),
                "data_type_id": str(output.data_type_id),
                "data_type_name": data_type_name_resolved,
                "agent_type_id": str(output.agent_type_id),
                "agent_type_name": agent_type_name_resolved,
                "execution_session_id": str(output.execution_session_id),
                "field_values": output.field_values,
                "validation_status": output.validation_status.value,
                "raw_output": output.raw_output,
                "created_at": output.created_at.isoformat() if output.created_at else None,
            })

        return SystemToolResponse(
            result={
                "results": results_list,
                "total": total,
                "data_type_name": data_type.name,
                "data_type_slug": data_type.slug,
            }
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Failed to query results for data type '%s'",
            body.tool_args.get("data_type_name"),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query results: {exc}",
        )


@router.post("/save-data", response_model=SystemToolResponse)
async def save_data_tool(
    body: SystemToolRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemToolResponse:
    """Save a named AgentData record on behalf of an agent session.

    Called by CommHub when routing a ``save_data`` system tool call from
    Agent Runtime.  Persists one ``AgentData`` record and returns the
    saved record's id and timestamp.

    Args:
        body: Tool request with session_id and tool_args containing
            ``data_name``, ``data_value``, optional ``agent_type_id``
            and ``data_type`` (default "json").
        db: Database session.

    Returns:
        SystemToolResponse with saved record id, data_name, and created_at.

    Raises:
        HTTPException: 400 if required fields are missing, 500 on failure.
    """
    logger.info("System tool: save_data for session %s", body.session_id)

    try:
        from app.services.agent_data.service import AgentDataService

        session_id_str = body.session_id
        data_name = body.tool_args.get("data_name")
        data_value = body.tool_args.get("data_value")
        agent_type_id_raw = body.agent_type_id or body.tool_args.get("agent_type_id")
        data_type = body.tool_args.get("data_type", "json")

        if not session_id_str:
            raise HTTPException(status_code=400, detail="session_id is required")
        if not data_name:
            raise HTTPException(status_code=400, detail="data_name is required")
        if data_value is None:
            raise HTTPException(status_code=400, detail="data_value is required")

        service = AgentDataService()
        record = await service.save(
            db=db,
            session_id=uuid.UUID(session_id_str),
            data_name=data_name,
            data_value=data_value,
            agent_type_id=uuid.UUID(agent_type_id_raw) if agent_type_id_raw else None,
            data_type=data_type,
        )
        await db.commit()

        logger.info(
            "AgentData saved: id=%s, data_name=%s, session=%s",
            record.id,
            data_name,
            session_id_str,
        )
        return SystemToolResponse(
            result={
                "id": str(record.id),
                "data_name": record.data_name,
                "data_type": record.data_type,
                "session_id": str(record.session_id),
                "created_at": record.created_at.isoformat() if record.created_at else None,
            }
        )

    except HTTPException:
        raise
    except ValueError as exc:
        logger.error("Invalid UUID in save_data: %s", exc)
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {exc}")
    except Exception as exc:
        logger.exception("Failed to save data for session %s", body.session_id)
        raise HTTPException(status_code=500, detail=f"Failed to save data: {exc}")


@router.post("/get-data", response_model=SystemToolResponse)
async def get_data_tool(
    body: SystemToolRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemToolResponse:
    """Query AgentData records for an agent session or type.

    Called by CommHub when routing a ``get_data`` system tool call.
    At least one filter (data_name, agent_type_id, session_id) must be
    provided; returns 400 if all filters are absent.

    Args:
        body: Tool request with tool_args containing optional ``data_name``,
            ``agent_type_id``, ``session_id``, ``limit``, and ``offset``.
        db: Database session.

    Returns:
        SystemToolResponse with list of matching AgentData records.

    Raises:
        HTTPException: 400 if no filters provided, 500 on failure.
    """
    logger.info("System tool: get_data for session %s", body.session_id)

    try:
        from app.services.agent_data.service import AgentDataService

        data_name = body.tool_args.get("data_name")
        agent_type_id_raw = body.tool_args.get("agent_type_id")
        session_id_raw = body.tool_args.get("session_id")
        limit = int(body.tool_args.get("limit", 50))
        offset = int(body.tool_args.get("offset", 0))

        if not data_name and not agent_type_id_raw and not session_id_raw:
            raise HTTPException(
                status_code=400,
                detail=(
                    "At least one filter (data_name, agent_type_id, or session_id) "
                    "must be provided."
                ),
            )

        service = AgentDataService()
        records = await service.query_by_filters(
            db=db,
            data_name=data_name,
            agent_type_id=uuid.UUID(agent_type_id_raw) if agent_type_id_raw else None,
            session_id=uuid.UUID(session_id_raw) if session_id_raw else None,
            limit=limit,
            offset=offset,
        )

        return SystemToolResponse(
            result={
                "records": [
                    {
                        "id": str(r.id),
                        "data_name": r.data_name,
                        "data_value": r.data_value,
                        "data_type": r.data_type,
                        "session_id": str(r.session_id) if r.session_id else None,
                        "agent_type_id": str(r.agent_type_id) if r.agent_type_id else None,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in records
                ],
                "count": len(records),
            }
        )

    except HTTPException:
        raise
    except ValueError as exc:
        logger.error("Invalid filter value in get_data: %s", exc)
        raise HTTPException(status_code=400, detail=f"Invalid filter value: {exc}")
    except Exception as exc:
        logger.exception("Failed to get data for session %s", body.session_id)
        raise HTTPException(status_code=500, detail=f"Failed to get data: {exc}")


@router.post("/get-output", response_model=SystemToolResponse)
async def get_output_tool(
    body: SystemToolRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemToolResponse:
    """Query AgentOutput records for an agent session or type.

    Called by CommHub when routing a ``get_output`` system tool call.
    All filters are optional; results are ordered by created_at descending.

    Args:
        body: Tool request with tool_args containing optional ``agent_type_id``,
            ``session_id``, ``date_from``, ``date_to``, ``limit``, ``offset``.
        db: Database session.

    Returns:
        SystemToolResponse with list of matching AgentOutput records.

    Raises:
        HTTPException: 500 on failure.
    """
    logger.info("System tool: get_output for session %s", body.session_id)

    try:
        from app.services.outputs.service import OutputService

        agent_type_id_raw = body.tool_args.get("agent_type_id")
        session_id_raw = body.tool_args.get("session_id")
        date_from_raw = body.tool_args.get("date_from")
        date_to_raw = body.tool_args.get("date_to")
        limit = int(body.tool_args.get("limit", 50))
        offset = int(body.tool_args.get("offset", 0))

        output_service = OutputService()
        records = await output_service.query_output_history(
            db=db,
            agent_type_id=uuid.UUID(agent_type_id_raw) if agent_type_id_raw else None,
            session_id=uuid.UUID(session_id_raw) if session_id_raw else None,
            date_from=date_from_raw,
            date_to=date_to_raw,
            limit=limit,
            offset=offset,
        )

        return SystemToolResponse(
            result={
                "records": [
                    {
                        "id": str(r.id),
                        "agent_type_id": str(r.agent_type_id) if r.agent_type_id else None,
                        "execution_session_id": str(r.execution_session_id) if r.execution_session_id else None,
                        "data_type_id": str(r.data_type_id) if r.data_type_id else None,
                        "field_values": r.field_values,
                        "validation_status": r.validation_status.value if r.validation_status else None,
                        "raw_output": r.raw_output,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in records
                ],
                "count": len(records),
            }
        )

    except HTTPException:
        raise
    except ValueError as exc:
        logger.error("Invalid filter value in get_output: %s", exc)
        raise HTTPException(status_code=400, detail=f"Invalid filter value: {exc}")
    except Exception as exc:
        logger.exception("Failed to get output for session %s", body.session_id)
        raise HTTPException(status_code=500, detail=f"Failed to get output: {exc}")


# ── Skills Resolution for External Agents ────────────────────────────────────

from app.schemas.api_key import SkillResolveInternalRequest, SkillResolveInternalResponse


@router.post("/skills/resolve", response_model=SkillResolveInternalResponse)
async def resolve_skills_internal(
    body: SkillResolveInternalRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SkillResolveInternalResponse:
    """Resolve all accessible skills for an agent role with optional ``since`` filter.

    Called by Communication Hub when an external agent invokes ``load_skills``.
    Returns full skill definitions including tool schemas and ``updated_at``
    timestamps. Supports incremental sync via ``since`` parameter.

    Args:
        body: Request with ``agent_role_id`` and optional ``since`` timestamp.
        db: Database session.

    Returns:
        SkillResolveInternalResponse with list of SkillWithVersion.

    Raises:
        HTTPException: 404 if role not found, 500 on database error.
    """
    from sqlalchemy.orm import selectinload

    from app.db.models.agents import AgentRole, AgentRoleSkill
    from app.db.models.mcp_hub import McpTool
    from app.db.models.skills import Skill, SkillToolBinding
    from app.schemas.api_key import SkillWithVersion, ToolDefinition

    logger.info(
        "Skills resolve requested for role %s (since=%s)",
        body.agent_role_id,
        body.since,
    )

    try:
        # Verify role exists
        role = await db.get(AgentRole, body.agent_role_id)
        if not role:
            raise HTTPException(
                status_code=404,
                detail=f"Agent role {body.agent_role_id} not found",
            )

        # Get skill IDs assigned to the role
        result = await db.execute(
            select(AgentRoleSkill.skill_id).where(
                AgentRoleSkill.role_id == body.agent_role_id
            )
        )
        skill_ids = [row[0] for row in result.fetchall()]

        if not skill_ids:
            return SkillResolveInternalResponse(skills=[])

        # Fetch skills with tool bindings
        stmt = (
            select(Skill)
            .where(Skill.id.in_(skill_ids), Skill.is_active.is_(True))
            .options(
                selectinload(Skill.tool_bindings).selectinload(SkillToolBinding.tool)
            )
        )

        if body.since is not None:
            stmt = stmt.where(Skill.updated_at > body.since)

        result = await db.execute(stmt)
        skills = result.scalars().unique().all()

        skill_versions: list[SkillWithVersion] = []
        for skill in skills:
            tools: list[ToolDefinition] = []
            for binding in skill.tool_bindings:
                tool = binding.tool
                if tool and tool.is_active:
                    tools.append(
                        ToolDefinition(
                            tool_id=tool.id,
                            name=tool.name,
                            description=tool.description,
                            input_schema=getattr(tool, 'input_schema', None),
                            output_schema=getattr(tool, 'output_schema', None),
                        )
                    )

            skill_versions.append(
                SkillWithVersion(
                    skill_id=skill.id,
                    name=skill.name,
                    description=skill.description,
                    instructions=skill.instructions,
                    is_active=skill.is_active,
                    is_system=skill.is_system,
                    updated_at=skill.updated_at,
                    tools=tools,
                )
            )

        logger.info(
            "Resolved %d skills for role %s",
            len(skill_versions),
            body.agent_role_id,
        )

        return SkillResolveInternalResponse(skills=skill_versions)

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Failed to resolve skills for role %s",
            body.agent_role_id,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to resolve skills: {exc}",
        )
