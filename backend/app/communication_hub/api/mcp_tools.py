"""MCP-facing tools for external agents authenticated via API key.

These tools are exposed on the Communication Hub's MCP endpoint for external
third-party agents (Claude Code, Cursor, custom agents).  Authentication is
handled by the ApiKeyAuthMiddleware which validates API keys via Control Center
and enriches ``request.state`` with resolved identity tokens and permissions.

All tool responses are formatted as MCP-compliant JSON structures.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.core.ssl_context import get_ssl_context

logger = logging.getLogger(__name__)

mcp_router = APIRouter(prefix="/mcp", tags=["MCP - External Agent Tools"])


def _get_control_center_url() -> str:
    return os.environ.get("CONTROL_CENTER_URL", "").rstrip("/")


def _allow_insecure_internal_fallback() -> bool:
    environment = os.environ.get("ENVIRONMENT", "").strip().lower()
    opt_in = os.environ.get("ALLOW_INSECURE_INTERNAL_CALL_FALLBACK", "").strip().lower()
    return environment == "development" and opt_in in {"1", "true", "yes", "on"}


def _build_control_center_auth(
    request: Request,
    cc_base: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build transport kwargs and headers for authenticated CH -> CC calls."""
    from pathlib import Path

    cert_manager = getattr(request.app.state, "certificate_manager", None)
    client_kwargs: dict[str, Any] = {
        "timeout": 30.0,
        "verify": get_ssl_context(),
    }
    headers: dict[str, str] = {}

    if cert_manager and cert_manager.cert_path and cert_manager.key_path:
        if cc_base.startswith("https://"):
            client_kwargs["cert"] = (str(cert_manager.cert_path), str(cert_manager.key_path))
        else:
            cert_content = Path(cert_manager.cert_path).read_text()
            headers["X-Client-Certificate"] = cert_content.replace("\n", "\\n")
        return client_kwargs, headers

    if _allow_insecure_internal_fallback():
        logger.warning("MCP tools using insecure internal fallback (development only)")
        return client_kwargs, headers

    raise HTTPException(
        status_code=503,
        detail="Communication Hub service certificate is required for internal calls",
    )


class LoadSkillsResponse(BaseModel):
    """MCP-compliant response for load_skills tool."""

    skills: list[dict[str, Any]] = Field(default_factory=list)
    since_provided: bool = False


@mcp_router.get("/tools/load_skills", response_model=LoadSkillsResponse)
@mcp_router.post("/tools/load_skills", response_model=LoadSkillsResponse)
async def load_skills(
    request: Request,
    since: str | None = Query(None, description="ISO 8601 timestamp for incremental sync"),
) -> LoadSkillsResponse:
    """Discover all accessible skills with full tool definitions and ``updated_at`` timestamps.

    Called by external AI agents via MCP protocol.  Returns all skills (including
    SOPs) that the authenticated agent is permitted to access.

    Supports an optional ``since`` query parameter for incremental sync — only
    skills with ``updated_at > since`` are returned.  Call with a timestamp from
    the most recent previous response to avoid re-downloading unchanged skills.

    Authentication: requires a valid API key (handled by ApiKeyAuthMiddleware).
    Identity tokens and permissions are stored on ``request.state`` — never
    exposed to external agents.
    """
    # Verify API key auth was performed
    if getattr(request.state, "auth_method", None) != "api_key":
        raise HTTPException(
            status_code=401,
            detail="API key authentication required for load_skills. "
                   "Use Authorization: Bearer <api_key> header or ?apiKey=<api_key> query parameter.",
        )

    agent_role_id = getattr(request.state, "api_key_agent_role_id", None)
    if not agent_role_id:
        raise HTTPException(
            status_code=500,
            detail="Internal error: no agent role resolved from API key",
        )

    # Parse since parameter
    since_dt: str | None = None
    if since:
        try:
            # Validate ISO 8601 format
            datetime.fromisoformat(since.replace("Z", "+00:00"))
            since_dt = since
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid 'since' timestamp format: {since}. Use ISO 8601 format.",
            )

    # Call Control Center to resolve skills
    cc_base = _get_control_center_url()
    if not cc_base:
        raise HTTPException(status_code=503, detail="Control Center URL not configured")

    try:
        cc_client_kwargs, headers = _build_control_center_auth(request, cc_base)
        payload: dict[str, Any] = {
            "agent_role_id": str(agent_role_id),
        }
        if since_dt:
            payload["since"] = since_dt

        async with httpx.AsyncClient(**cc_client_kwargs) as client:
            response = await client.post(
                f"{cc_base}/api/v1/internal/skills/resolve",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()

        skills_data = result.get("skills", [])
        logger.info(
            "load_skills: resolved %d skills for role %s (since=%s)",
            len(skills_data),
            agent_role_id,
            since_dt,
        )

        return LoadSkillsResponse(
            skills=skills_data,
            since_provided=since_dt is not None,
        )

    except httpx.HTTPStatusError as exc:
        logger.error(
            "load_skills: CC call failed HTTP %d: %s",
            exc.response.status_code,
            exc.response.text[:200],
        )
        raise HTTPException(
            status_code=502,
            detail=f"Skill resolution failed: Control Center returned {exc.response.status_code}",
        )
    except Exception as exc:
        logger.exception("load_skills: CC call failed")
        raise HTTPException(
            status_code=502,
            detail=f"Skill resolution failed: {exc}",
        )
