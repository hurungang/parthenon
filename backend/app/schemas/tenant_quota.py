"""Structured quota contract schemas (Phase 10).

One payload shape shared by ALL three enforcement gates (users, agent
types, monthly executions); one HTTP mapping (403 Forbidden — deliberate
choice: quota refusal is a plan/entitlement limit, not rate-based
traffic throttling like 429, and it flows through the same 403 handling
as other forbidden responses).  The frontend renders this payload
as-is via the shared blocked-action alert (QuotaBlockedAlert).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

#: Stable error code carried by every quota refusal.
QUOTA_EXHAUSTED_CODE = "quota_exhausted"

QuotaTypeLiteral = Literal["users", "agent_types", "monthly_executions"]


class QuotaBlockedPayload(BaseModel):
    """Structured feedback for a blocked (over-quota) action.

    Round-trips cleanly to the frontend ``QuotaBlockedPayload`` interface
    in ``frontend/src/types/index.ts`` — the UI renders tier, limit,
    current usage and the upgrade path directly from these fields.
    """

    code: Literal["quota_exhausted"] = QUOTA_EXHAUSTED_CODE
    quota_type: QuotaTypeLiteral
    # The tenant's current tier ("free" when unlicensed)
    tier: str
    # The effective limit that was hit
    limit: int = Field(ge=0)
    # Current usage at the time of refusal
    used: int = Field(ge=0)
    # Human-facing upgrade path message (frontend shows its own i18n text
    # keyed off ``code``/``quota_type``; this field is the server default)
    upgrade_path: str = Field(
        default=(
            "Upgrade your plan (contact your platform administrator) to "
            "raise this limit"
        ),
    )


class TenantUsageRead(BaseModel):
    """Tier, effective limits and current usage for one tenant.

    Returned by ``GET /api/v1/tenant/usage`` (tenant-side) and embedded
    in the platform tenant list/detail responses (platform-side).
    """

    tier: str
    max_users: int
    max_agent_types: int
    monthly_agent_executions: int
    users: int
    agent_types: int
    executions_this_month: int
