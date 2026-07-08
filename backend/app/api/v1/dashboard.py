"""Dashboard API router — exposes operational metrics aggregation endpoint."""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_claims
from app.db.session import get_db
from app.schemas.dashboard import DashboardSummary
from app.services.dashboard_metrics_service import DashboardMetricsService

logger = logging.getLogger(__name__)

DashboardRouter = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@DashboardRouter.get("/summary", response_model=DashboardSummary)
async def get_summary(
    request: Request,
    start_time: str | None = Query(
        default=None,
        description="ISO 8601 start datetime (defaults to 24 hours ago)",
    ),
    end_time: str | None = Query(
        default=None,
        description="ISO 8601 end datetime (defaults to now)",
    ),
    claims: dict = Depends(get_current_claims),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummary:
    """Return aggregated dashboard metrics with per-card permission flags.

    Permission enforcement is per-domain inside the service — the endpoint
    itself has no ``require_permission()`` guard.  A valid JWT is still
    required for authentication.
    """
    # Parse date range, defaulting to last 24 hours
    now = datetime.now(tz=timezone.utc)
    start_dt = _parse_datetime(start_time) if start_time else (now - timedelta(hours=24))
    end_dt = _parse_datetime(end_time) if end_time else now

    if start_dt > end_dt:
        raise HTTPException(
            status_code=422,
            detail="start_time must be before end_time",
        )

    try:
        service = DashboardMetricsService(db=db, claims=claims)
        return await service.aggregate_metrics(
            start_time=start_dt,
            end_time=end_dt,
        )
    except Exception as exc:
        logger.exception("Dashboard summary aggregation failed")
        raise HTTPException(
            status_code=500,
            detail="Failed to aggregate dashboard metrics",
        ) from exc


def _parse_datetime(value: str) -> datetime:
    """Parse an ISO 8601 datetime string, raising 422 on invalid input."""
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid datetime value: {value}. Expected ISO 8601 format.",
        ) from exc
