"""FastAPI application entry point."""
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env into os.environ before anything else so os.getenv() calls work
load_dotenv(Path(__file__).parent.parent / ".env", override=False)

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import get_settings
from app.core.telemetry import setup_telemetry
from app.middleware.auth import JWTAuthMiddleware

# Configure logging before anything else
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)
settings = get_settings()

logger.info("Starting Parthenon backend in %s mode", settings.environment)


def _log_http_client_log_policy() -> None:
    httpx_level = logging.getLevelName(logging.getLogger("httpx").getEffectiveLevel())
    httpcore_level = logging.getLevelName(logging.getLogger("httpcore").getEffectiveLevel())
    logger.info(
        "HTTP client log policy applied via telemetry log_levels: httpx=%s, httpcore=%s",
        httpx_level,
        httpcore_level,
    )

# Global rate limiter instance — shared across all route modules
limiter = Limiter(key_func=get_remote_address)

# Global OIDC Provider Registry — initialized at startup, accessed by middleware
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.services.oidc_provider_registry import OIDCProviderRegistry

_registry = None

def _get_registry():
    """Return the module-level OIDC Provider Registry singleton."""
    global _registry
    if _registry is None:
        from app.services.oidc_provider_registry import OIDCProviderRegistry
        _registry = OIDCProviderRegistry()
    return _registry


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    # Initialise OpenTelemetry before anything else so instrumentation patches apply
    setup_telemetry(settings.telemetry)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Parthenon Enterprise AI Harness API",
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url="/redoc" if settings.environment != "production" else None,
    )

    # Attach the slowapi limiter to the app state
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

    # 422 Unprocessable Entity handler with structured field details
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Pydantic v2 model_validator errors may include exception objects in 'ctx'
        # that are not JSON-serializable.  Convert them to strings before serialising.
        def _make_serializable(obj):  # type: ignore[no-untyped-def]
            if isinstance(obj, dict):
                return {k: _make_serializable(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_make_serializable(item) for item in obj]
            if isinstance(obj, Exception):
                return str(obj)
            return obj

        serializable_errors = _make_serializable(exc.errors())
        # Truncate body to keep logs bounded for large payloads
        body_repr = exc.body
        if isinstance(body_repr, (dict, list)):
            body_repr = str(body_repr)
        if isinstance(body_repr, str) and len(body_repr) > 1000:
            body_repr = body_repr[:1000] + "...<truncated>"

        logger.warning(
            "Request validation failed (422): method=%s path=%s errors=%s body=%s",
            request.method,
            request.url.path,
            serializable_errors,
            body_repr,
        )

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": serializable_errors,
                "body": exc.body,
            },
        )

    # 500 Internal Server Error handler — logs the full traceback to structured logs
    @app.exception_handler(Exception)
    async def internal_server_error_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception(
            "Internal server error (500): method=%s path=%s",
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    # CORS
    # Browsers reject allow_origins=["*"] + allow_credentials=True.
    # In development, explicitly allow frontend dev and preview servers.
    if settings.environment == "development":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost:5173",  # Vite dev server
                "http://localhost:4173",  # Vite preview server
                "http://localhost:3000",  # Alternative dev port
            ],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[],  # set explicit origins via env in production
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # JWT Auth Middleware (applied after CORS)
    app.add_middleware(JWTAuthMiddleware)

    # Health check (public endpoint)
    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str | None]:
        from app.services.certificate_authority import get_ca_certificate
        ca_cert = get_ca_certificate()
        cert_expiry: str | None = None
        if ca_cert is not None:
            cert_expiry = ca_cert.not_valid_after_utc.isoformat()
        return {
            "status": "ok",
            "service": "control-center",
            "version": settings.app_version,
            "cert_expires_at": cert_expiry,
        }

    # Register routers
    _register_routers(app)

    return app


def _register_routers(app: FastAPI) -> None:
    """Register Control Center API routers.

    REST API and internal endpoints only. WebSocket chat routes are served by
    Communication Hub (app.communication_hub.main). Agent Runtime service
    (app.agent_runtime.main) handles session dispatching.
    """
    from app.api.v1 import router as api_v1_router

    app.include_router(api_v1_router, prefix="/api/v1")


async def _run_bootstrap() -> None:
    """Run the bootstrap service to seed system roles on startup."""
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.permissions.bootstrap_service import BootstrapService
        async with AsyncSessionLocal() as db:
            await BootstrapService().initialize(db)
    except Exception:
        logger.exception("Bootstrap service failed; application will continue.")


async def _cleanup_stale_sessions_on_startup() -> None:
    """Close all queued/running sessions so restart always starts clean."""
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.agents.session_recovery_service import SessionRecoveryService

        async with AsyncSessionLocal() as db:
            closed_count = await SessionRecoveryService().cleanup_non_terminal_sessions(db)
            await db.commit()
        if closed_count:
            logger.warning(
                "Startup cleanup closed %d non-terminal session(s)",
                closed_count,
            )
        else:
            logger.info("Startup cleanup found no non-terminal sessions")
    except Exception:
        logger.exception("Startup session cleanup failed; application will continue.")


async def _seed_system_tools() -> None:
    """Seed system MCP server and tools into database on startup."""
    try:
        from app.db.session import AsyncSessionLocal
        from app.api.v1.mcp_hub import seed_system_tools
        async with AsyncSessionLocal() as db:
            await seed_system_tools(db)
            await db.commit()
        logger.info("System tools seeding complete")
    except Exception:
        logger.exception("System tools seeding failed; application will continue.")


app = create_app()


@app.on_event("startup")
async def startup_event() -> None:
    """Run Control Center startup tasks.

    Session dispatching is handled by the Agent Runtime service.
    Startup validations run first — any unreachable dependency causes
    immediate exit.  Identity provider provisioning has been moved to the
    separate ``setup/`` CLI for production security.
    """
    _log_http_client_log_policy()

    # Log resolved configuration sources for every infrastructure connection
    settings.log_config_sources()

    # Phase 1: Validate external dependencies before doing any DB work
    await _validate_postgresql_reachable()
    await _validate_redis_reachable()
    await _validate_oidc_provider()

    # Phase 2: Internal data seeding and service initialization
    await _cleanup_stale_sessions_on_startup()
    await _run_bootstrap()
    await _seed_system_tools()
    await _cleanup_super_admin_db_records()
    await _initialize_oidc_provider_registry()
    await _run_skill_seeder()
    await _initialize_certificate_authority()
    await _start_scheduling_engine()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await _stop_scheduling_engine()


async def _cleanup_super_admin_db_records() -> None:
    """Remove super admin PlatformUser and Identity records from DB.

    Super admin is now purely env-var based — no DB records needed.
    """
    try:
        from app.db.session import AsyncSessionLocal
        from sqlalchemy import delete

        async with AsyncSessionLocal() as db:
            from app.db.models.identity import Identity as IdentityModel
            from app.db.models.platform_user import PlatformUser
            result = await db.execute(
                delete(IdentityModel).where(IdentityModel.subject.like("super_admin:%"))
            )
            deleted_ids = result.rowcount
            result2 = await db.execute(
                delete(PlatformUser).where(PlatformUser.sub.like("super_admin:%"))
            )
            deleted_users = result2.rowcount
            await db.commit()
            if deleted_ids or deleted_users:
                logger.info(
                    "Cleaned up %d super_admin Identity and %d PlatformUser records",
                    deleted_ids, deleted_users,
                )
    except Exception:
        logger.exception("Failed to clean up super admin DB records")


async def _initialize_oidc_provider_registry() -> None:
    """Load OIDC provider configs from DB into the in-memory registry."""
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.oidc_provider_registry import OIDCProviderRegistry
        async with AsyncSessionLocal() as db:
            registry = _get_registry()
            await registry.initialize(db)

        has_user = registry.has_user_provider()
        has_agent = registry.has_agent_provider()
        logger.info(
            "OIDCProviderRegistry initialized: user_provider=%s, agent_provider=%s, total=%d",
            has_user, has_agent, len(registry.list_providers()),
        )
    except Exception:
        logger.exception(
            "OIDCProviderRegistry initialization failed; auth will be unavailable."
        )


async def _run_skill_seeder() -> None:
    """Idempotently seed default platform skills (save_result, send_notification)."""
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.skill_seeder import SkillSeeder
        async with AsyncSessionLocal() as db:
            summary = await SkillSeeder().run(db)
            await db.commit()
        logger.info("SkillSeeder complete: %s", summary)
    except Exception:
        logger.exception("SkillSeeder failed; application will continue without default skills.")


# ── Startup validations (replaced auto-provisioning) ──────────────────────


async def _validate_postgresql_reachable() -> None:
    """Validate PostgreSQL connectivity with a lightweight query.

    On failure, logs a clear error and exits the process — the Control
    Center cannot operate without a database.
    """
    import asyncio
    import asyncpg
    from urllib.parse import urlparse

    try:
        parsed = urlparse(settings.database_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        db_name = parsed.path.lstrip("/") or "unknown"
    except Exception:
        host, port, db_name = "unknown", 5432, "unknown"

    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(
                host=host,
                port=port,
                user=parsed.username or "",
                password=parsed.password or "",
                database=db_name,
                timeout=5,
            ),
            timeout=5.0,
        )
        await conn.execute("SELECT 1")
        await conn.close()
        logger.info(
            "resolved PostgreSQL from database_url: %s:%s/%s (password redacted)",
            host, port, db_name,
        )
    except Exception as exc:
        logger.error(
            "PostgreSQL is NOT reachable at %s:%s/%s: %s. "
            "Check DATABASE_URL or POSTGRES_* env vars and ensure the database is running.",
            host, port, db_name, exc,
        )
        sys.exit(1)


async def _validate_redis_reachable() -> None:
    """Validate Redis connectivity with PING.

    On failure, logs a clear error and exits the process.
    """
    import redis.asyncio as aioredis

    redis_url = getattr(settings, "computed_redis_url", None) or settings.redis_url
    try:
        client = aioredis.from_url(redis_url, socket_connect_timeout=5)
        await client.ping()
        await client.aclose()
        logger.info(
            "resolved Redis from redis_url: %s (password redacted)",
            _redact_url(redis_url),
        )
    except Exception as exc:
        logger.error(
            "Redis is NOT reachable at %s: %s. "
            "Check REDIS_URL or REDIS_* env vars and ensure Redis is running.",
            _redact_url(redis_url), exc,
        )
        sys.exit(1)


async def _validate_oidc_provider() -> None:
    """Validate the OIDC provider is reachable (when super-admin login is disabled).

    When super-admin login is enabled, the super admin may be in the middle
    of initial setup, so the check is skipped.  When disabled, the OIDC
    provider is the only auth path and must be reachable.
    """
    from app.services.super_admin_auth_service import super_admin_enabled
    from app.services.identity.realm_manager import RealmManager

    if super_admin_enabled():
        logger.info(
            "OIDC reachability validation skipped — super-admin login is enabled "
            "(PARTHENON_SUPER_ADMIN_ENABLED is set). "
            "The OIDC provider may not be configured yet."
        )
        return

    manager = RealmManager()
    reachable, error = await manager.validate_agent_realm()
    if not reachable:
        logger.error(
            "OIDC provider is NOT reachable at %s: %s. "
            "Super-admin login is disabled — the OIDC provider must be configured and running. "
            "Check OIDC_PROVIDER_URL or run the setup command to initialize the identity provider.",
            settings.oidc_provider_url,
            error,
        )
        sys.exit(1)

    logger.info(
        "OIDC provider validated at %s/.well-known/openid-configuration",
        settings.oidc_provider_url.rstrip("/"),
    )


def _redact_url(url: str) -> str:
    """Redact password from a database or Redis URL for safe logging."""
    import re
    return re.sub(r"://[^:]+:[^@]+@", "://***:***@", url)


async def _initialize_certificate_authority() -> None:
    """Initialize the Certificate Authority on startup.

    Generates (or loads) the root CA certificate used to sign and validate
    agent instance certificates.  CA is stored in memory; private key
    is encrypted at rest if CA_PRIVATE_KEY_ENCRYPTED env var is set.
    """
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.certificate_authority import initialize_ca
        async with AsyncSessionLocal() as db:
            ca_cert = await initialize_ca(db)
        logger.info(
            "Certificate Authority initialized — serial=%s expires=%s",
            ca_cert.serial_number,
            ca_cert.not_valid_after_utc,
        )
    except Exception:
        logger.exception(
            "Certificate Authority initialization failed; "
            "agent certificate issuance/validation will not work. "
            "Ensure CREDENTIAL_VAULT_KEY is set and the database is reachable."
        )


async def _start_scheduling_engine() -> None:
    """Start the scheduling engine and recover active schedules."""
    if not settings.scheduler_enabled:
        logger.info("Scheduler is disabled — skipping scheduling engine startup")
        return
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.scheduling.scheduler import get_scheduling_engine
        engine = get_scheduling_engine()
        engine.start()
        recovered = await engine.recover_schedules(AsyncSessionLocal)
        logger.info("Scheduling engine started with %d recovered schedule(s)", recovered)
    except Exception:
        logger.exception("Scheduling engine startup failed; application will continue.")


async def _stop_scheduling_engine() -> None:
    """Shutdown the scheduling engine."""
    from app.services.scheduling.scheduler import get_scheduling_engine
    try:
        engine = get_scheduling_engine()
        engine.shutdown()
        logger.info("Scheduling engine stopped")
    except Exception:
        logger.exception("Scheduling engine shutdown failed.")


# SessionDispatcher is now started by the Agent Runtime service (app.agent_runtime.main).
# It is no longer a Control Center startup responsibility.
