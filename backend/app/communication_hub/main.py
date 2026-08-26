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


def _log_http_client_log_policy() -> None:
    httpx_level = logging.getLevelName(logging.getLogger("httpx").getEffectiveLevel())
    httpcore_level = logging.getLevelName(logging.getLogger("httpcore").getEffectiveLevel())
    logger.info(
        "HTTP client log policy applied via telemetry log_levels: httpx=%s, httpcore=%s",
        httpx_level,
        httpcore_level,
    )


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

    # API key auth middleware: detect API keys on MCP paths, validate via CC
    from app.communication_hub.middleware.api_key_auth import ApiKeyAuthMiddleware
    app.add_middleware(ApiKeyAuthMiddleware)

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
    from app.communication_hub.api.internal.agent_terminate import router as agent_terminate_router
    from app.communication_hub.api.internal.agent_resume import router as agent_resume_router
    from app.communication_hub.api.a2a import router as a2a_router  # Phase 1.1
    from app.communication_hub.api.mcp_tools import mcp_router  # API Key MCP Hub
    from app.communication_hub.mcp.router import register_mcp_protocol_server  # MCP protocol server

    app.include_router(mcp_router)  # MCP tools for external agents
    app.include_router(GatewayRouter)
    app.include_router(ws_router)
    app.include_router(dispatch_router)  # POST /internal/dispatch
    app.include_router(tool_routing_router)  # POST /internal/tools/call
    app.include_router(agent_execute_router)  # POST /internal/agent/execute
    app.include_router(agent_terminate_router)  # POST /internal/agent/terminate/{session_id}
    app.include_router(agent_resume_router)  # POST /internal/agent/resume/{session_id}
    app.include_router(a2a_router)  # POST /internal/a2a/request, /internal/a2a/disconnect/{session_link_id}

    # MCP protocol server — opt-in via CH_MCP_PROTOCOL_SERVER_ENABLED
    register_mcp_protocol_server(app, enabled=settings.ch_mcp_protocol_server_enabled)


app = create_app()


@app.on_event("startup")
async def startup_event() -> None:
    """Run Communication Hub startup tasks."""
    _log_http_client_log_policy()
    settings.log_config_sources()
    await _validate_control_center_reachable()
    await _load_certificate()
    _init_data_client()
    await _start_certificate_renewal()
    await _verify_redis_connectivity()
    await _init_intervention_router()
    _init_task_delegation_router()


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


def _init_data_client() -> None:
    """Initialize Control Center data client used by Communication Hub routes."""
    from app.communication_hub.data_client import ControlCenterDataClient

    manager = getattr(app.state, "certificate_manager", None)
    app.state.data_client = ControlCenterDataClient(cert_manager=manager)
    logger.info("Communication Hub Control Center data client initialized")


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


async def _init_intervention_router() -> None:
    """Initialize the Intervention Router for conversation-scoped intervention routing.

    Wires the InterventionRouter into the ActiveSessionTracker so intervention
    messages can be delivered directly to connected WebSocket clients.
    """
    try:
        from app.api.ws.chat import ActiveSessionTracker
        from app.communication_hub.intervention_router import InterventionRouter

        data_client = getattr(app.state, "data_client", None)
        router = InterventionRouter(data_client=data_client)
        router.set_send_to_session(ActiveSessionTracker.send_to_session)
        app.state.intervention_router = router
        logger.info("Intervention Router initialized and wired to ActiveSessionTracker")
    except Exception as exc:
        logger.warning("Intervention Router initialization failed: %s", exc)


def _init_task_delegation_router() -> None:
    """Initialize the Task Delegation Event Router for non-conversational
    delegation event and intervention routing.

    Stores the router on ``app.state.task_delegation_router`` for access
    from dispatch and tool routing endpoints.
    """
    try:
        from app.communication_hub.services.task_delegation_router import (
            TaskDelegationEventRouter,
        )

        data_client = getattr(app.state, "data_client", None)
        router = TaskDelegationEventRouter(data_client=data_client)
        app.state.task_delegation_router = router
        logger.info("Task Delegation Event Router initialized")
    except Exception as exc:
        logger.warning("Task Delegation Event Router initialization failed: %s", exc)


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
        "The Communication Hub requires Control Center for certificate bootstrap "
        "and data access. Check CONTROL_CENTER_URL and ensure Control Center is running.",
        health_url,
    )
    sys.exit(1)
