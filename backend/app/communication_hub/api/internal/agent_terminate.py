"""Communication Hub — Agent Session Termination Endpoint.

Forwards session termination requests from Control Center to Agent Runtime.

Route: POST /internal/agent/terminate/{session_id}

This mirrors the ``/internal/agent/execute`` flow so that all cross-service
control plane traffic to Agent Runtime passes through Communication Hub.
Routing the terminate call through CH (rather than CC → AR direct) is required
because Agent Runtime's ``ControlCenterCertificateMiddleware`` only accepts
``CN=service:communication-hub`` certificates on its ``/terminate/{session_id}``
endpoint — Control Center's own ``service:control-center`` cert is rejected.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.ssl_context import get_ssl_context

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/internal/agent", tags=["Internal - Agent Control"])


class AgentTerminateRequest(BaseModel):
    """Request to cancel an in-flight agent session."""

    reason: str | None = None


class AgentTerminateResponse(BaseModel):
    """Response from session termination.

    ``already_terminal`` is ``True`` when the session was not in
    ``running`` state and so was skipped (the agent had already
    finished naturally and there is nothing to cancel).
    """

    session_id: uuid.UUID
    cancelled: bool
    already_terminal: bool = False
    reason: str | None = None


@router.post("/terminate/{session_id}", response_model=AgentTerminateResponse)
async def forward_terminate_session(
    session_id: uuid.UUID,
    body: AgentTerminateRequest,
    request: Request,
) -> AgentTerminateResponse:
    """Forward a termination request from Control Center to Agent Runtime.

    Flow:
        1. Control Center operator hits "Terminate" in the UI.
        2. Control Center's ``TerminationOrchestrator`` updates the DB row
           to ``failed`` with ``termination_category=user_requested`` and
           then calls Communication Hub here.
        3. Communication Hub forwards to Agent Runtime's
           ``/terminate/{session_id}`` with mTLS (CH cert).
        4. Agent Runtime cancels the in-memory ``asyncio.Task`` and the
           agent's eventual ``mark_session_completed`` is a no-op
           (terminal-state guards in ``update_session_status``).

    Returns 200 on success (with ``cancelled=True``), 200 with
    ``cancelled=False`` when AR has no in-flight task for the session,
    502 when AR rejects the call after retries.
    """
    logger.info(
        "Agent termination request forwarded: session=%s reason=%s",
        session_id,
        body.reason,
    )

    ar_base = settings.agent_runtime_url or "http://localhost:8001"
    ar_endpoint = f"{ar_base}/terminate/{session_id}"

    cert_manager = getattr(request.app.state, "certificate_manager", None)
    client_kwargs: dict[str, Any] = {
        "timeout": 30.0,
        "verify": get_ssl_context(),
    }

    headers: dict[str, str] = {}
    if cert_manager and cert_manager.cert_path and cert_manager.key_path:
        if ar_base.startswith("https://"):
            client_kwargs["cert"] = (str(cert_manager.cert_path), str(cert_manager.key_path))
            logger.debug("Using mTLS certificate for Agent Runtime termination")
        else:
            from pathlib import Path
            cert_content = Path(cert_manager.cert_path).read_text()
            cert_header_value = cert_content.replace("\n", "\\n")
            headers["X-Client-Certificate"] = cert_header_value
            logger.debug("Using X-Client-Certificate header for Agent Runtime termination")
    else:
        logger.warning(
            "No certificate manager available — Agent Runtime call may fail authentication"
        )

    payload: dict[str, Any] = {}
    if body.reason:
        payload["reason"] = body.reason

    max_retries = 3
    retry_delays = [0, 2, 4]
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                delay = retry_delays[attempt]
                logger.info(
                    "Retrying Agent Runtime termination (attempt %d/%d) after %ds delay: session=%s",
                    attempt + 1,
                    max_retries,
                    delay,
                    session_id,
                )
                await asyncio.sleep(delay)

            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.post(
                    ar_endpoint,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                result = response.json()

                logger.info(
                    "Agent termination forwarded successfully: session=%s cancelled=%s (attempt %d/%d)",
                    session_id,
                    result.get("cancelled"),
                    attempt + 1,
                    max_retries,
                )

                return AgentTerminateResponse(
                    session_id=uuid.UUID(result["session_id"]),
                    cancelled=bool(result.get("cancelled", False)),
                    already_terminal=bool(result.get("already_terminal", False)),
                    reason=result.get("reason"),
                )

        except httpx.HTTPStatusError as exc:
            # 404 from AR means the session already completed — that
            # is a success for the operator's intent (the session is
            # no longer running).  4xx other than 404 is a real error.
            if exc.response.status_code == 404:
                logger.info(
                    "Agent Runtime has no in-flight task for session %s — operator intent satisfied",
                    session_id,
                )
                return AgentTerminateResponse(
                    session_id=session_id,
                    cancelled=False,
                    already_terminal=True,
                    reason="No in-flight task (session already completed)",
                )
            last_error = exc
            if exc.response.status_code < 500:
                error_msg = (
                    f"Agent Runtime rejected termination: HTTP {exc.response.status_code}"
                )
                logger.error("%s — %s", error_msg, exc.response.text[:200])
                raise HTTPException(status_code=502, detail=error_msg)
            logger.warning(
                "Agent Runtime returned HTTP %d (attempt %d/%d): %s",
                exc.response.status_code,
                attempt + 1,
                max_retries,
                exc.response.text[:200],
            )

        except httpx.TimeoutException as exc:
            last_error = exc
            logger.warning(
                "Agent Runtime termination timeout (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                exc,
            )

        except httpx.ConnectError as exc:
            last_error = exc
            logger.warning(
                "Agent Runtime termination connection failed (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                exc,
            )

        except Exception as exc:
            last_error = exc
            logger.exception(
                "Agent termination forward failed unexpectedly (attempt %d/%d)",
                attempt + 1,
                max_retries,
            )

    # All retries exhausted
    if isinstance(last_error, (httpx.ConnectError, httpx.TimeoutException)):
        error_msg = "Agent Runtime unavailable after retries — request timed out or connection failed"
        logger.error("%s: session=%s", error_msg, session_id)
        raise HTTPException(status_code=503, detail=error_msg)
    else:
        error_msg = f"Failed to forward agent termination after {max_retries} retries: {last_error}"
        logger.error("%s: session=%s", error_msg, session_id)
        raise HTTPException(status_code=502, detail=error_msg)
