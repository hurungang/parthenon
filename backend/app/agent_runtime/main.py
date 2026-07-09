"""Agent Runtime — standalone FastAPI application entry point.

This service is responsible for:
- Receiving execution/delegation triggers from Communication Hub over mTLS
- Managing the agent-instance X.509 certificate lifecycle
- Immediately executing sessions trigger-based (no polling)
- Posting results back to Control Center

Database access: NONE — all data is fetched from Control Center data APIs.
Entry point: uvicorn app.agent_runtime.main:app
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env", override=False)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.telemetry import setup_telemetry

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)
settings = get_settings()

logger.info("Starting Agent Runtime in %s mode", settings.environment)


def _log_http_client_log_policy() -> None:
    httpx_level = logging.getLevelName(logging.getLogger("httpx").getEffectiveLevel())
    httpcore_level = logging.getLevelName(logging.getLogger("httpcore").getEffectiveLevel())
    logger.info(
        "HTTP client log policy applied via telemetry log_levels: httpx=%s, httpcore=%s",
        httpx_level,
        httpcore_level,
    )


def create_app() -> FastAPI:
    """Create and configure the Agent Runtime FastAPI application."""
    setup_telemetry(settings.telemetry)

    app = FastAPI(
        title="Parthenon Agent Runtime",
        version=settings.app_version,
        description="Stateless LangChain executor service for Parthenon agents",
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url="/redoc" if settings.environment != "production" else None,
    )

    # Inbound certificate validation: only Communication Hub may call Agent Runtime
    # (task 4.2 — rejects any request without a valid service:communication-hub cert)
    from app.agent_runtime.middleware import ControlCenterCertificateMiddleware
    app.add_middleware(ControlCenterCertificateMiddleware)

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str | None]:
        manager = getattr(app.state, "certificate_manager", None)
        cert_expiry = (
            manager.expires_at.isoformat() if manager and manager.expires_at else None
        )
        return {
            "status": "ok",
            "service": "agent-runtime",
            "version": settings.app_version,
            "cert_expires_at": cert_expiry,
        }

    # Phase 5.1 — execution trigger endpoint (Control Center → Agent Runtime)
    from app.agent_runtime.api.execute import execute_router
    app.include_router(execute_router)

    # Phase 3.11 — session cancellation endpoint (Control Center → Agent Runtime)
    from app.agent_runtime.api.terminate import terminate_router
    app.include_router(terminate_router)

    # WebSocket chat execution delegation (Communication Hub → Agent Runtime)
    from app.agent_runtime.api.conversation import conversation_router
    app.include_router(conversation_router)

    # Phase 3.5 — resume endpoint for human intervene (Control Center → Agent Runtime)
    from app.agent_runtime.api.intervene import resume_router
    app.include_router(resume_router)

    return app


app = create_app()


@app.on_event("startup")
async def startup_event() -> None:
    """Run Agent Runtime startup tasks."""
    _log_http_client_log_policy()
    settings.log_config_sources()
    await _validate_control_center_reachable()
    await _load_certificate()
    await _start_certificate_renewal()
    await _init_execution_engine()


async def _load_certificate() -> None:
    """Load or bootstrap the agent-instance certificate from Control Center.

    Phase 2 (task 2.2) wires this to the /internal/bootstrap endpoint.
    At Phase 1, the manager loads an existing cert from AGENT_CERT_PATH if present,
    and logs a warning when running without a certificate (dev/test mode).
    """
    try:
        from app.agent_runtime.certificate_manager import CertificateManager, CertificateLoadError
        manager = CertificateManager()
        await manager.load_certificate()
        # Store globally so routes and the data client can access it
        app.state.certificate_manager = manager
        logger.info("Agent Runtime certificate loaded successfully")
    except Exception as exc:
        logger.exception(
            "Agent Runtime certificate not loaded — running without mTLS "
            "(acceptable in dev/test; Phase 2 wires full bootstrap)"
        )
        app.state.certificate_manager = None


async def _start_certificate_renewal() -> None:
    """Start the background certificate renewal task."""
    import asyncio
    manager = getattr(app.state, "certificate_manager", None)
    if manager is not None:
        asyncio.create_task(manager.run_renewal_task())
        logger.info("Certificate renewal background task started")


async def _init_execution_engine() -> None:
    """Initialise the data client and concurrency semaphore for trigger-based execution.

    POST /execute transitions the session to running and launches the executor
    directly as a background task.  No polling or queue dispatcher is needed.
    """
    import asyncio
    try:
        from app.agent_runtime.data_client import ControlCenterDataClient

        cert_manager = getattr(app.state, "certificate_manager", None)
        data_client = ControlCenterDataClient(cert_manager=cert_manager)
        app.state.data_client = data_client

        # Bound concurrent sessions (same limit as the former SessionDispatcher)
        app.state.execution_semaphore = asyncio.Semaphore(4)

        # Phase 3.11: session_id -> asyncio.Task registry.  Populated
        # by /execute, consumed by /terminate/{session_id}.  Done
        # callbacks remove completed tasks so the dict stays bounded.
        app.state.session_tasks = {}

        logger.info("Agent Runtime execution engine initialised (trigger-based, no polling)")
    except Exception:
        logger.exception("Failed to initialise Agent Runtime execution engine")


async def _validate_control_center_reachable() -> None:
    """Validate Control Center is reachable before attempting certificate bootstrap.

    Sends a GET to ``{CONTROL_CENTER_URL}/health`` with 3 retries at
    5-second intervals.  On failure, logs a clear error and exits.
    """
    import asyncio
    import httpx

    cc_url = settings.control_center_url.rstrip("/")
    health_url = f"{cc_url}/health"

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(health_url)
            if resp.status_code == 200:
                logger.info(
                    "resolved Control Center from env:CONTROL_CENTER_URL: %s (reachable)",
                    cc_url,
                )
                return
            logger.warning(
                "Control Center health check returned HTTP %d (attempt %d/3)",
                resp.status_code, attempt + 1,
            )
        except Exception as exc:
            logger.warning(
                "Control Center not reachable at %s (attempt %d/3): %s",
                health_url, attempt + 1, exc,
            )

        if attempt < 2:
            await asyncio.sleep(5)

    logger.error(
        "Control Center is NOT reachable at %s after 3 attempts. "
        "The Agent Runtime requires Control Center for certificate bootstrap "
        "and data access. Check CONTROL_CENTER_URL and ensure Control Center is running.",
        health_url,
    )
    sys.exit(1)
