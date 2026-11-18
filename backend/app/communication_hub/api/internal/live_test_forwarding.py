"""Communication Hub — approved live-test forwarding (CC → CH → AR).

Route: ``POST /internal/live-test/run``

Control Center's ledger is the ONLY originator of a live test. After it has
consumed the operator's single-use approval it forwards the approved **script**
(the saved version's source) here; this endpoint forwards it **verbatim** to
Agent Runtime's ``POST /internal/live-test/run`` using the Communication Hub's
own service certificate (the same CH → AR identity used by the script-tool hop).

A live test runs the script end-to-end — the script's own ``tools.call(...)``
lines are the only egress; there is no per-operation list to execute.

Transport only, by design:

* no database access, no ledger state, no authorization of its own beyond the
  existing control-plane certificate checks;
* no identity material is added — the per-call agent identity is injected by
  CH's normal tool route inside Agent Runtime's run, not by this forward;
* the body is passed through unchanged (the script is already the approved
  unit), and AR's structured result is returned as-is.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.internal_http import internal_httpx_client
from app.core.ssl_context import get_ssl_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/live-test", tags=["Internal - Live Test"])

#: Agent Runtime route for an approved live-test run.
AR_LIVE_TEST_PATH = "/internal/live-test/run"


class LiveTestForwardRequest(BaseModel):
    """CC → CH live-test run (the approved script the operator consented to)."""

    live_test_request_id: str
    conversation_session_id: str
    target_agent_type_id: str
    script_version_id: str | None = None
    script_name: str | None = None
    script_version_label: str | None = None
    python_source: str = ""
    #: The reference execution's input (state context only, never credentials).
    input_context: dict[str, Any] = Field(default_factory=dict)


def _ar_base() -> str:
    return get_settings().agent_runtime_url or "http://localhost:8001"


def _build_ar_transport(
    ar_base: str, request: Request
) -> tuple[dict[str, Any], dict[str, str]]:
    """Transport kwargs + headers for the CH → AR live-test hop.

    CH presents ITS OWN service certificate (mTLS in production, the
    ``X-Client-Certificate`` header over development HTTP) — exactly like the
    script-tool forwarding hop. Raises HTTP 503 when CH has no certificate.
    """
    from pathlib import Path

    try:
        timeout = float(
            max(30, int(getattr(get_settings(), "optimizer_live_test_run_timeout_seconds", 120)))
        )
    except Exception:  # noqa: BLE001
        timeout = 120.0

    cert_manager = getattr(request.app.state, "certificate_manager", None)
    headers: dict[str, str] = {}
    client_kwargs: dict[str, Any] = {"timeout": timeout, "verify": get_ssl_context()}
    if cert_manager and cert_manager.cert_path and cert_manager.key_path:
        if ar_base.startswith("https://"):
            client_kwargs["cert"] = (
                str(cert_manager.cert_path),
                str(cert_manager.key_path),
            )
        else:
            headers["X-Client-Certificate"] = (
                Path(cert_manager.cert_path).read_text().replace("\n", "\\n")
            )
        return client_kwargs, headers
    raise HTTPException(
        status_code=503,
        detail="Communication Hub service certificate is required to run a live test",
    )


@router.post("/run")
async def forward_live_test(
    body: LiveTestForwardRequest,
    request: Request,
) -> dict[str, Any]:
    """Forward an approved live-test run to Agent Runtime (CH-cert hop)."""
    ar_base = _ar_base()
    endpoint = f"{ar_base}{AR_LIVE_TEST_PATH}"
    payload = body.model_dump()
    client_kwargs, headers = _build_ar_transport(ar_base, request)

    logger.info(
        "Forwarding approved live test %s to Agent Runtime (conversation=%s, "
        "subject=%s, script_version=%s, source_chars=%d)",
        body.live_test_request_id,
        body.conversation_session_id,
        body.target_agent_type_id,
        body.script_version_id,
        len(body.python_source or ""),
    )
    try:
        async with internal_httpx_client(**client_kwargs) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        error_msg = (
            f"Agent Runtime live test failed: HTTP {exc.response.status_code} - "
            f"{exc.response.text[:200]}"
        )
        logger.error("%s", error_msg)
        if 400 <= exc.response.status_code < 500:
            # AR rejected the run (e.g. capability check failed): pass the
            # structured failure back so the ledger records it.
            return {
                "status": "failed",
                "executed_operations": [],
                "error": error_msg,
            }
        raise HTTPException(status_code=502, detail=error_msg) from exc
    except HTTPException:
        raise
    except Exception as exc:
        error_msg = f"Agent Runtime live test call error: {exc}"
        logger.exception("Live-test forwarding failed for %s", body.live_test_request_id)
        raise HTTPException(status_code=502, detail=error_msg) from exc


__all__ = ["router", "LiveTestForwardRequest"]
