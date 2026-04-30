"""API tests for the group-optional access request endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.db.models.access_request import AccessRequest, AccessRequestStatus
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware
from app.schemas.access_requests import (
    AccessRequestBatchRead,
    AccessRequestRead,
    AccessRequestStatusEnum,
)
from app.services.permissions.permission_engine import AuthorizationResult


def _bypass_auth():
    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "user-sub", "roles": ["admin"]}
        request.state.platform_user_id = uuid.uuid4()
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


def _mock_permission_engine_allow():
    async def mock_authorize(*args, **kwargs):
        return AuthorizationResult(allowed=True, reason="Test override")

    return patch(
        "app.services.permissions.permission_engine.PermissionEngine.authorize",
        mock_authorize,
    )


def _make_db_override(get_return=None):
    """DB session override: execute() returns a mock PlatformUser; get() returns get_return."""
    mock_session = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    mock_user.sub = "user-sub"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=mock_user)
    mock_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[]))
    )
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.get = AsyncMock(return_value=get_return)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    async def override():
        yield mock_session

    return mock_session, override


# ---------------------------------------------------------------------------
# Task 4.2 test cases
# ---------------------------------------------------------------------------


class TestSubmitAccessRequestEmptyGroups:
    """POST /user-access-requests with group_ids: []."""

    @pytest.mark.asyncio
    async def test_empty_group_ids_returns_201_with_null_group(self):
        """POST /user-access-requests with body {"group_ids": [], "justification": "..."}
        returns HTTP 201 and a batch containing one request where group_id is null."""
        req_id = uuid.uuid4()
        batch_id = uuid.uuid4()
        user_id = uuid.uuid4()
        now = datetime.utcnow()

        mock_batch = MagicMock()
        mock_batch.id = batch_id

        expected_batch_read = AccessRequestBatchRead(
            id=batch_id,
            user_id=user_id,
            justification="I need access",
            submitted_at=now,
            requests=[
                AccessRequestRead(
                    id=req_id,
                    batch_id=batch_id,
                    user_id=user_id,
                    group_id=None,
                    status=AccessRequestStatusEnum.pending,
                    reviewer_id=None,
                    reviewer_reason=None,
                    created_at=now,
                    updated_at=now,
                )
            ],
        )

        _, db_dep = _make_db_override()
        app = create_app()
        app.dependency_overrides[get_db] = db_dep

        with (
            _bypass_auth(),
            _mock_permission_engine_allow(),
            patch("app.api.v1.user_access_requests.AccessRequestService") as MockSvc,
            patch(
                "app.api.v1.user_access_requests._load_batch_with_requests",
                new=AsyncMock(return_value=expected_batch_read),
            ),
        ):
            MockSvc.return_value.submit_batch_request = AsyncMock(return_value=mock_batch)

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/user-access-requests",
                    json={"group_ids": [], "justification": "I need access"},
                )

        assert response.status_code == 201
        data = response.json()
        assert len(data["requests"]) == 1
        assert data["requests"][0]["group_id"] is None


class TestApproveRequestWithGroupAssignment:
    """PATCH /user-access-requests/{id}/approve with group_id in body."""

    @pytest.mark.asyncio
    async def test_approve_with_group_id_returns_200_with_group_assigned(self):
        """PATCH /user-access-requests/{id}/approve with {"group_id": "<uuid>"}
        for a group-less request returns HTTP 200 and the response contains
        the assigned group_id."""
        req_id = uuid.uuid4()
        group_id = uuid.uuid4()
        user_id = uuid.uuid4()
        now = datetime.utcnow()

        mock_req = MagicMock(spec=AccessRequest)
        mock_req.id = req_id
        mock_req.group_id = None
        mock_req.status = AccessRequestStatus.pending

        mock_updated = MagicMock(spec=AccessRequest)
        mock_updated.group_id = group_id

        expected_read = AccessRequestRead(
            id=req_id,
            batch_id=uuid.uuid4(),
            user_id=user_id,
            group_id=group_id,
            status=AccessRequestStatusEnum.approved,
            reviewer_id=None,
            reviewer_reason=None,
            created_at=now,
            updated_at=now,
        )

        _, db_dep = _make_db_override(get_return=mock_req)
        app = create_app()
        app.dependency_overrides[get_db] = db_dep

        with (
            _bypass_auth(),
            _mock_permission_engine_allow(),
            patch("app.api.v1.user_access_requests.AccessRequestService") as MockSvc,
            patch(
                "app.api.v1.user_access_requests._enrich_request",
                new=AsyncMock(return_value=expected_read),
            ),
        ):
            MockSvc.return_value.approve_request = AsyncMock(return_value=mock_updated)

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.patch(
                    f"/api/v1/user-access-requests/{req_id}/approve",
                    json={"group_id": str(group_id)},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["group_id"] == str(group_id)

    @pytest.mark.asyncio
    async def test_approve_group_less_request_without_group_id_returns_400(self):
        """PATCH /user-access-requests/{id}/approve without group_id in the body
        for a request that has no group assigned returns HTTP 400."""
        req_id = uuid.uuid4()

        mock_req = MagicMock(spec=AccessRequest)
        mock_req.id = req_id
        mock_req.group_id = None
        mock_req.status = AccessRequestStatus.pending

        _, db_dep = _make_db_override(get_return=mock_req)
        app = create_app()
        app.dependency_overrides[get_db] = db_dep

        with (
            _bypass_auth(),
            _mock_permission_engine_allow(),
            patch("app.api.v1.user_access_requests.AccessRequestService") as MockSvc,
        ):
            MockSvc.return_value.approve_request = AsyncMock(
                side_effect=HTTPException(
                    status_code=400,
                    detail="group_id is required when approving a request with no assigned group.",
                )
            )

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.patch(
                    f"/api/v1/user-access-requests/{req_id}/approve",
                    json={},
                )

        assert response.status_code == 400
