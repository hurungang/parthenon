"""Token Health Service — Control Center's single owner of token expiry state.

Computes the token health classification (``healthy`` / ``expiring`` /
``expired`` / ``unknown``) for agent identities and MCP sessions as a PURE
function of timestamps, refresh outcome and entity status, and persists the
denormalized ``token_health_state`` on the entities after every refresh.

Tenant scoping: all database queries run on the request-scoped, tenant-scoped
async session (see ``app.db.session``) — this service never bypasses the
tenant scope. Only Control Center may import this module (only CC touches
the database).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_security import TokenRefreshLog, TokenRefreshOutcome
from app.db.models.agents import AgentIdentity, AgentTokenStatus
from app.db.models.mcp_hub import McpSession, McpSessionAuthType
from app.db.models.token_health import (
    TokenCheckOutcome,
    TokenHealthCheck,
    TokenHealthState,
    TokenHealthTargetKind,
)

logger = logging.getLogger(__name__)

# A token expiring within this window is classified as "expiring".
TOKEN_EXPIRING_WINDOW: timedelta = timedelta(days=7)


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """Coerce a (possibly naive) datetime to timezone-aware UTC.

    SQLite-backed sessions return naive datetimes; comparisons must be
    consistent.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


# ── Pure classification (unit-testable, no I/O) ───────────────────────────────


def classify_identity_health(
    *,
    token_expires_at: datetime | None,
    refresh_token_expires_at: datetime | None,
    token_status: AgentTokenStatus | str | None,
    last_token_refresh_outcome: TokenRefreshOutcome | str | None,
    now: datetime | None = None,
) -> TokenHealthState:
    """Classify an agent identity's token health.

    Rules (evaluated in order):
    - No access-token expiry recorded → ``unknown``.
    - ``token_status`` is ``refresh_failed`` or the last refresh failed →
      the access token can no longer be renewed → ``expired``.
    - Access token past expiry → ``expired``.
    - Refresh token past expiry (cannot renew) → ``expired``.
    - Access token or refresh token expiring within
      :data:`TOKEN_EXPIRING_WINDOW` → ``expiring``.
    - Otherwise → ``healthy``.
    """
    now = _aware(now) or _now_utc()
    status = AgentTokenStatus(token_status) if isinstance(token_status, str) else token_status
    outcome = (
        TokenRefreshOutcome(last_token_refresh_outcome)
        if isinstance(last_token_refresh_outcome, str)
        else last_token_refresh_outcome
    )

    token_expires_at = _aware(token_expires_at)
    refresh_token_expires_at = _aware(refresh_token_expires_at)

    if token_expires_at is None:
        return TokenHealthState.unknown
    if status == AgentTokenStatus.refresh_failed or outcome == TokenRefreshOutcome.failure:
        return TokenHealthState.expired
    if token_expires_at <= now:
        return TokenHealthState.expired
    if refresh_token_expires_at is not None and refresh_token_expires_at <= now:
        return TokenHealthState.expired

    access_threshold = now + TOKEN_EXPIRING_WINDOW
    if token_expires_at <= access_threshold:
        return TokenHealthState.expiring
    if refresh_token_expires_at is not None and refresh_token_expires_at <= access_threshold:
        return TokenHealthState.expiring
    return TokenHealthState.healthy


def classify_session_health(
    *,
    oauth_expires_at: datetime | None,
    oauth_refresh_expires_at: datetime | None,
    now: datetime | None = None,
) -> TokenHealthState:
    """Classify an MCP session's OAuth token health (same rules as identities)."""
    now = _aware(now) or _now_utc()
    oauth_expires_at = _aware(oauth_expires_at)
    oauth_refresh_expires_at = _aware(oauth_refresh_expires_at)
    if oauth_expires_at is None:
        return TokenHealthState.unknown
    if oauth_expires_at <= now:
        return TokenHealthState.expired
    if oauth_refresh_expires_at is not None and oauth_refresh_expires_at <= now:
        return TokenHealthState.expired

    threshold = now + TOKEN_EXPIRING_WINDOW
    if oauth_expires_at <= threshold:
        return TokenHealthState.expiring
    if oauth_refresh_expires_at is not None and oauth_refresh_expires_at <= threshold:
        return TokenHealthState.expiring
    return TokenHealthState.healthy


def compute_identity_state(identity: AgentIdentity, now: datetime | None = None) -> TokenHealthState:
    """Compute (read-time) health state for an ``AgentIdentity`` row."""
    return classify_identity_health(
        token_expires_at=identity.token_expires_at,
        refresh_token_expires_at=identity.refresh_token_expires_at,
        token_status=identity.token_status,
        last_token_refresh_outcome=identity.last_token_refresh_outcome,
        now=now,
    )


def compute_session_state(session: McpSession, now: datetime | None = None) -> TokenHealthState:
    """Compute (read-time) health state for an ``McpSession`` row."""
    return classify_session_health(
        oauth_expires_at=session.oauth_expires_at,
        oauth_refresh_expires_at=session.oauth_refresh_expires_at,
        now=now,
    )


# ── Persistence (called from the refresh flows) ───────────────────────────────


def persist_identity_health_state(
    identity: AgentIdentity,
    *,
    refresh_outcome: TokenRefreshOutcome,
) -> TokenHealthState:
    """Recompute and persist health fields on an identity after a refresh attempt.

    Sets ``last_token_refresh_outcome`` and ``token_health_state``. Callers
    flush/commit the session.
    """
    identity.last_token_refresh_outcome = refresh_outcome
    state = compute_identity_state(identity)
    identity.token_health_state = state
    return state


def persist_session_health_state(
    session: McpSession,
    *,
    refresh_outcome: TokenRefreshOutcome,
) -> TokenHealthState:
    """Recompute and persist health fields on an MCP session after a refresh attempt."""
    session.last_token_refresh_at = _now_utc()
    session.last_token_refresh_outcome = refresh_outcome
    state = compute_session_state(session)
    session.token_health_state = state
    return state


def log_session_refresh(
    db: AsyncSession,
    *,
    mcp_session_id: uuid.UUID,
    outcome: TokenRefreshOutcome,
    error_message: str | None = None,
) -> None:
    """Write a ``TokenRefreshLog`` audit row for an MCP session refresh.

    The row carries ``mcp_session_id`` set and ``agent_identity_id`` NULL —
    the exactly-one-target check constraint
    ``ck_token_refresh_logs_has_target`` requires exactly one target per row.
    """
    entry = TokenRefreshLog(
        agent_identity_id=None,
        mcp_session_id=mcp_session_id,
        attempted_at=_now_utc(),
        outcome=outcome,
        error_message=error_message,
        retry_attempt=1,
    )
    db.add(entry)


# ── Preflight resolution ──────────────────────────────────────────────────────


class PreflightTarget(NamedTuple):
    """One token-bearing target resolved for a preflight check."""

    kind: TokenHealthTargetKind
    id: uuid.UUID
    name: str
    state: TokenHealthState


class TokenHealthService:
    """Tenant-scoped token health evaluation and persistence (CC-only)."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Reads ────────────────────────────────────────────────────────────────

    async def list_identity_states(self) -> list[PreflightTarget]:
        """All agent identities in scope with their computed health state."""
        result = await self._db.execute(select(AgentIdentity))
        return [
            PreflightTarget(
                kind=TokenHealthTargetKind.agent_identity,
                id=identity.id,
                name=identity.name,
                state=compute_identity_state(identity),
            )
            for identity in result.scalars().all()
        ]

    async def list_session_states(self) -> list[PreflightTarget]:
        """Active OAuth2 MCP sessions in scope with their computed health state."""
        result = await self._db.execute(
            select(McpSession).where(
                McpSession.is_active == True,  # noqa: E712
                McpSession.auth_type == McpSessionAuthType.oauth2,
            )
        )
        return [
            PreflightTarget(
                kind=TokenHealthTargetKind.mcp_session,
                id=session.id,
                name=session.name,
                state=compute_session_state(session),
            )
            for session in result.scalars().all()
        ]

    # ── Execution preflight ─────────────────────────────────────────────────

    async def _try_refresh_identity(
        self, target: "PreflightTarget"
    ) -> tuple["PreflightTarget", str | None]:
        """Attempt an inline OAuth refresh for an expired/expiring identity.

        Returns the (possibly re-classified) target and ``None`` on success,
        or a short failure reason on error — never raises. On success the
        denormalized ``token_health_state`` is already re-persisted by the
        refresh service (``persist_identity_health_state`` via
        ``store_refreshed_token``), and the audit rows written by this
        preflight run share the same session/commit.
        """
        from app.services.token_refresh import refresh_oauth_token

        try:
            await refresh_oauth_token(target.id, self._db)
        except Exception as exc:  # noqa: BLE001 — degrade to BLOCKED, never crash preflight
            reason = str(exc).strip()[:160] or exc.__class__.__name__
            logger.warning(
                "Preflight auto-refresh failed for agent_identity '%s' (%s): %s",
                target.name,
                target.id,
                reason,
            )
            return target, reason
        # Refresh succeeded — recompute the state from the updated row.
        identity = await self._db.get(AgentIdentity, target.id)
        if identity is None:
            return target, None
        new_state = compute_identity_state(identity)
        logger.info(
            "Preflight auto-refreshed agent_identity '%s' (%s): %s -> %s",
            target.name,
            target.id,
            target.state.value,
            new_state.value,
        )
        return target._replace(state=new_state), None

    async def resolve_execution_targets(
        self,
        agent_type_id: uuid.UUID,
        session_id: uuid.UUID | None = None,
    ) -> list[PreflightTarget]:
        """Resolve every token an execution will use — the agent type's identity,
        the role-bound MCP sessions, and all subagent identities already
        delegated within the execution tree (``AgentRunRelationship``)."""
        from app.db.models.agents import (
            AgentRoleMcpSession,
            AgentType,
        )

        targets: list[PreflightTarget] = []
        seen_ids: set[tuple[TokenHealthTargetKind, uuid.UUID]] = set()

        async def _add_identity(identity_id: uuid.UUID | None) -> None:
            if identity_id is None:
                return
            key = (TokenHealthTargetKind.agent_identity, identity_id)
            if key in seen_ids:
                return
            identity = await self._db.get(AgentIdentity, identity_id)
            if identity is None:
                return
            seen_ids.add(key)
            targets.append(
                PreflightTarget(
                    kind=TokenHealthTargetKind.agent_identity,
                    id=identity.id,
                    name=identity.name,
                    state=compute_identity_state(identity),
                )
            )

        async def _add_role_sessions(role_id: uuid.UUID | None) -> None:
            if role_id is None:
                return
            result = await self._db.execute(
                select(McpSession)
                .join(AgentRoleMcpSession, AgentRoleMcpSession.mcp_session_id == McpSession.id)
                .where(AgentRoleMcpSession.role_id == role_id)
            )
            for session in result.scalars().all():
                key = (TokenHealthTargetKind.mcp_session, session.id)
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                targets.append(
                    PreflightTarget(
                        kind=TokenHealthTargetKind.mcp_session,
                        id=session.id,
                        name=session.name,
                        state=compute_session_state(session),
                    )
                )

        async def _add_agent_type(type_id: uuid.UUID) -> None:
            agent_type = await self._db.get(AgentType, type_id)
            if agent_type is None:
                return
            await _add_identity(agent_type.identity_id)
            await _add_role_sessions(agent_type.role_id)

        # The primary agent type.
        await _add_agent_type(agent_type_id)

        # Subagents: runtime delegation edges for this execution tree.
        from app.db.models.agents import AgentJob
        from app.db.models.agent_run_relationship import AgentRunRelationship

        child_type_ids: list[uuid.UUID] = []
        if session_id is not None:
            result = await self._db.execute(
                select(AgentRunRelationship.child_agent_job_id).where(
                    AgentRunRelationship.parent_agent_job_id == session_id
                )
            )
            child_job_ids = [row[0] for row in result.all()]
        else:
            child_job_ids = []
        for job_id in child_job_ids:
            job = await self._db.get(AgentJob, job_id)
            if job is not None and job.agent_type_id is not None:
                child_type_ids.append(job.agent_type_id)
        for child_type_id in child_type_ids:
            await _add_agent_type(child_type_id)

        return targets

    async def run_preflight(
        self,
        agent_type_id: uuid.UUID,
        session_id: uuid.UUID | None = None,
    ) -> "PreflightResult":
        """Evaluate token health for the whole execution and persist audit rows.

        Returns PROCEED / PROCEED+WARN / BLOCKED with per-target messages.
        Every evaluation writes an immutable ``TokenHealthCheck`` row
        (including blocked runs)."""
        from app.schemas.token_health import (
            PreflightTargetReport,
            PreflightResult,
            PreflightVerdict,
        )

        # Tenant stamp for the audit rows — from the agent type's own tenant
        # (mandatory in production), falling back to the root tenant.
        from app.db.models.agents import AgentType as _AgentType

        agent_type_row = await self._db.get(_AgentType, agent_type_id)
        tenant_id: uuid.UUID | None = (
            agent_type_row.tenant_id if agent_type_row is not None else None
        )
        if tenant_id is None:
            from app.services.tenancy.root_tenant import get_root_tenant_id

            tenant_id = await get_root_tenant_id(self._db)

        targets = await self.resolve_execution_targets(agent_type_id, session_id)

        reports: list[PreflightTargetReport] = []
        warnings: list[PreflightTargetReport] = []
        blocked: list[PreflightTargetReport] = []

        for target in targets:
            # Auto-refresh (delegation reliability): an expired/expiring
            # agent identity token is refreshed inline before blocking, so
            # executions are not stalled by a stale access token. MCP
            # sessions are left alone — session refresh is a separate
            # OAuth re-auth flow. Any refresh error degrades to the
            # pre-existing BLOCKED behaviour with the REAL reason surfaced.
            refresh_error: str | None = None
            refresh_attempted = False
            if (
                target.kind == TokenHealthTargetKind.agent_identity
                and target.state in (TokenHealthState.expired, TokenHealthState.expiring)
            ):
                refresh_attempted = True
                target, refresh_error = await self._try_refresh_identity(target)

            if target.state == TokenHealthState.expired:
                outcome = TokenCheckOutcome.blocked
                if refresh_error is not None:
                    message = (
                        f"{target.kind.value} '{target.name}' token auto-refresh failed "
                        f"({refresh_error}) — refresh token likely expired/revoked; "
                        f"re-authenticate identity '{target.name}' before executing this agent"
                    )
                else:
                    message = (
                        f"{target.kind.value} '{target.name}' token has expired — "
                        "refresh it (identity) or re-authenticate (MCP session) "
                        "before executing this agent"
                    )
                blocked.append(
                    PreflightTargetReport(
                        target_kind=target.kind,
                        target_id=target.id,
                        target_name=target.name,
                        health_state=target.state,
                        message=message,
                    )
                )
            elif target.state == TokenHealthState.expiring:
                outcome = TokenCheckOutcome.passed
                message = (
                    f"{target.kind.value} '{target.name}' token expires within "
                    f"{int(TOKEN_EXPIRING_WINDOW.total_seconds() // 86400)} days — "
                    "refresh soon to avoid execution blocks"
                )
                if refresh_error is not None:
                    # Token is still valid — a failed refresh attempt must
                    # NOT block execution; surface it as a warning instead.
                    message += (
                        f" (auto-refresh attempt failed: {refresh_error})"
                    )
                warnings.append(
                    PreflightTargetReport(
                        target_kind=target.kind,
                        target_id=target.id,
                        target_name=target.name,
                        health_state=target.state,
                        message=message,
                    )
                )
            else:
                outcome = TokenCheckOutcome.passed
                if refresh_attempted and refresh_error is None and target.kind == TokenHealthTargetKind.agent_identity:
                    # Reached healthy after a successful inline auto-refresh
                    # (the target only entered this branch expired/expiring).
                    message = (
                        f"{target.kind.value} '{target.name}' token was expired/expiring "
                        "and was auto-refreshed before execution"
                    )
                else:
                    message = f"{target.kind.value} '{target.name}' token is {target.state.value}"
            reports.append(
                PreflightTargetReport(
                    target_kind=target.kind,
                    target_id=target.id,
                    target_name=target.name,
                    health_state=target.state,
                    message=message,
                )
            )
            # Immutable audit row per evaluated target (append-only).
            self._db.add(
                TokenHealthCheck(
                    tenant_id=tenant_id,
                    agent_type_id=agent_type_id,
                    session_id=session_id,
                    target_kind=target.kind,
                    target_id=target.id,
                    health_state=target.state,
                    check_outcome=outcome,
                    message=message,
                )
            )
        if targets:
            await self._db.flush()

        if blocked:
            verdict = PreflightVerdict.blocked
        elif warnings:
            verdict = PreflightVerdict.proceed_with_warnings
        else:
            verdict = PreflightVerdict.proceed

        return PreflightResult(
            verdict=verdict,
            agent_type_id=agent_type_id,
            session_id=session_id,
            targets=reports,
            warnings=[w.message for w in warnings],
            blocked=[b.message for b in blocked],
        )
