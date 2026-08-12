"""TerminationOrchestrator — permission-gated node termination with subtree cascade.

Control Center authority for all termination persistence and authorization decisions.
Agent Runtime executes the actual stop; Control Center owns the records and outcomes.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentJob, AgentJobStatus, AgentTerminationCategory
from app.db.models.termination_request import (
    TerminationPermissionEvaluationOutcome,
    TerminationRequest,
    TerminationRequestStatus,
    TerminationScope,
)
from app.db.models.termination_cascade_outcome import TerminationCascadeOutcome, TerminationOutcome
from app.services.control_center.agent_runtime_client import (
    AgentRuntimeClient,
    AgentRuntimeClientError,
)
from app.services.control_center.runtime_topology_controller import RuntimeTopologyController

logger = logging.getLogger(__name__)

_topology_controller = RuntimeTopologyController()
_agent_runtime_client = AgentRuntimeClient()


class TerminationDeniedError(Exception):
    """Raised when a terminate request is rejected due to insufficient permissions."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class TerminationOrchestrator:
    """
    Orchestrates permission-gated termination of agent runs with optional cascade.

    Permission decisions are made before any write occurs (fail-closed).
    All outcomes are persisted via Control Center DB; Agent Runtime status updates
    flow through this service.

    Phase 3.11: termination is now a TWO-PHASE action:
      1. Cancel the in-flight ``asyncio.Task`` on Agent Runtime via
         ``POST /terminate/{session_id}`` so the running agent actually stops.
      2. Persist the terminal transition (``failed`` + termination_category)
         on the Control Center's ``AgentJob`` row.
    A 404 from Agent Runtime (no in-flight task — already finished) is
    treated as a no-op success because the operator's intent (stop the
    session) is satisfied either way.
    """

    async def request_termination(
        self,
        *,
        target_session_id: uuid.UUID,
        requested_by_user_id: uuid.UUID,
        scope: TerminationScope,
        operator_reason: str | None,
        db: AsyncSession,
        can_terminate: bool = True,
    ) -> TerminationRequest:
        """Create a TerminationRequest, check permissions, and cascade if authorised.

        Args:
            target_session_id: The AgentJob to terminate.
            requested_by_user_id: Identity ID of the requesting operator.
            scope: node_only or cascade_subtree.
            operator_reason: Human-readable reason from the operator.
            db: Async database session (Control Center).
            can_terminate: Pre-evaluated permission flag from the API layer.

        Returns:
            Persisted TerminationRequest record.

        Raises:
            TerminationDeniedError: When can_terminate is False.
        """
        # Verify target session exists
        target_job = await db.get(AgentJob, target_session_id)
        if target_job is None:
            raise ValueError(f"Session {target_session_id} not found")

        # Permission evaluation
        if not can_terminate:
            deny_reason = "Operator does not have runtime terminate permission"
            request = TerminationRequest(
                requested_by_user_id=requested_by_user_id,
                target_agent_job_id=target_session_id,
                termination_scope=scope,
                permission_evaluation_outcome=TerminationPermissionEvaluationOutcome.denied,
                permission_evaluation_reason=deny_reason,
                request_status=TerminationRequestStatus.rejected,
            )
            db.add(request)
            await db.flush()
            await db.commit()
            logger.warning(
                "Termination denied for session %s by user %s: %s",
                target_session_id,
                requested_by_user_id,
                deny_reason,
            )
            raise TerminationDeniedError(deny_reason)

        # Create accepted request record
        request = TerminationRequest(
            requested_by_user_id=requested_by_user_id,
            target_agent_job_id=target_session_id,
            termination_scope=scope,
            permission_evaluation_outcome=TerminationPermissionEvaluationOutcome.allowed,
            permission_evaluation_reason=operator_reason,
            request_status=TerminationRequestStatus.accepted,
        )
        db.add(request)
        await db.flush()

        # Collect sessions to terminate
        if scope == TerminationScope.cascade_subtree:
            session_ids = await _topology_controller.get_subtree_session_ids(
                target_session_id, db
            )
        else:
            session_ids = [target_session_id]

        # Execute terminations and record cascade outcomes
        outcomes: list[TerminationCascadeOutcome] = []
        success_count = 0
        failure_count = 0

        for idx, session_id in enumerate(session_ids):
            cascade_level = idx  # root is level 0
            outcome = await self._terminate_single_session(
                session_id=session_id,
                request_id=request.id,
                cascade_level=cascade_level,
                db=db,
                operator_reason=operator_reason,
            )
            outcomes.append(outcome)
            if outcome.termination_outcome == TerminationOutcome.terminated:
                success_count += 1
            elif outcome.termination_outcome in (
                TerminationOutcome.already_completed,
            ):
                success_count += 1
            else:
                failure_count += 1

        # Determine final request status
        if failure_count == 0:
            request.request_status = TerminationRequestStatus.completed
        elif success_count > 0:
            request.request_status = TerminationRequestStatus.partially_completed
        else:
            request.request_status = TerminationRequestStatus.failed

        request.completed_at = datetime.now(timezone.utc)
        await db.flush()
        await db.commit()

        logger.info(
            "Termination request %s completed: scope=%s target=%s "
            "sessions=%d success=%d failure=%d status=%s",
            request.id,
            scope.value,
            target_session_id,
            len(session_ids),
            success_count,
            failure_count,
            request.request_status.value,
        )
        return request

    async def _terminate_single_session(
        self,
        *,
        session_id: uuid.UUID,
        request_id: uuid.UUID,
        cascade_level: int,
        db: AsyncSession,
        operator_reason: str | None = None,
    ) -> TerminationCascadeOutcome:
        """Terminate a single session and persist its cascade outcome.

        Phase 3.11: this is the cross-process termination point. The order
        matters — we tell Agent Runtime to cancel first, THEN update the
        Control Center's row, so the agent's eventual ``mark_session_*
        call cannot overwrite our ``failed`` + termination_category state
        (the inner ``update_session_status`` now refuses to demote a
        ``failed``/``completed`` state to ``running`` or to clear
        ``stop_category`` on ``completed`` when one is already set).
        """
        job = await db.get(AgentJob, session_id)

        if job is None:
            outcome = TerminationCascadeOutcome(
                termination_request_id=request_id,
                affected_agent_job_id=session_id,
                cascade_level=cascade_level,
                termination_outcome=TerminationOutcome.not_found,
                outcome_reason="Session not found",
            )
            db.add(outcome)
            return outcome

        if job.status in (
            AgentJobStatus.completed,
            AgentJobStatus.failed,
            AgentJobStatus.terminated,
        ):
            outcome = TerminationCascadeOutcome(
                termination_request_id=request_id,
                affected_agent_job_id=session_id,
                cascade_level=cascade_level,
                termination_outcome=TerminationOutcome.already_completed,
                outcome_reason=f"Session already in terminal status: {job.status.value}",
            )
            db.add(outcome)
            return outcome

        # Phase 3.11 step 1: tell Agent Runtime to cancel the in-flight task.
        # 404 (no in-flight task — already finished) is the success case.
        runtime_cancelled = False
        try:
            rt_result = await _agent_runtime_client.terminate_session(
                session_id=session_id, reason=operator_reason
            )
            runtime_cancelled = bool(rt_result and rt_result.get("cancelled"))
        except AgentRuntimeClientError as exc:
            # Don't fail the whole termination just because the runtime
            # call had a transport error — the DB transition is the
            # authoritative record.  The cancelled task will eventually
            # unwind and call mark_session_failed, but we've already
            # moved the state to failed/terminated.
            logger.warning(
                "Agent Runtime terminate call failed for session %s: %s; "
                "proceeding with DB transition",
                session_id,
                exc,
            )

        # Phase 3.12 step 2: persist the terminal transition.  Use the
        # distinct ``terminated`` status (not ``failed``) so the UI can
        # show "Terminated" instead of "Failed" for operator-initiated
        # cancellations.  ``failed`` is reserved for genuine
        # agent/runtime errors.
        try:
            job.status = AgentJobStatus.terminated
            job.completed_at = datetime.now(timezone.utc)
            job.error_message = "Terminated by operator request"
            if hasattr(job, "termination_category"):
                job.termination_category = (
                    AgentTerminationCategory.cascade_parent_terminated
                    if cascade_level > 0
                    else AgentTerminationCategory.user_requested
                )

            reason_text = (
                "Session terminated by operator cascade request"
                if cascade_level > 0
                else "Session terminated by operator request"
            )
            if runtime_cancelled:
                reason_text += " (Agent Runtime task cancelled)"

            # Cancel any pending intervene requests for this session
            # so the Control Center doesn't show orphaned pending requests
            # for a terminated session.
            try:
                from app.services.agents.intervene_service import (
                    InterveneRequestStore,
                )
                intervene_store = InterveneRequestStore()
                pending_request = await intervene_store._find_pending_for_session(
                    db, session_id
                )
                if pending_request is not None:
                    await intervene_store.cancel_request(db, pending_request.id)
                    logger.info(
                        "Cancelled pending intervene request %s for "
                        "terminated session %s",
                        pending_request.id,
                        session_id,
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to cancel pending intervene request for "
                    "session %s: %s",
                    session_id,
                    exc,
                )

            outcome = TerminationCascadeOutcome(
                termination_request_id=request_id,
                affected_agent_job_id=session_id,
                cascade_level=cascade_level,
                termination_outcome=TerminationOutcome.terminated,
                outcome_reason=reason_text,
            )
            db.add(outcome)
            logger.info(
                "Session %s terminated at cascade level %d (request %s, runtime_cancelled=%s)",
                session_id,
                cascade_level,
                request_id,
                runtime_cancelled,
            )
            return outcome

        except Exception as exc:
            logger.error(
                "Failed to terminate session %s (request %s): %s",
                session_id,
                request_id,
                exc,
            )
            outcome = TerminationCascadeOutcome(
                termination_request_id=request_id,
                affected_agent_job_id=session_id,
                cascade_level=cascade_level,
                termination_outcome=TerminationOutcome.failed,
                outcome_reason=f"Termination error: {exc}",
            )
            db.add(outcome)
            return outcome

    async def get_termination_request(
        self,
        request_id: uuid.UUID,
        db: AsyncSession,
    ) -> TerminationRequest | None:
        """Fetch a termination request by ID."""
        return await db.get(TerminationRequest, request_id)

    async def get_cascade_outcomes(
        self,
        request_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[TerminationCascadeOutcome]:
        """Fetch all cascade outcomes for a termination request."""
        result = await db.execute(
            select(TerminationCascadeOutcome).where(
                TerminationCascadeOutcome.termination_request_id == request_id
            )
        )
        return list(result.scalars().all())
