"""AgentSessionService — manages AgentJob lifecycle: enqueue, status transitions, persistence."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket
from opentelemetry import trace
from sqlalchemy import select

from app.db.models.agents import AgentJob, AgentJobStatus

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class AgentSessionService:
    """
    Provides async methods to create, track, and transition AgentJob sessions.

    State machine:
        queued → running → completed
                         → failed
    """

    async def enqueue(
        self,
        agent_type_id: uuid.UUID,
        input_data: dict[str, Any] | None,
        user_id: uuid.UUID | None,
        db: AsyncSession,
    ) -> AgentJob:
        """Create a new AgentJob with status=queued and return it immediately."""
        with tracer.start_as_current_span(
            "session_service.enqueue",
            attributes={
                "agent_type_id": str(agent_type_id),
                "user_id": str(user_id) if user_id else "anonymous",
            },
        ):
            job = AgentJob(
                agent_type_id=agent_type_id,
                triggered_by_user_id=user_id,
                input_data=input_data,
                status=AgentJobStatus.queued,
            )
            db.add(job)
            await db.flush()
            await db.refresh(job)
            logger.info(
                "Enqueued AgentJob %s for type %s (user=%s)",
                job.id,
                agent_type_id,
                user_id,
            )
            return job

    async def mark_running(self, session_id: uuid.UUID, db: AsyncSession) -> AgentJob:
        """Transition a queued session to running."""
        with tracer.start_as_current_span(
            "session_service.mark_running",
            attributes={"session_id": str(session_id)},
        ):
            job = await self._get_or_raise(session_id, db)
            job.status = AgentJobStatus.running
            job.started_at = datetime.now(timezone.utc)
            await db.flush()
            await db.refresh(job)
            logger.info("Session %s transitioned to running", session_id)
            return job

    async def mark_completed(
        self,
        session_id: uuid.UUID,
        output_data: dict[str, Any],
        db: AsyncSession,
    ) -> AgentJob:
        """Transition a running session to completed and persist output_data."""
        with tracer.start_as_current_span(
            "session_service.mark_completed",
            attributes={"session_id": str(session_id)},
        ):
            job = await self._get_or_raise(session_id, db)
            job.status = AgentJobStatus.completed
            job.completed_at = datetime.now(timezone.utc)
            job.output_data = output_data
            await db.flush()
            await db.refresh(job)
            logger.info("Session %s completed successfully", session_id)
            return job

    async def mark_failed(
        self,
        session_id: uuid.UUID,
        error_message: str,
        db: AsyncSession,
    ) -> AgentJob:
        """Transition a session to failed and record the error message."""
        with tracer.start_as_current_span(
            "session_service.mark_failed",
            attributes={"session_id": str(session_id), "error": error_message},
        ):
            job = await self._get_or_raise(session_id, db)
            job.status = AgentJobStatus.failed
            job.completed_at = datetime.now(timezone.utc)
            job.error_message = error_message
            await db.flush()
            await db.refresh(job)
            logger.error("Session %s failed: %s", session_id, error_message)
            return job

    async def get_session(
        self, session_id: uuid.UUID, db: AsyncSession
    ) -> AgentJob | None:
        """Fetch an AgentJob by ID. Returns None if not found."""
        return await db.get(AgentJob, session_id)

    async def list_sessions(
        self,
        user_id: uuid.UUID | None,
        db: AsyncSession,
        status: AgentJobStatus | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        agent_type_id: uuid.UUID | None = None,
    ) -> list[AgentJob]:
        """List AgentJobs triggered by the given user (or all if user_id is None),
        with optional filters for status, date range, and agent type."""
        query = select(AgentJob).order_by(AgentJob.created_at.desc())
        if user_id is not None:
            query = query.where(AgentJob.triggered_by_user_id == user_id)
        if status is not None:
            query = query.where(AgentJob.status == status)
        if from_date is not None:
            query = query.where(AgentJob.created_at >= from_date)
        if to_date is not None:
            query = query.where(AgentJob.created_at <= to_date)
        if agent_type_id is not None:
            query = query.where(AgentJob.agent_type_id == agent_type_id)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def handle_chat_websocket(
        self,
        session_id: uuid.UUID,
        websocket: WebSocket,
        db: AsyncSession,
        conv_session_id: uuid.UUID | None = None,
    ) -> None:
        """
        Maintain a bidirectional WebSocket connection for conversational agents.

        Messages from the client are forwarded to the runtime executor's chat queue.
        Responses from the executor are forwarded back to the client.

        When conv_session_id is provided, the first user message triggers
        SessionAutoNamer as a background task, which pushes a title_update event
        to this client when complete.

        This is a simplified implementation; production would use Redis pub/sub.
        """
        import asyncio

        from app.services.conversations.auto_namer import SessionAutoNamer

        with tracer.start_as_current_span(
            "session_service.chat_websocket",
            attributes={"session_id": str(session_id)},
        ):
            message_count = 0
            try:
                while True:
                    data = await websocket.receive_json()
                    message = data.get("message", "")
                    message_count += 1
                    logger.debug("Chat message for session %s: %s", session_id, message)

                    # Echo acknowledgement — real implementation dispatches to runtime
                    await websocket.send_json({
                        "type": "ack",
                        "session_id": str(session_id),
                        "message": "Message received — processing",
                    })

                    # Trigger auto-naming after the first user message
                    if message_count == 1 and conv_session_id and message:
                        asyncio.create_task(
                            self._auto_name_and_push(
                                conv_session_id=conv_session_id,
                                first_message=message,
                                websocket=websocket,
                            )
                        )
            except Exception as exc:
                logger.debug("Chat WebSocket closed for session %s: %s", session_id, exc)

    async def _auto_name_and_push(
        self,
        conv_session_id: uuid.UUID,
        first_message: str,
        websocket: WebSocket,
    ) -> None:
        """Background task: generate a session title and push title_update to the WebSocket."""
        from app.db.session import AsyncSessionLocal
        from app.db.models.conversations import ConversationSession
        from app.services.conversations.auto_namer import SessionAutoNamer

        try:
            async with AsyncSessionLocal() as db:
                conv_session = await db.get(ConversationSession, conv_session_id)
                agent_type_id = conv_session.agent_type_id if conv_session else None
                namer = SessionAutoNamer()
                title = await namer.generate_and_save(
                    session_id=conv_session_id,
                    first_user_message=first_message,
                    agent_type_id=agent_type_id,
                    db=db,
                )
            await websocket.send_json({"type": "title_update", "title": title})
        except Exception as exc:
            logger.warning("Auto-naming background task failed: %s", exc)

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _get_or_raise(self, session_id: uuid.UUID, db: AsyncSession) -> AgentJob:
        """Fetch an AgentJob or raise ValueError if not found."""
        job = await db.get(AgentJob, session_id)
        if not job:
            raise ValueError(f"AgentJob {session_id} not found")
        return job
