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

from app.api.deps import require_internal_tenant_context, require_service_certificate
from app.core.tenant_context import TenantContext
from app.db.models.agents import AgentOutputType, AgentType
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal/system-tools",
    tags=["Internal - System Tools"],
    dependencies=[
        Depends(require_service_certificate),
        Depends(require_internal_tenant_context),
    ],
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
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
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
            tenant_id=tenant_ctx.tenant_id,
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
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
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
        # Tenant containment: resolve strictly within the signed tenant.
        result = await db.execute(
            select(RecipientGroup)
            .where(
                RecipientGroup.slug == group_slug,
                RecipientGroup.tenant_id == tenant_ctx.tenant_id,
            )
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
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
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
        # The preview/prompt is not a persisted column — fold it into the
        # reason so the markdown table preview reaches the WS intervention UI
        # (FIX-20261031-133253 confirmation previews render as tables).
        _prompt = body.tool_args.get("prompt")
        if _prompt and _prompt not in reason:
            reason = f"{reason}\n\n{_prompt}".strip()

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

        # For conversation-scoped interventions, resolve via ConversationSession.
        # FIX-20261031-133253: a conversational session (e.g. the Control
        # Center Assistant) may have NO agent_jobs row — the request is then
        # created with agent_session_id=None and conversation_session_id as
        # the resume key instead of failing with 404.
        conv_job = job
        conv_session = None
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

        if not conv_job and conv_session is None:
            raise HTTPException(
                status_code=404, detail=f"Session {session_id} not found"
            )
        _job_target = conv_job
        _agent_type_id = (
            conv_job.agent_type_id if conv_job else conv_session.agent_type_id
        )
        _delegation_depth = (
            (conv_job.delegation_depth or 0)
            if conv_job
            else 0
        )

        itype = InterventionType(intervention_type_str)
        store = InterveneRequestStore()

        # FIX-20261031-133253 replay idempotency: on LangGraph resume the
        # interrupted tool task REPLAYS from its start, so the assistant's
        # human_intervene call may arrive AGAIN. If a request with the same
        # conversation + reason already exists:
        #   - pending  → return it (dedupe; no duplicate WS dispatch)
        #   - responded → return the operator's response payload as the tool
        #     result so the replayed tool call completes WITHOUT interrupting
        #     again and the deep-agent loop continues.
        from app.db.models.intervene import (
            InterveneRequest,
            InterveneRequestStatus,
        )
        from sqlalchemy.orm import selectinload as _selectinload

        replay_existing = (
            await db.execute(
                select(InterveneRequest)
                .options(_selectinload(InterveneRequest.response))
                .where(
                    InterveneRequest.conversation_session_id == conversation_session_id,
                    InterveneRequest.reason == reason,
                )
                .order_by(InterveneRequest.created_at.desc())
                .limit(1)
            )
        ).scalars().first() if conversation_session_id else None
        if replay_existing is not None:
            if replay_existing.status == InterveneRequestStatus.pending:
                logger.info(
                    "System tool: human_intervene replay — returning existing "
                    "pending request %s (no duplicate)",
                    replay_existing.id,
                )
                return SystemToolResponse(
                    result={
                        "request_id": str(replay_existing.id),
                        "status": "pending",
                    }
                )
            if replay_existing.status == InterveneRequestStatus.responded:
                _resp = replay_existing.response
                _payload = {
                    "status": "resolved",
                    "request_id": str(replay_existing.id),
                }
                if _resp is not None:
                    if _resp.approval_value is not None:
                        _payload["approval_value"] = _resp.approval_value
                    if _resp.selected_choice is not None:
                        _payload["selected_choice"] = _resp.selected_choice
                    if _resp.text_value is not None:
                        _payload["text_value"] = _resp.text_value
                logger.info(
                    "System tool: human_intervene replay — request %s already "
                    "responded; returning operator response to the replayed "
                    "tool call",
                    replay_existing.id,
                )
                return SystemToolResponse(result=_payload)

        # Get agent type name for dispatch metadata
        from app.db.models.agents import AgentType
        result_at = await db.execute(
            select(AgentType).where(AgentType.id == _agent_type_id)
        )
        agent_type_row = result_at.scalar_one_or_none()
        agent_type_name = agent_type_row.name if agent_type_row else "unknown"

        request = await store.create_request(
            db=db,
            agent_session_id=_job_target.id if _job_target else None,
            agent_type_id=_agent_type_id,
            intervention_type=itype,
            reason=reason,
            choices=choices,
            conversation_session_id=conversation_session_id,
            delegation_depth=_delegation_depth,
        )

        # Extract parent session ID from child's input_data BEFORE commit
        # (conv_job is expired by commit, so read what we need now)
        requester_session_id = None
        child_session_id = str(_job_target.id) if _job_target else (
            str(conversation_session_id) if conversation_session_id else ""
        )
        input_data = (
            _job_target.input_data
            if _job_target is not None and isinstance(_job_target.input_data, dict)
            else {}
        )
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
                tenant_id=tenant_ctx.tenant_id,
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
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
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
        # Tenant containment: strictly within the signed tenant.
        # Try slug first (exact match), then name (exact match)
        result = await db.execute(
            select(AgentDataType).where(
                AgentDataType.slug == data_type_name,
                AgentDataType.tenant_id == tenant_ctx.tenant_id,
            )
        )
        data_type = result.scalar_one_or_none()

        if not data_type:
            result = await db.execute(
                select(AgentDataType).where(
                    AgentDataType.name == data_type_name,
                    AgentDataType.tenant_id == tenant_ctx.tenant_id,
                )
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
            db=db, filters=filters_dict, tenant_id=tenant_ctx.tenant_id
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
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
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
            tenant_id=tenant_ctx.tenant_id,
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
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
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
            tenant_id=tenant_ctx.tenant_id,
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
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
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
            tenant_id=tenant_ctx.tenant_id,
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
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
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
        # Verify role exists within the signed tenant (tenant-contained).
        role_result = await db.execute(
            select(AgentRole).where(
                AgentRole.id == body.agent_role_id,
                AgentRole.tenant_id == tenant_ctx.tenant_id,
            )
        )
        role = role_result.scalar_one_or_none()
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


# ── Decision Tool Resolution + Execution (Communication Hub forwarding) ──────


class DecisionToolExecuteRequest(BaseModel):
    """Request from Communication Hub to execute a decision tool.

    CH holds no credentials and makes no external calls — Control Center
    resolves the tool within the given tenant, decrypts the provider key,
    and dispatches. Tenant containment: the tool name resolves strictly
    within ``tenant_id`` (identical names in different tenants are
    independent).
    """

    session_id: str
    tenant_id: str | None = None
    tool_name: str
    input_state: dict[str, Any] = {}
    conversation_session_id: str | None = None


class DecisionToolInfo(BaseModel):
    """Catalog entry for one decision tool (MCP surface uses ``decision____<name>``)."""

    id: str
    name: str
    description: str | None
    input_schema: dict[str, Any] | None
    enabled: bool
    provider_type: str | None = None
    provider_display_name: str | None = None
    model_name: str | None = None


class DecisionToolListResponse(BaseModel):
    """Tenant-scoped decision tool catalog for the CH MCP bridge."""

    tools: list[DecisionToolInfo]


class DecisionToolListRequest(BaseModel):
    """Tenant-scoped decision tool catalog request from Communication Hub."""

    tenant_id: str | None = None


@router.post("/decision/list", response_model=DecisionToolListResponse)
async def list_decision_tools_internal(
    body: DecisionToolListRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: AsyncSession = Depends(get_db),
) -> DecisionToolListResponse:
    """List active decision tools within a tenant (called by Communication Hub).

    The tenant comes from the SIGNED internal tenant context (authoritative);
    the body ``tenant_id`` is only a cross-check fallback. CH holds no
    credentials — this endpoint returns names, generated descriptions, and
    input schemas only.
    """
    from app.services.system_one.decision_model_availability_service import (
        DecisionModelCatalogueService,
    )
    from app.services.system_one.decision_tool_service import (
        DecisionToolService,
        build_input_schema,
    )

    # Signed tenant context is authoritative (see execute_decision_tool_internal).
    tenant_id = tenant_ctx.tenant_id
    tools = await DecisionToolService().list(db, tenant_id)
    catalogue = DecisionModelCatalogueService()
    identity: dict[str, dict] = {}
    for t in tools:
        if t.decision_model_availability_id is None:
            continue
        try:
            resolved = await catalogue.resolve_selection(
                db, t.decision_model_availability_id, tenant_id
            )
        except Exception:
            continue
        identity[str(t.id)] = {
            "provider_type": resolved.provider_type.value,
            "provider_display_name": resolved.provider_display_name,
            "model_name": resolved.model_name,
        }
    entries = []
    for t in tools:
        if not t.enabled:
            continue
        info = identity.get(str(t.id), {})
        model_name = info.get("model_name")
        if model_name is None:
            model_name = t.provider_model  # legacy free-text fallback
        entries.append(
            DecisionToolInfo(
                id=str(t.id),
                name=t.name,
                description=t.description,
                input_schema=build_input_schema(t),
                enabled=t.enabled,
                provider_type=info.get("provider_type"),
                provider_display_name=info.get("provider_display_name"),
                model_name=model_name,
            )
        )
    return DecisionToolListResponse(tools=entries)


def _parse_uuid(raw: str | None) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


@router.post("/decision/execute", response_model=SystemToolResponse)
async def execute_decision_tool_internal(
    body: DecisionToolExecuteRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemToolResponse:
    """Execute a decision tool via the decision engine (called by Communication Hub).

    The tool name resolves strictly within the request's tenant before
    execution; the structured decision result is returned (no credentials,
    no provider key).
    """
    from app.services.system_one.decision_engine import (
        DecisionExecutionEngine,
        DecisionExecutionError,
    )
    from app.services.system_one.decision_tool_service import (
        is_decision_tool_ready,
        unavailable_tool_message,
    )

    # Signed tenant context is authoritative (tenant containment). It is
    # ALWAYS bound here: require_internal_tenant_context fails closed —
    # verified signed headers, or the ROOT tenant in single-tenant mode.
    # body.tenant_id (legacy CH→CC field, no longer sent) is only a
    # cross-check fallback and is never authoritative.
    bound_tenant_id = tenant_ctx.tenant_id
    logger.info(
        "Decision tool execution requested for '%s' (session %s, tenant %s)",
        body.tool_name,
        body.session_id,
        bound_tenant_id,
    )
    try:
        engine = DecisionExecutionEngine()
        tenant_id = bound_tenant_id
        tool = await engine.resolve_tool(db, body.tool_name, tenant_id)

        # Enabled-but-unready tool (pre-gate rows with NULL input/output
        # data types): do NOT run the engine (no model inference, no
        # persisted result). Return the actionable error IN-BAND (HTTP
        # 200, like validation errors) so CH/AR surface it to the agent
        # instead of retrying against a 5xx.
        if not is_decision_tool_ready(tool):
            logger.info(
                "decision tool '%s' called but not ready: missing "
                "input/output data type configuration",
                body.tool_name,
            )
            return SystemToolResponse(
                result={"error": unavailable_tool_message(tool.name)}
            )

        conversation_session_id = _parse_uuid(body.conversation_session_id)
        decision_result = await engine.execute(
            db=db,
            tool=tool,
            input_state=body.input_state,
            conversation_session_id=conversation_session_id,
            tenant_id=tenant_id,
        )
        await db.commit()
        return SystemToolResponse(
            result={
                "decision_tool_id": str(tool.id),
                "tool_name": tool.name,
                "outcome": decision_result.outcome.value,
                "status": decision_result.status.value,
                "answers": (decision_result.answers or {}).get("answers", {}),
                "input_state_snapshot": decision_result.input_state_snapshot,
                "provider_model": decision_result.provider_model,
                "provider": (decision_result.answers or {}).get("provider"),
                "error_message": decision_result.error_message,
                "created_at": decision_result.created_at.isoformat()
                if decision_result.created_at
                else None,
            }
        )
    except DecisionExecutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to execute decision tool '%s'", body.tool_name)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute decision tool: {exc}",
        )


# ── Semantic bridge (Software 3.0 script framework) ──────────────────────────


class SemanticBridgeRequest(BaseModel):
    """One-shot LLM completion request routed from Communication Hub.

    Sent by CH when a compiled script's ``semantic____<name>`` step runs:
    the script carries the repeatable tool calls + data processing; only
    the semantic step (summary / bridge / final render) consumes model
    capacity here.
    """

    session_id: str
    agent_type_id: str
    prompt: str
    input: Any = None


class SemanticBridgeResponse(BaseModel):
    """One-shot completion result."""

    text: str


@router.post("/semantic-bridge", response_model=SemanticBridgeResponse)
async def execute_semantic_bridge_internal(
    body: SemanticBridgeRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SemanticBridgeResponse:
    """One-shot LLM completion using the agent type's configured model.

    The agent type resolves strictly within the request's tenant (signed
    internal tenant context — same guard as the decision execute endpoint);
    its model configuration is decrypted and dispatched here in Control
    Center (CC-only DB access), and the raw completion text is returned.
    No credentials or provider keys cross the service boundary.
    """
    from app.services.agents.model_binding import ModelBindingError, ModelBindingLayer

    bound_tenant_id = tenant_ctx.tenant_id
    try:
        agent_type_id = uuid.UUID(str(body.agent_type_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Invalid agent_type_id")

    result = await db.execute(
        select(AgentType).where(
            AgentType.id == agent_type_id,
            AgentType.tenant_id == bound_tenant_id,
        )
    )
    agent_type = result.scalars().first()
    if agent_type is None:
        raise HTTPException(
            status_code=404,
            detail="Agent type not found in tenant for semantic bridge",
        )

    logger.info(
        "Semantic bridge requested for agent type '%s' (session %s, tenant %s)",
        agent_type.name,
        body.session_id,
        bound_tenant_id,
    )

    user_message = f"{body.prompt}\n\nInput data:\n{json.dumps(body.input, default=str)}"

    # LLM Mock Layer (Phase 4.5): in test mock modes the bridge completion
    # is served deterministically — zero LLM API usage. Inactive (default)
    # returns None and the real model path below runs unchanged.
    from app.services.agents.llm_mock_provider import maybe_mock_semantic_bridge

    mocked = maybe_mock_semantic_bridge(
        user_message, str(agent_type.model_id or "semantic-bridge")
    )
    if mocked is not None:
        return SemanticBridgeResponse(text=mocked)

    try:
        binding = ModelBindingLayer()
        model_config = await binding.resolve_model_config(agent_type.model_id, db)
        response = await binding.complete(
            agent_type=agent_type,
            model_config=model_config,
            messages=[{"role": "user", "content": user_message}],
        )
    except ModelBindingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("Semantic bridge completion failed for agent type '%s'", agent_type.name)
        raise HTTPException(
            status_code=500,
            detail=f"Semantic bridge completion failed: {exc}",
        )

    text = response.text if hasattr(response, "text") else str(response)
    logger.info(
        "Semantic bridge completed for agent type '%s' (session %s)",
        agent_type.name,
        body.session_id,
    )
    return SemanticBridgeResponse(text=text)
