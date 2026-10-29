"""Dashboard API router — exposes operational metrics aggregation endpoint."""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_claims
from app.db.session import get_db
from app.schemas.dashboard import DashboardSummary
from app.schemas.token_health import (
    TokenHealthCategorySummary,
    TokenHealthItem,
    TokenHealthPermissionFlags,
    TokenHealthSummary,
)
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


# ── Token Health (token-expiry-alerting) ──────────────────────────────────────

_TOKEN_HEALTH_PERMISSION_MAP: dict[str, tuple[str, str]] = {
    "identities": ("agent::identities", "read"),
    "mcp_sessions": ("integration::mcp_hub", "read"),
}


async def _resolve_dashboard_user_id(db: AsyncSession, claims: dict):
    """Resolve the caller's PlatformUser id (platform-level, unscoped)."""
    from sqlalchemy import select

    from app.db.models.platform_user import PlatformUser
    from app.db.tenant_scoping import execute_unscoped

    if claims.get("is_super_admin"):
        return None
    sub: str | None = claims.get("sub")
    if not sub:
        return False
    result = await execute_unscoped(
        db, select(PlatformUser.id).where(PlatformUser.sub == sub)
    )
    return result.scalar_one_or_none()


async def _check_token_health_permission(
    db: AsyncSession, claims: dict, user_id, domain: str
) -> bool:
    """PermissionEngine check for one token-health category."""
    from app.services.permissions.permission_engine import PermissionEngine

    if claims.get("is_super_admin"):
        return True
    if user_id is None or user_id is False:
        return False
    module, action = _TOKEN_HEALTH_PERMISSION_MAP[domain]
    auth = await PermissionEngine().authorize(
        db=db, user_id=user_id, module=module, action=action,
        resource_id="*", resource_tags={},
    )
    return auth.allowed


@DashboardRouter.get("/token-health", response_model=TokenHealthSummary)
async def get_token_health(
    request: Request,
    claims: dict = Depends(get_current_claims),
    db: AsyncSession = Depends(get_db),
) -> TokenHealthSummary:
    """Return expired / expiring token counts and itemized details.

    Per-category permission enforcement mirrors ``DashboardSummary``:
    a category the caller cannot read is flagged in ``permission_flags``
    (the frontend renders a "Permission Denied" placeholder) instead of
    the endpoint returning 403. A valid JWT is still required.
    """
    from app.services.token_health import TokenHealthService

    user_id = await _resolve_dashboard_user_id(db, claims)
    service = TokenHealthService(db)

    identities_flag = not await _check_token_health_permission(
        db, claims, user_id, "identities"
    )
    sessions_flag = not await _check_token_health_permission(
        db, claims, user_id, "mcp_sessions"
    )

    now = datetime.now(tz=timezone.utc)

    identities_summary = TokenHealthCategorySummary()
    if not identities_flag:
        targets = await service.list_identity_states()
        identities_summary = await _summarize_identities(db, targets, now)

    sessions_summary = TokenHealthCategorySummary()
    if not sessions_flag:
        sessions_summary = await _summarize_sessions(db, now)

    return TokenHealthSummary(
        identities=identities_summary,
        mcp_sessions=sessions_summary,
        permission_flags=TokenHealthPermissionFlags(
            identities=identities_flag,
            mcp_sessions=sessions_flag,
        ),
    )


async def _summarize_identities(db: AsyncSession, targets, now: datetime) -> TokenHealthCategorySummary:
    """Build the identity category summary from computed target states."""
    from app.db.models.agents import AgentIdentity

    summary = TokenHealthCategorySummary()
    identity_rows = {
        row.id: row
        for row in (
            await db.execute(select(AgentIdentity))
        ).scalars().all()
    }
    for target in targets:
        row = identity_rows.get(target.id)
        item = TokenHealthItem(
            id=target.id,
            name=target.name,
            health_state=target.state,
            expires_at=row.token_expires_at if row else None,
            refresh_expires_at=row.refresh_token_expires_at if row else None,
            last_refresh_outcome=(
                row.last_token_refresh_outcome.value if row and row.last_token_refresh_outcome else None
            ),
            last_refresh_at=row.last_token_refresh_at if row else None,
            remediation_target="agent_identity",
            remediation_path="/agents/identities",
        )
        _accumulate(summary, item)
    return summary


async def _summarize_sessions(db: AsyncSession, now: datetime) -> TokenHealthCategorySummary:
    """Build the MCP session category summary (active OAuth2 sessions only)."""
    from app.db.models.mcp_hub import McpSession, McpSessionAuthType
    from app.services.token_health import compute_session_state

    summary = TokenHealthCategorySummary()
    result = await db.execute(
        select(McpSession).where(
            McpSession.is_active == True,  # noqa: E712
            McpSession.auth_type == McpSessionAuthType.oauth2,
        )
    )
    for session in result.scalars().all():
        item = TokenHealthItem(
            id=session.id,
            name=session.name,
            health_state=compute_session_state(session, now),
            expires_at=session.oauth_expires_at,
            refresh_expires_at=session.oauth_refresh_expires_at,
            last_refresh_outcome=(
                session.last_token_refresh_outcome.value
                if session.last_token_refresh_outcome
                else None
            ),
            last_refresh_at=session.last_token_refresh_at,
            remediation_target="mcp_session",
            remediation_path="/mcp",
        )
        _accumulate(summary, item)
    return summary


def _accumulate(summary: TokenHealthCategorySummary, item: TokenHealthItem) -> None:
    """Fold one item into its category summary (counts + capped itemization)."""
    from app.db.models.token_health import TokenHealthState

    if item.health_state == TokenHealthState.expired:
        summary.expired_count += 1
    elif item.health_state == TokenHealthState.expiring:
        summary.expiring_count += 1
    elif item.health_state == TokenHealthState.healthy:
        summary.healthy_count += 1
    else:
        summary.unknown_count += 1
    # Itemize only the actionable states, capped to keep the payload small.
    if item.health_state in (TokenHealthState.expired, TokenHealthState.expiring) and len(summary.items) < 50:
        summary.items.append(item)
