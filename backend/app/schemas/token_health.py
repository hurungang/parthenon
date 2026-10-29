"""Pydantic schemas for the Token Expiry Alerting surfaces (dashboard + preflight)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.db.models.token_health import (
    TokenCheckOutcome,
    TokenHealthState,
    TokenHealthTargetKind,
)

PreflightVerdictLiteral = Literal["proceed", "proceed_with_warnings", "blocked"]


class PreflightVerdict:
    """Verdict values for the execution preflight result (string enum source)."""

    proceed = "proceed"
    proceed_with_warnings = "proceed_with_warnings"
    blocked = "blocked"


# ── Dashboard token health ────────────────────────────────────────────────────


class TokenHealthItem(BaseModel):
    """One token-bearing entity with its computed health state (itemized details)."""

    id: uuid.UUID
    name: str
    health_state: TokenHealthState
    expires_at: datetime | None = None
    refresh_expires_at: datetime | None = None
    last_refresh_outcome: str | None = None
    last_refresh_at: datetime | None = None
    remediation_target: Literal["agent_identity", "mcp_session"]
    remediation_path: str = Field(
        description="Frontend route where refresh / re-auth can be performed"
    )


class TokenHealthCategorySummary(BaseModel):
    """Expired / expiring counts plus itemized details for one category."""

    expired_count: int = 0
    expiring_count: int = 0
    healthy_count: int = 0
    unknown_count: int = 0
    items: list[TokenHealthItem] = Field(default_factory=list)


class TokenHealthSummary(BaseModel):
    """Dashboard token-health payload: per-category summaries + permission flags."""

    identities: TokenHealthCategorySummary
    mcp_sessions: TokenHealthCategorySummary
    permission_flags: TokenHealthPermissionFlags


class TokenHealthPermissionFlags(BaseModel):
    """True when the caller lacks permission for that category (placeholder shown)."""

    identities: bool = False
    mcp_sessions: bool = False


# ── Execution preflight (internal) ────────────────────────────────────────────


class PreflightRequest(BaseModel):
    """Request body for the internal execution preflight endpoint."""

    agent_type_id: uuid.UUID
    session_id: uuid.UUID | None = None


class PreflightTargetReport(BaseModel):
    """Per-target health evaluation inside a preflight result."""

    target_kind: TokenHealthTargetKind
    target_id: uuid.UUID
    target_name: str
    health_state: TokenHealthState
    message: str


class PreflightResult(BaseModel):
    """PROCEED / PROCEED+WARN / BLOCKED with per-target messages.

    Contains NO token material — only outcomes and human-readable messages.
    """

    verdict: PreflightVerdictLiteral
    agent_type_id: uuid.UUID
    session_id: uuid.UUID | None = None
    targets: list[PreflightTargetReport] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blocked: list[str] = Field(default_factory=list)

    @property
    def check_outcome(self) -> TokenCheckOutcome:
        return (
            TokenCheckOutcome.blocked
            if self.verdict == PreflightVerdict.blocked
            else TokenCheckOutcome.passed
        )
