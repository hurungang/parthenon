"""Internal execution preflight endpoint — token-expiry-alerting.

Called by the Communication Hub Agent Gateway (via ``internal_httpx_client``,
signed ``X-Internal-Tenant-*`` headers) immediately before starting an agent
execution. Resolves EVERY token the run will use — the agent type's identity,
its role-bound MCP sessions, and all subagents already delegated within the
execution tree — and returns PROCEED / PROCEED+WARN / BLOCKED with
per-target, human-readable messages.

Fails closed: 401 without valid signed tenant headers (router-level
``require_internal_tenant_context`` dependency). No token material ever
appears in the response — only outcomes and messages.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.api.deps import require_internal_tenant_context
from app.db.session import DbSession
from app.schemas.token_health import PreflightRequest, PreflightResult
from app.services.token_health import TokenHealthService

logger = logging.getLogger(__name__)

InternalTokenHealthRouter = APIRouter(
    prefix="/internal/token-health",
    tags=["internal"],
    dependencies=[
        Depends(require_internal_tenant_context),
    ],
)


@InternalTokenHealthRouter.post("/preflight", response_model=PreflightResult)
async def execution_token_preflight(
    body: PreflightRequest,
    db: DbSession,
) -> PreflightResult:
    """Preflight every token an execution (including subagents) will use.

    Writes one immutable ``TokenHealthCheck`` audit row per evaluated target
    (including blocked runs) before returning.
    """
    service = TokenHealthService(db)
    result = await service.run_preflight(
        agent_type_id=body.agent_type_id,
        session_id=body.session_id,
    )
    await db.commit()  # Persist audit rows
    logger.info(
        "Execution preflight: agent_type=%s session=%s verdict=%s blocked=%d warned=%d",
        body.agent_type_id,
        body.session_id,
        result.verdict,
        len(result.blocked),
        len(result.warnings),
    )
    return result
