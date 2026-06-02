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
    """
    _log_http_client_log_policy()
    await _cleanup_stale_sessions_on_startup()
    await _run_bootstrap()
    await _seed_system_tools()
    await _run_skill_seeder()
    await _initialize_agent_realm()
    await _initialize_certificate_authority()


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


async def _initialize_agent_realm() -> None:
    """Initialize the agent realm in the identity provider on startup."""
    try:
        from app.services.identity.realm_manager import RealmManager
        manager = RealmManager()
        await manager.initialize_agent_realm()
        logger.info("Agent realm initialization complete")
    except Exception:
        logger.exception(
            "Agent realm initialization failed; agents may not be able to authenticate. "
            "Ensure the identity provider is reachable and configured correctly."
        )


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


# SessionDispatcher is now started by the Agent Runtime service (app.agent_runtime.main).
# It is no longer a Control Center startup responsibility.
