"""InterveneRequestStore — manages human-intervene request lifecycle."""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from opentelemetry import trace
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.agents import AgentJob, AgentJobStatus, AgentType
from app.db.models.identity import Identity
from app.db.models.intervene import (
    InterveneRequest,
    InterveneRequestStatus,
    InterveneResponse,
    InterventionType,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class InterveneRequestStore:
    """Persistence layer for intervene request lifecycle.

    Handles creation, querying, response submission, cancellation, and
    aggregate metrics for the system____human_intervene tool.
    """

    async def create_request(
        self,
        db: AsyncSession,
        agent_session_id: uuid.UUID,
        agent_type_id: uuid.UUID,
        intervention_type: InterventionType,
        reason: str,
        choices: list[str] | None = None,
    ) -> InterveneRequest:
        """Create a new intervene request for an agent session.

        Raises ValueError if a pending request already exists for the session.
        """
        with tracer.start_as_current_span(
            "intervene.create_request",
            attributes={
                "intervene.agent_session_id": str(agent_session_id),
                "intervene.intervention_type": intervention_type.value,
            },
        ) as span:
            existing = await self._find_pending_for_session(db, agent_session_id)
            if existing is not None:
                span.set_attribute("intervene.conflict", True)
                raise ValueError(
                    f"Agent session {agent_session_id} already has a pending "
                    f"intervene request {existing.id}"
                )

            request = InterveneRequest(
                agent_session_id=agent_session_id,
                agent_type_id=agent_type_id,
                intervention_type=intervention_type,
                reason=reason,
                choices=choices,
                status=InterveneRequestStatus.pending,
            )
            db.add(request)
            await db.flush()
            await db.refresh(request)
            span.set_attribute("intervene.request_id", str(request.id))
            span.set_attribute("intervene.status", request.status.value)
            logger.info(
                "Created intervene request %s for session %s (type=%s)",
                request.id,
                agent_session_id,
                intervention_type.value,
            )
            return request

    async def get_request(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
    ) -> InterveneRequest | None:
        """Fetch an intervene request with its response eagerly loaded."""
        stmt = (
            select(InterveneRequest)
            .options(
                selectinload(InterveneRequest.response),
                selectinload(InterveneRequest.agent_session).selectinload(AgentJob.agent_type),
            )
            .where(InterveneRequest.id == request_id)
        )
        result = await db.execute(stmt)
        request = result.scalar_one_or_none()
        if request:
            await self._populate_user_names(db, request)
        return request

    async def list_requests(
        self,
        db: AsyncSession,
        status: InterveneRequestStatus | None = None,
        intervention_type: InterventionType | None = None,
        agent_session_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[InterveneRequest]:
        """List intervene requests with optional filters."""
        stmt = (
            select(InterveneRequest)
            .options(
                selectinload(InterveneRequest.response),
                selectinload(InterveneRequest.agent_session).selectinload(AgentJob.agent_type),
            )
            .order_by(InterveneRequest.created_at.desc())
        )
        if status is not None:
            stmt = stmt.where(InterveneRequest.status == status)
        if intervention_type is not None:
            stmt = stmt.where(InterveneRequest.intervention_type == intervention_type)
        if agent_session_id is not None:
            stmt = stmt.where(InterveneRequest.agent_session_id == agent_session_id)
        stmt = stmt.limit(limit).offset(offset)
        result = await db.execute(stmt)
        requests = list(result.scalars().all())

        # Populate agent_name, triggered_by_user_name, operator_user_name
        user_ids = set()
        for req in requests:
            if req.agent_session and req.agent_session.triggered_by_user_id:
                user_ids.add(req.agent_session.triggered_by_user_id)
            if req.response and req.response.operator_user_id:
                user_ids.add(req.response.operator_user_id)
        if user_ids:
            identity_stmt = select(Identity).where(Identity.id.in_(user_ids))
            identity_result = await db.execute(identity_stmt)
            identity_map = {ident.id: ident.display_name for ident in identity_result.scalars().all()}
        else:
            identity_map = {}
        for req in requests:
            if req.agent_session:
                req.agent_name = req.agent_session.agent_type.name if req.agent_session.agent_type else None
                req.triggered_by_user_name = identity_map.get(req.agent_session.triggered_by_user_id) if req.agent_session.triggered_by_user_id else None
            if req.response:
                req.response.operator_user_name = identity_map.get(req.response.operator_user_id) if req.response.operator_user_id else None

        return requests

    async def submit_response(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        operator_user_id: uuid.UUID,
        approval_value: bool | None = None,
        selected_choice: str | None = None,
        text_value: str | None = None,
    ) -> InterveneResponse:
        """Submit a human response to a pending intervene request.

        Creates an InterveneResponse, marks the request as responded, and
        transitions the associated AgentJob back to running.

        Raises ValueError if the request is not pending.
        """
        with tracer.start_as_current_span(
            "intervene.submit_response",
            attributes={
                "intervene.request_id": str(request_id),
                "intervene.operator_user_id": str(operator_user_id),
            },
        ) as span:
            request = await self._get_or_raise(db, request_id)
            if request.status != InterveneRequestStatus.pending:
                span.set_attribute("intervene.error", "not_pending")
                raise ValueError(
                    f"Cannot respond to request {request_id}: "
                    f"current status is {request.status.value}"
                )

            response = InterveneResponse(
                request_id=request_id,
                operator_user_id=operator_user_id,
                approval_value=approval_value,
                selected_choice=selected_choice,
                text_value=text_value,
            )
            db.add(response)
            request.status = InterveneRequestStatus.responded
            request.responded_at = datetime.now(UTC)

            # Resume the agent session
            job = await db.get(AgentJob, request.agent_session_id)
            if job is not None and job.status == AgentJobStatus.waiting_for_human:
                job.status = AgentJobStatus.running
                span.set_attribute("intervene.session_resumed", True)
                logger.info(
                    "Resumed agent session %s after human response to request %s",
                    job.id,
                    request_id,
                )

            await db.flush()
            await db.refresh(response)

            # Populate operator name
            identity_stmt = select(Identity).where(Identity.id == operator_user_id)
            identity_result = await db.execute(identity_stmt)
            operator_identity = identity_result.scalar_one_or_none()
            response.operator_user_name = operator_identity.display_name if operator_identity else None

            span.set_attribute("intervene.response_id", str(response.id))
            logger.info(
                "Submitted response %s for request %s (operator=%s)",
                response.id,
                request_id,
                operator_user_id,
            )
            return response

    async def cancel_request(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
    ) -> InterveneRequest:
        """Cancel a pending intervene request.

        Raises ValueError if the request is not pending.
        """
        with tracer.start_as_current_span(
            "intervene.cancel_request",
            attributes={"intervene.request_id": str(request_id)},
        ) as span:
            request = await self._get_or_raise(db, request_id)
            if request.status != InterveneRequestStatus.pending:
                span.set_attribute("intervene.error", "not_pending")
                raise ValueError(
                    f"Cannot cancel request {request_id}: "
                    f"current status is {request.status.value}"
                )
            request.status = InterveneRequestStatus.cancelled
            await db.flush()
            await db.refresh(request)
            span.set_attribute("intervene.status", request.status.value)
            logger.info("Cancelled intervene request %s", request_id)
            return request

    async def get_metrics(
        self,
        db: AsyncSession,
    ) -> dict[str, int | float]:
        """Return aggregate metrics for the intervene system.

        Returns:
            dict with pending_count, avg_response_time_seconds, resolution_rate.
        """
        with tracer.start_as_current_span("intervene.get_metrics") as span:
            # Total requests count
            total_stmt = select(func.count(InterveneRequest.id))
            total_result = await db.execute(total_stmt)
            total = total_result.scalar() or 0

            # Pending count
            pending_stmt = select(func.count(InterveneRequest.id)).where(
                InterveneRequest.status == InterveneRequestStatus.pending
            )
            pending_result = await db.execute(pending_stmt)
            pending_count = pending_result.scalar() or 0

            # Resolved count (responded or cancelled)
            resolved_stmt = select(func.count(InterveneRequest.id)).where(
                InterveneRequest.status.in_([
                    InterveneRequestStatus.responded,
                    InterveneRequestStatus.cancelled,
                ])
            )
            resolved_result = await db.execute(resolved_stmt)
            resolved_count = resolved_result.scalar() or 0

            # Average response time (seconds between created_at and responded_at)
            # Only for requests that have been responded to
            avg_time_stmt = select(
                func.avg(
                    func.extract("epoch", InterveneResponse.responded_at)
                    - func.extract("epoch", InterveneRequest.created_at)
                )
            ).select_from(InterveneRequest).join(
                InterveneResponse,
                InterveneRequest.id == InterveneResponse.request_id,
            ).where(
                InterveneRequest.status == InterveneRequestStatus.responded,
            )
            avg_time_result = await db.execute(avg_time_stmt)
            avg_time = avg_time_result.scalar()
            avg_response_time_seconds = float(avg_time) if avg_time is not None else 0.0

            resolution_rate = (
                round(resolved_count / total, 4) if total > 0 else 1.0
            )

            span.set_attribute("intervene.pending_count", pending_count)
            span.set_attribute("intervene.avg_response_time_seconds", avg_response_time_seconds)
            span.set_attribute("intervene.resolution_rate", resolution_rate)

            return {
                "pending_count": pending_count,
                "avg_response_time_seconds": avg_response_time_seconds,
                "resolution_rate": resolution_rate,
            }

    # ── Internal helpers ───────────────────────────────────────────────────

    async def _find_pending_for_session(
        self,
        db: AsyncSession,
        agent_session_id: uuid.UUID,
    ) -> InterveneRequest | None:
        """Return the first pending request for a given agent session, if any."""
        stmt = (
            select(InterveneRequest)
            .where(
                InterveneRequest.agent_session_id == agent_session_id,
                InterveneRequest.status == InterveneRequestStatus.pending,
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_or_raise(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
    ) -> InterveneRequest:
        """Fetch an InterveneRequest by ID or raise ValueError."""
        request = await db.get(InterveneRequest, request_id)
        if request is None:
            raise ValueError(f"InterveneRequest {request_id} not found")
        return request

    async def _populate_user_names(
        self,
        db: AsyncSession,
        request: InterveneRequest,
    ) -> None:
        """Populate agent_name, triggered_by_user_name, and operator_user_name on the request."""
        user_ids = set()
        if request.agent_session and request.agent_session.triggered_by_user_id:
            user_ids.add(request.agent_session.triggered_by_user_id)
        if request.response and request.response.operator_user_id:
            user_ids.add(request.response.operator_user_id)
        identity_map = {}
        if user_ids:
            identity_stmt = select(Identity).where(Identity.id.in_(user_ids))
            identity_result = await db.execute(identity_stmt)
            identity_map = {ident.id: ident.display_name for ident in identity_result.scalars().all()}
        if request.agent_session:
            request.agent_name = request.agent_session.agent_type.name if request.agent_session.agent_type else None
            request.triggered_by_user_name = identity_map.get(request.agent_session.triggered_by_user_id) if request.agent_session.triggered_by_user_id else None
        if request.response:
            request.response.operator_user_name = identity_map.get(request.response.operator_user_id) if request.response.operator_user_id else None
