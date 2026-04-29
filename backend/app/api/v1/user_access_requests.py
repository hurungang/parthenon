"""Access Requests API router."""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_claims, require_permission
from app.core.resource_types import RT_ACCESS_REQUEST
from app.db.models.access_request import AccessRequest, AccessRequestStatus
from app.db.models.access_request_batch import AccessRequestBatch
from app.db.models.group import Group
from app.db.models.platform_user import PlatformUser
from app.db.session import DbSession
from app.schemas.access_requests import (
    AccessRequestBatchCreate,
    AccessRequestBatchRead,
    AccessRequestRead,
    ApproveRequestBody,
    RejectRequestBody,
)
from app.services.permissions.access_request_service import AccessRequestService

AccessRequestsRouter = APIRouter(prefix="/user-access-requests", tags=["Permissions: Access Requests"])


def _get_platform_user_id(request: Request) -> uuid.UUID | None:
    return getattr(request.state, "platform_user_id", None)


async def _enrich_request(db: DbSession, req: AccessRequest) -> AccessRequestRead:
    """Populate group_name and requester_display_name on an AccessRequest."""
    group_name: str | None = None
    requester_name: str | None = None

    group = await db.get(Group, req.group_id)
    if group:
        group_name = group.name

    user = await db.get(PlatformUser, req.user_id)
    if user:
        requester_name = user.display_name

    read = AccessRequestRead.model_validate(req)
    return read.model_copy(update={
        "group_name": group_name,
        "requester_display_name": requester_name,
    })


async def _load_batch_with_requests(
    db: DbSession, batch: AccessRequestBatch
) -> AccessRequestBatchRead:
    """Build AccessRequestBatchRead with enriched requests."""
    result = await db.execute(
        select(AccessRequest).where(AccessRequest.batch_id == batch.id)
        .order_by(AccessRequest.created_at)
    )
    requests = result.scalars().all()
    enriched = [await _enrich_request(db, r) for r in requests]
    batch_read = AccessRequestBatchRead.model_validate(batch)
    return batch_read.model_copy(update={"requests": enriched})


@AccessRequestsRouter.post(
    "",
    response_model=AccessRequestBatchRead,
    status_code=status.HTTP_201_CREATED,
)
async def submit_access_request(
    body: AccessRequestBatchCreate,
    request: Request,
    db: DbSession,
) -> AccessRequestBatchRead:
    """Submit a batch access request for one or more groups. Authenticated users."""
    platform_user_id = _get_platform_user_id(request)
    if platform_user_id is None:
        raise HTTPException(status_code=403, detail="User identity not resolved. Please re-authenticate.")

    svc = AccessRequestService()
    batch = await svc.submit_batch_request(db, platform_user_id, body.group_ids, body.justification)
    return await _load_batch_with_requests(db, batch)


@AccessRequestsRouter.get("/my", response_model=List[AccessRequestBatchRead])
async def list_my_requests(
    request: Request,
    db: DbSession,
) -> List[AccessRequestBatchRead]:
    """List the current user's access request batches. Authenticated users."""
    platform_user_id = _get_platform_user_id(request)
    if platform_user_id is None:
        raise HTTPException(status_code=403, detail="User identity not resolved.")

    result = await db.execute(
        select(AccessRequestBatch)
        .where(AccessRequestBatch.user_id == platform_user_id)
        .order_by(AccessRequestBatch.submitted_at.desc())
    )
    batches = result.scalars().all()
    return [await _load_batch_with_requests(db, b) for b in batches]


@AccessRequestsRouter.get("/pending", response_model=List[AccessRequestRead])
async def list_pending_requests(
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_ACCESS_REQUEST, "read")),
) -> List[AccessRequestRead]:
    """List pending access requests. Requires access_request:read permission."""
    result = await db.execute(
        select(AccessRequest)
        .where(AccessRequest.status == AccessRequestStatus.pending)
        .order_by(AccessRequest.created_at.desc())
    )
    requests = result.scalars().all()
    return [await _enrich_request(db, r) for r in requests]


@AccessRequestsRouter.patch("/{request_id}/approve", response_model=AccessRequestRead)
async def approve_request(
    request_id: uuid.UUID,
    body: ApproveRequestBody,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_ACCESS_REQUEST, "approve")),
) -> AccessRequestRead:
    """Approve an access request. Requires access_request:approve permission."""
    platform_user_id = _get_platform_user_id(request)
    if platform_user_id is None:
        raise HTTPException(status_code=403, detail="User identity not resolved.")

    req_obj = await db.get(AccessRequest, request_id)
    if not req_obj:
        raise HTTPException(status_code=404, detail="Access request not found.")

    svc = AccessRequestService()
    updated = await svc.approve_request(db, request_id, platform_user_id, body.approval_reason)
    return await _enrich_request(db, updated)


@AccessRequestsRouter.patch("/{request_id}/reject", response_model=AccessRequestRead)
async def reject_request(
    request_id: uuid.UUID,
    body: RejectRequestBody,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_ACCESS_REQUEST, "reject")),
) -> AccessRequestRead:
    """Reject an access request. Requires access_request:reject permission."""
    platform_user_id = _get_platform_user_id(request)
    if platform_user_id is None:
        raise HTTPException(status_code=403, detail="User identity not resolved.")

    req_obj = await db.get(AccessRequest, request_id)
    if not req_obj:
        raise HTTPException(status_code=404, detail="Access request not found.")

    svc = AccessRequestService()
    updated = await svc.reject_request(db, request_id, platform_user_id, body.rejection_reason)
    return await _enrich_request(db, updated)
