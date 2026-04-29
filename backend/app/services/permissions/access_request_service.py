"""Access Request Service — handles group join request lifecycle."""
import logging
import uuid
from typing import List

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.access_request import AccessRequest, AccessRequestStatus
from app.db.models.access_request_batch import AccessRequestBatch
from app.db.models.user_group import UserGroup
from app.services.permissions.notification_hook import NotificationHook

logger = logging.getLogger(__name__)


class AccessRequestService:
    """Manages the full lifecycle of group join requests."""

    def __init__(self) -> None:
        self._hook = NotificationHook()

    async def submit_batch_request(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        group_ids: List[uuid.UUID],
        justification: str,
    ) -> AccessRequestBatch:
        """Create an AccessRequestBatch + one AccessRequest per group_id.

        Raises HTTPException 409 if any user/group pair already has a pending request.
        Notifies each group owner after creation.
        """
        # Check for existing pending requests
        for group_id in group_ids:
            existing = await db.execute(
                select(AccessRequest).where(
                    AccessRequest.user_id == user_id,
                    AccessRequest.group_id == group_id,
                    AccessRequest.status == AccessRequestStatus.pending,
                )
            )
            if existing.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=409,
                    detail=f"A pending request already exists for group {group_id}.",
                )

        # Create the batch
        batch = AccessRequestBatch(
            user_id=user_id,
            justification=justification,
        )
        db.add(batch)
        await db.flush()

        # Create one AccessRequest per group
        for group_id in group_ids:
            req = AccessRequest(
                batch_id=batch.id,
                user_id=user_id,
                group_id=group_id,
                status=AccessRequestStatus.pending,
            )
            db.add(req)

        await db.flush()
        await db.refresh(batch)

        # Notify owners (fire-and-ignore errors)
        for group_id in group_ids:
            try:
                await self._hook.notify_owner_new_request(db, group_id, user_id)
            except Exception as exc:
                logger.warning("Owner notification failed for group %s: %s", group_id, exc)

        return batch

    async def approve_request(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        reviewer_id: uuid.UUID,
        reviewer_reason: str | None = None,
    ) -> AccessRequest:
        """Approve an access request and create the UserGroup membership.

        Raises HTTPException 404 if request not found.
        Raises HTTPException 400 if request is not in pending state.
        """
        request = await db.get(AccessRequest, request_id)
        if request is None:
            raise HTTPException(status_code=404, detail="Access request not found.")
        if request.status != AccessRequestStatus.pending:
            raise HTTPException(
                status_code=400,
                detail=f"Request is already {request.status.value}.",
            )

        request.status = AccessRequestStatus.approved
        request.reviewer_id = reviewer_id
        request.reviewer_reason = reviewer_reason

        # Create UserGroup membership
        existing = await db.execute(
            select(UserGroup).where(
                UserGroup.user_id == request.user_id,
                UserGroup.group_id == request.group_id,
            )
        )
        if existing.scalar_one_or_none() is None:
            membership = UserGroup(
                user_id=request.user_id,
                group_id=request.group_id,
                join_reason=f"Approved via access request {request_id}",
            )
            db.add(membership)

        await db.flush()
        await db.refresh(request)

        try:
            await self._hook.notify_requester_decision(db, request_id)
        except Exception as exc:
            logger.warning("Requester notification failed for request %s: %s", request_id, exc)

        return request

    async def reject_request(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        reviewer_id: uuid.UUID,
        reviewer_reason: str,
    ) -> AccessRequest:
        """Reject an access request. reviewer_reason is REQUIRED.

        Raises HTTPException 404 if request not found.
        Raises HTTPException 400 if request is not in pending state.
        """
        request = await db.get(AccessRequest, request_id)
        if request is None:
            raise HTTPException(status_code=404, detail="Access request not found.")
        if request.status != AccessRequestStatus.pending:
            raise HTTPException(
                status_code=400,
                detail=f"Request is already {request.status.value}.",
            )

        request.status = AccessRequestStatus.rejected
        request.reviewer_id = reviewer_id
        request.reviewer_reason = reviewer_reason

        await db.flush()
        await db.refresh(request)

        try:
            await self._hook.notify_requester_decision(db, request_id)
        except Exception as exc:
            logger.warning("Requester notification failed for request %s: %s", request_id, exc)

        return request

    async def list_requests(
        self,
        db: AsyncSession,
        group_id: uuid.UUID,
        status: str | None = None,
    ) -> List[AccessRequest]:
        """List AccessRequests for a group, optionally filtered by status."""
        stmt = select(AccessRequest).where(AccessRequest.group_id == group_id)
        if status is not None:
            stmt = stmt.where(AccessRequest.status == status)
        result = await db.execute(stmt.order_by(AccessRequest.created_at.desc()))
        return list(result.scalars().all())
