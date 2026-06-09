"""Communication Hub — Agent Session Resume Endpoint.

Forwards session resume requests from Control Center to Agent Runtime after
human intervention.

Route: POST /internal/agent/resume/{session_id}

This mirrors the ``/internal/agent/terminate/{session_id}`` flow so that all
cross-service control plane traffic to Agent Runtime passes through
Communication Hub.  Routing the resume call through CH (rather than CC → AR
direct) is required because Agent Runtime's
``ControlCenterCertificateMiddleware`` only accepts
``CN=service:communication-hub`` certificates — Control Center's own
``service:control-center`` cert is rejected.
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


class AgentResumeRequest(BaseModel):
    """Request to resume an agent session after human intervention."""

    response_value: dict | None = None


class AgentResumeResponse(BaseModel):
    """Response from session resume."""

    session_id: uuid.UUID
    status: str


@router.post("/resume/{session_id}", response_model=AgentResumeResponse)
async def forward_resume_session(
    session_id: uuid.UUID,
    body: AgentResumeRequest,
    request: Request,
) -> AgentResumeResponse:
    """Forward a resume request from Control Center to Agent Runtime.

    Flow:
        1. Operator responds to an intervene request in the UI.
        2. Control Center commits the response and calls Communication Hub here.
        3. Communication Hub forwards to Agent Runtime's
           ``POST /internal/resume`` with mTLS (CH cert).
        4. Agent Runtime marks the session as running and starts a new
           execution task with the human's response value injected.

    Returns 200 on success (with ``status="resumed"``), 502/503 on failure.
    """
    logger.info(
        "Agent resume request forwarded: session=%s",
        session_id,
    )

    ar_base = settings.agent_runtime_url or "http://localhost:8001"
    ar_endpoint = f"{ar_base}/internal/resume"

    cert_manager = getattr(request.app.state, "certificate_manager", None)
    client_kwargs: dict[str, Any] = {
        "timeout": 30.0,
        "verify": get_ssl_context(),
    }

    headers: dict[str, str] = {}
    if cert_manager and cert_manager.cert_path and cert_manager.key_path:
        if ar_base.startswith("https://"):
            client_kwargs["cert"] = (str(cert_manager.cert_path), str(cert_manager.key_path))
            logger.debug("Using mTLS certificate for Agent Runtime resume")
        else:
            from pathlib import Path
            cert_content = Path(cert_manager.cert_path).read_text()
            cert_header_value = cert_content.replace("\n", "\\n")
            headers["X-Client-Certificate"] = cert_header_value
            logger.debug("Using X-Client-Certificate header for Agent Runtime resume")
    else:
        logger.warning(
            "No certificate manager available — Agent Runtime call may fail authentication"
        )

    payload: dict[str, Any] = {
        "session_id": str(session_id),
    }
    if body.response_value:
        payload["response_value"] = body.response_value

    max_retries = 3
    retry_delays = [0, 2, 4]
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                delay = retry_delays[attempt]
                logger.info(
                    "Retrying Agent Runtime resume (attempt %d/%d) after %ds delay: session=%s",
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
                    "Agent resume forwarded successfully: session=%s status=%s (attempt %d/%d)",
                    session_id,
                    result.get("status"),
                    attempt + 1,
                    max_retries,
                )

                return AgentResumeResponse(
                    session_id=uuid.UUID(result["session_id"]),
                    status=str(result.get("status", "resumed")),
                )

        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response.status_code < 500:
                error_msg = (
                    f"Agent Runtime rejected resume: HTTP {exc.response.status_code}"
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
                "Agent Runtime resume timeout (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                exc,
            )

        except httpx.ConnectError as exc:
            last_error = exc
            logger.warning(
                "Agent Runtime resume connection failed (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                exc,
            )

        except Exception as exc:
            last_error = exc
            logger.exception(
                "Agent resume forward failed unexpectedly (attempt %d/%d)",
                attempt + 1,
                max_retries,
            )

    # All retries exhausted
    if isinstance(last_error, (httpx.ConnectError, httpx.TimeoutException)):
        error_msg = "Agent Runtime unavailable after retries — request timed out or connection failed"
        logger.error("%s: session=%s", error_msg, session_id)
        raise HTTPException(status_code=503, detail=error_msg)
    else:
        error_msg = f"Failed to forward agent resume after {max_retries} retries: {last_error}"
        logger.error("%s: session=%s", error_msg, session_id)
        raise HTTPException(status_code=502, detail=error_msg)
