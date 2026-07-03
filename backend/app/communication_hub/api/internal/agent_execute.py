"""Communication Hub — Agent Execution Trigger Endpoint.

Forwards execution requests from Control Center to Agent Runtime.

Route: POST /internal/agent/execute

This enables all agent communication to flow through Communication Hub,
supporting future agent-to-agent communication patterns.
"""
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


class AgentExecuteRequest(BaseModel):
    """Request to trigger agent execution."""
    
    session_id: uuid.UUID
    agent_type_id: uuid.UUID
    input_data: dict[str, Any] | None = None


class AgentExecuteResponse(BaseModel):
    """Response from agent execution trigger."""
    
    session_id: uuid.UUID
    status: str


@router.post("/execute", response_model=AgentExecuteResponse)
async def trigger_agent_execution(
    body: AgentExecuteRequest,
    request: Request,
) -> AgentExecuteResponse:
    """Forward execution trigger from Control Center to Agent Runtime.
    
    This endpoint centralizes all agent execution requests through Communication Hub,
    enabling future agent-to-agent communication and centralized routing.
    
    Flow:
    1. Control Center creates AgentJob (status=queued)
    2. Control Center → Communication Hub: POST /internal/agent/execute
    3. Communication Hub → Agent Runtime: POST /execute (with mTLS cert, with retry)
    4. Agent Runtime executes session immediately
    
    Args:
        body: Execution request with session_id, agent_type_id, input_data
        request: FastAPI request (for accessing certificate manager)
        
    Returns:
        Response confirming session was accepted
        
    Raises:
        HTTPException: 502 if Agent Runtime is unavailable after retries or rejects request
    """
    logger.info(
        "Agent execution trigger: session=%s agent_type=%s",
        body.session_id,
        body.agent_type_id,
    )
    
    # Get Agent Runtime URL
    ar_base = settings.agent_runtime_url or "http://localhost:8001"
    ar_endpoint = f"{ar_base}/execute"
    
    # Get Communication Hub certificate for authenticating to Agent Runtime.
    # If the certificate manager is absent or the cert was not bootstrapped on startup
    # (e.g. CC was unavailable when CH started), attempt an on-demand reload.
    cert_manager = getattr(request.app.state, "certificate_manager", None)
    if cert_manager is None or not cert_manager.is_loaded:
        logger.warning(
            "Certificate not ready for session=%s — attempting on-demand re-bootstrap",
            body.session_id,
        )
        try:
            from app.communication_hub.main import _load_certificate
            await _load_certificate()
            cert_manager = getattr(request.app.state, "certificate_manager", None)
            if cert_manager and cert_manager.is_loaded:
                # Update app state so future requests benefit too
                request.app.state.certificate_manager = cert_manager
                logger.info("On-demand cert re-bootstrap succeeded for session=%s", body.session_id)
            else:
                logger.warning("On-demand cert re-bootstrap did not produce a loaded cert")
        except Exception as exc:
            logger.warning("On-demand cert re-bootstrap failed: %s", exc)

    client_kwargs: dict = {
        "timeout": 30.0,
        "verify": get_ssl_context(),
    }

    def _build_headers() -> dict:
        """Build request headers with current cert (re-read on each retry for freshness)."""
        hdrs: dict = {}
        mgr = getattr(request.app.state, "certificate_manager", None)
        if mgr and mgr.cert_path and mgr.key_path:
            if ar_base.startswith("https://"):
                client_kwargs["cert"] = (str(mgr.cert_path), str(mgr.key_path))
            else:
                from pathlib import Path
                try:
                    cert_content = Path(mgr.cert_path).read_text()
                    hdrs["X-Client-Certificate"] = cert_content.replace("\n", "\\n")
                except OSError as e:
                    logger.warning("Could not read cert file for AR request: %s", e)
        else:
            logger.warning("No certificate available — Agent Runtime may reject request")
        return hdrs

    # Forward request to Agent Runtime with retry logic
    payload = {
        "session_id": str(body.session_id),
        "agent_type_id": str(body.agent_type_id),
        "input_data": body.input_data,
    }
    
    # Retry configuration: 3 attempts with exponential backoff (0s, 3s, 6s)
    max_retries = 3
    retry_delays = [0, 3, 6]  # seconds
    last_error = None
    
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                delay = retry_delays[attempt]
                logger.info(
                    "Retrying Agent Runtime trigger (attempt %d/%d) after %ds delay: session=%s",
                    attempt + 1,
                    max_retries,
                    delay,
                    body.session_id,
                )
                await asyncio.sleep(delay)
            
            headers = _build_headers()
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.post(
                    ar_endpoint,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                result = response.json()
                
                logger.info(
                    "Agent execution trigger forwarded successfully: session=%s status=%s (attempt %d/%d)",
                    body.session_id,
                    result.get("status"),
                    attempt + 1,
                    max_retries,
                )
                
                return AgentExecuteResponse(
                    session_id=uuid.UUID(result["session_id"]),
                    status=result["status"],
                )
        
        except httpx.HTTPStatusError as exc:
            last_error = exc
            status = exc.response.status_code
            # 401 means AR rejected our cert — try to re-bootstrap cert and retry
            if status == 401:
                logger.warning(
                    "Agent Runtime rejected cert (401) on attempt %d/%d — attempting cert re-bootstrap: session=%s",
                    attempt + 1,
                    max_retries,
                    body.session_id,
                )
                try:
                    from app.communication_hub.main import _load_certificate
                    await _load_certificate()
                    request.app.state.certificate_manager = getattr(request.app.state, "certificate_manager", None)
                    logger.info("Cert re-bootstrap completed after 401; will retry AR call")
                except Exception as bootstrap_exc:
                    logger.warning("Cert re-bootstrap after 401 failed: %s", bootstrap_exc)
                continue  # retry with refreshed cert

            # Other 4xx errors are not retriable
            if status < 500:
                error_msg = f"Agent Runtime rejected execution: HTTP {status}"
                logger.error("%s - %s", error_msg, exc.response.text[:200])
                raise HTTPException(status_code=502, detail=error_msg)
            # 5xx errors — continue retry loop
            logger.warning(
                "Agent Runtime returned HTTP %d (attempt %d/%d): %s",
                status,
                attempt + 1,
                max_retries,
                exc.response.text[:200],
            )

        except httpx.TimeoutException as exc:
            last_error = exc
            logger.warning(
                "Agent Runtime timeout (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                exc,
            )

        except httpx.ConnectError as exc:
            last_error = exc
            logger.warning(
                "Agent Runtime connection failed (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                exc,
            )

        except Exception as exc:
            last_error = exc
            logger.exception(
                "Agent execution trigger failed unexpectedly (attempt %d/%d)",
                attempt + 1,
                max_retries,
            )

    # All retries exhausted
    if isinstance(last_error, (httpx.ConnectError, httpx.TimeoutException)):
        error_msg = "Agent Runtime unavailable after retries - request timed out or connection failed"
        logger.error("%s: session=%s", error_msg, body.session_id)
        raise HTTPException(status_code=503, detail=error_msg)
    else:
        error_msg = f"Failed to trigger agent execution after {max_retries} retries: {last_error}"
        logger.error("%s: session=%s", error_msg, body.session_id)
        raise HTTPException(status_code=502, detail=error_msg)
