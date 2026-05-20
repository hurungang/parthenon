"""Communication Hub — standalone FastAPI application entry point.

This service is responsible for:
- WebSocket connections from the Web UI (JWT-authenticated)
- Agent gateway lifecycle management (launch, status, close)
- Message dispatch from Control Center over mTLS
- Certificate-based authorization middleware for tool calls

Database access: NONE — all data is fetched from Control Center data APIs.
Entry point: uvicorn app.communication_hub.main:app
"""
from __future__ import annotations

import logging
import os
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

logger.info("Starting Communication Hub in %s mode", settings.environment)


def create_app() -> FastAPI:
    """Create and configure the Communication Hub FastAPI application."""
    setup_telemetry(settings.telemetry)

    app = FastAPI(
        title="Parthenon Communication Hub",
        version=settings.app_version,
        description="Message broker and agent gateway for Parthenon",
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url="/redoc" if settings.environment != "production" else None,
    )

    # CORS — mirrors Control Center settings; Web UI must be allowed for WebSocket handshake
    if settings.environment == "development":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost:5173",
                "http://localhost:4173",
                "http://localhost:3000",
            ],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Certificate authorization middleware for tool-call routes
    from app.communication_hub.middleware.authorization import CertificateAuthorizationMiddleware
    app.add_middleware(CertificateAuthorizationMiddleware)

    # Control plane middleware: validate Control Center service cert on /internal/* paths
    # (task 4.3 — while still accepting JWT-authenticated WebSocket connections)
    from app.communication_hub.middleware.control_plane import ControlPlaneMiddleware
    app.add_middleware(ControlPlaneMiddleware)

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str | None]:
        manager = getattr(app.state, "certificate_manager", None)
        cert_expiry = (
            manager.expires_at.isoformat() if manager and manager.expires_at else None
        )
        return {
            "status": "ok",
            "service": "communication-hub",
            "version": settings.app_version,
            "cert_expires_at": cert_expiry,
        }

    _register_routers(app)

    return app


def _register_routers(app: FastAPI) -> None:
    """Register Communication Hub API routers."""
    from app.api.gateway.lifecycle import GatewayRouter
    from app.api.ws.chat import ws_router
    from app.communication_hub.api.dispatch import dispatch_router  # Phase 5.2
    from app.communication_hub.api.internal.tool_routing import router as tool_routing_router
    from app.communication_hub.api.internal.agent_execute import router as agent_execute_router

    app.include_router(GatewayRouter)
    app.include_router(ws_router)
    app.include_router(dispatch_router)  # POST /internal/dispatch
    app.include_router(tool_routing_router)  # POST /internal/tools/call
    app.include_router(agent_execute_router)  # POST /internal/agent/execute


app = create_app()


@app.on_event("startup")
async def startup_event() -> None:
    """Run Communication Hub startup tasks."""
    await _load_certificate()
    await _start_certificate_renewal()
    await _verify_redis_connectivity()


async def _load_certificate() -> None:
    """Load or bootstrap the Communication Hub service certificate from Control Center.

    Phase 2 (task 2.3) wires this to the /internal/bootstrap endpoint.
    Logs a warning and continues without mTLS when running in dev/test without
    the required environment variables.
    """
    try:
        from app.communication_hub.certificate_manager import (
            CommHubCertificateManager,
            CertificateLoadError,
        )

        manager = CommHubCertificateManager()
        await manager.load_certificate()
        app.state.certificate_manager = manager
        logger.info("Communication Hub certificate loaded successfully")
    except Exception as exc:
        logger.warning(
            "Communication Hub certificate not loaded — running without mTLS "
            "(acceptable in dev/test; ensure COMM_HUB_CERT_PATH and SERVICE_BOOTSTRAP_KEY are set). Error: %s",
            exc
        )
        app.state.certificate_manager = None


async def _start_certificate_renewal() -> None:
    """Start the Communication Hub certificate renewal background task."""
    import asyncio

    manager = getattr(app.state, "certificate_manager", None)
    if manager is not None:
        asyncio.create_task(manager.run_renewal_task())
        logger.info("Communication Hub certificate renewal background task started")


async def _verify_redis_connectivity() -> None:
    """Verify Redis broker is reachable on startup."""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(redis_url, socket_connect_timeout=5)
        await client.ping()
        await client.aclose()
        logger.info("Redis connectivity verified at %s", redis_url)
    except Exception as exc:
        logger.warning(
            "Redis not reachable at %s: %s — message broker functionality will be degraded",
            redis_url,
            exc,
        )
