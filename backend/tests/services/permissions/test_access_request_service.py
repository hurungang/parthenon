"""Unit tests for AccessRequestService — group-optional access request behaviour."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.db.models.access_request import AccessRequest, AccessRequestStatus
from app.db.models.user_group import UserGroup
from app.services.permissions.access_request_service import AccessRequestService


def _make_service() -> AccessRequestService:
    """Create AccessRequestService with a mocked notification hook."""
    svc = AccessRequestService()
    svc._hook = AsyncMock()
    return svc


# ---------------------------------------------------------------------------
# Task 4.1 test cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSubmitBatchRequestGroupLess:
    """Submitting a request with group_ids=[]."""

    async def test_empty_group_ids_creates_one_request_with_null_group(self, db_session):
        """Calling submit_batch_request with group_ids=[] creates a batch with
        exactly one AccessRequest where group_id is None."""
        user_id = uuid.uuid4()
        svc = _make_service()

        batch = await svc.submit_batch_request(db_session, user_id, [], "I need access")

        result = await db_session.execute(
            select(AccessRequest).where(AccessRequest.batch_id == batch.id)
        )
        requests = list(result.scalars().all())

        assert len(requests) == 1
        assert requests[0].group_id is None
        assert requests[0].status == AccessRequestStatus.pending

    async def test_duplicate_group_less_request_raises_409(self, db_session):
        """A second group-less submission by the same user while one is pending
        raises HTTPException with status_code=409."""
        user_id = uuid.uuid4()
        svc = _make_service()

        await svc.submit_batch_request(db_session, user_id, [], "First request")

        with pytest.raises(HTTPException) as exc_info:
            await svc.submit_batch_request(db_session, user_id, [], "Duplicate request")

        assert exc_info.value.status_code == 409


@pytest.mark.asyncio
class TestApproveRequestGroupAssignment:
    """Approving a group-less request via the service."""

    async def test_approve_group_less_without_group_id_raises_400(self, db_session):
        """Approving a request with group_id=None on the record and no group_id
        argument raises HTTPException with status_code=400."""
        user_id = uuid.uuid4()
        reviewer_id = uuid.uuid4()
        svc = _make_service()

        batch = await svc.submit_batch_request(db_session, user_id, [], "Need access")
        result = await db_session.execute(
            select(AccessRequest).where(AccessRequest.batch_id == batch.id)
        )
        req = result.scalar_one()

        with pytest.raises(HTTPException) as exc_info:
            await svc.approve_request(db_session, req.id, reviewer_id, None, None)

        assert exc_info.value.status_code == 400

    async def test_approve_group_less_with_group_id_assigns_group_and_creates_membership(
        self, db_session
    ):
        """Approving a group-less request with a valid group_id sets
        request.group_id and creates a UserGroup membership row."""
        user_id = uuid.uuid4()
        reviewer_id = uuid.uuid4()
        group_id = uuid.uuid4()
        svc = _make_service()

        batch = await svc.submit_batch_request(db_session, user_id, [], "Need access")
        result = await db_session.execute(
            select(AccessRequest).where(AccessRequest.batch_id == batch.id)
        )
        req = result.scalar_one()
        assert req.group_id is None

        approved = await svc.approve_request(db_session, req.id, reviewer_id, "Welcome!", group_id)

        assert approved.status == AccessRequestStatus.approved
        assert approved.group_id == group_id

        membership_result = await db_session.execute(
            select(UserGroup).where(
                UserGroup.user_id == user_id,
                UserGroup.group_id == group_id,
            )
        )
        membership = membership_result.scalar_one_or_none()
        assert membership is not None

    async def test_approve_request_with_existing_group_id_succeeds_without_body_group(
        self, db_session
    ):
        """Approving a request that already has a group_id stored succeeds even
        when no group_id is passed to the service method."""
        user_id = uuid.uuid4()
        reviewer_id = uuid.uuid4()
        stored_group_id = uuid.uuid4()
        svc = _make_service()

        batch = await svc.submit_batch_request(
            db_session, user_id, [stored_group_id], "Need access"
        )
        result = await db_session.execute(
            select(AccessRequest).where(AccessRequest.batch_id == batch.id)
        )
        req = result.scalar_one()
        assert req.group_id == stored_group_id

        approved = await svc.approve_request(db_session, req.id, reviewer_id, None, None)

        assert approved.status == AccessRequestStatus.approved
        assert approved.group_id == stored_group_id
