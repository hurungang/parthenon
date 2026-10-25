"""Communication Hub — CC verification script-execution forwarding.

Control Center's ``execute_script`` system tool (the Optimize-&-Verify
verification primitive) must run the sandbox in Agent Runtime — scripts
execute ONLY there (top-priority rule). Historically CC posted to
``/internal/tools/call`` with the virtual name ``script____inline``, but that
path is reserved for AGENT-RUNTIME certificates (ControlPlaneMiddleware
accepts only ``service:agent-runtime`` on ``/internal/tools/``) — CC's service
certificate is rejected there by design, so the CC verification hop was
architecturally broken.

This endpoint is the CC-cert-authorized hop into the SAME AR forwarding
mechanism the ``script____`` tools use:

1. CC → CH ``POST /internal/script-tools/forward`` — ControlPlaneMiddleware
   validates CC's service certificate (``service:control-center``; kept fresh
   by CC's own startup/daily self-renewal).
2. CH → AR ``POST /internal/script-tools/execute`` — CH presents ITS OWN
   service certificate (shared ``_post_ar_script_execute`` helper, identical
   to the ``script____<name>`` route).
3. AR executes the inline ``python_source`` in the real sandbox with the
   SESSION-BOUND tool client (AR cert + agent identity, SEC1 parity).

The AR contract (``{"result": ..., "error": str | None}``) is passed through
verbatim: a sandbox compile/violation failure surfaces as ``error``, never a
5xx, so CC can relay the structured error to the LLM.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.communication_hub.api.internal.tool_routing import (
    _post_ar_script_execute,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal/script-tools", tags=["Internal - Script Forwarding"]
)

#: Virtual tool name for inline (unsaved) verification source. AR's
#: ``script_tools.py`` skips the registry lookup when ``python_source`` is
#: present and executes the source directly.
INLINE_TOOL_NAME = "script____inline"


class ScriptForwardRequest(BaseModel):
    """CC → CH inline script execution request.

    ``session_id`` + ``agent_type_id`` carry the session's agent identity so
    AR executes the sandbox with the same identity as the agent's own tool
    calls (SEC1). ``tool_args`` normally holds ``{"input": {...}}`` — the
    script's ``context``.
    """

    session_id: str
    agent_type_id: str = ""
    tool_args: dict[str, Any] = Field(default_factory=dict)
    python_source: str | None = None
    conv_session_id: str | None = None


@router.post("/forward")
async def forward_script_execution(
    body: ScriptForwardRequest,
    request: Request,
) -> dict[str, Any]:
    """Forward CC verification source to AR's sandbox (CH-cert hop)."""
    payload: dict[str, Any] = {
        "tool_name": INLINE_TOOL_NAME,
        "tool_args": body.tool_args,
        "session_id": body.session_id,
        "agent_type_id": body.agent_type_id,
        "provenance": "script",
    }
    if body.python_source:
        payload["python_source"] = body.python_source
    if body.conv_session_id:
        payload["conv_session_id"] = body.conv_session_id

    from app.communication_hub.api.internal.tool_routing import (
        _post_ar_script_execute,
    )

    logger.info(
        "Forwarding CC verification script to Agent Runtime (session=%s, "
        "agent_type=%s, inline=%s)",
        body.session_id[:8],
        body.agent_type_id[:8] if body.agent_type_id else "",
        bool(body.python_source),
    )
    try:
        return await _post_ar_script_execute(_ar_base(), payload, request)
    except HTTPException:
        raise


def _ar_base() -> str:
    from app.core.config import get_settings

    return get_settings().agent_runtime_url or "http://localhost:8001"
