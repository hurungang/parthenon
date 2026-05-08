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
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": exc.errors(),
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
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "version": settings.app_version}

    # Register routers
    _register_routers(app)

    return app


def _register_routers(app: FastAPI) -> None:
    """Register all API routers."""
    from app.api.v1 import router as api_v1_router
    from app.api.gateway.lifecycle import GatewayRouter
    from app.api.ws.chat import ws_router

    app.include_router(api_v1_router, prefix="/api/v1")
    app.include_router(GatewayRouter)
    app.include_router(ws_router)


async def _run_bootstrap() -> None:
    """Run the bootstrap service to seed system roles on startup."""
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.permissions.bootstrap_service import BootstrapService
        async with AsyncSessionLocal() as db:
            await BootstrapService().initialize(db)
    except Exception:
        logger.exception("Bootstrap service failed; application will continue.")


app = create_app()


@app.on_event("startup")
async def startup_event() -> None:
    """Run startup tasks including bootstrap seeding and session dispatcher."""
    await _run_bootstrap()
    await _run_skill_seeder()
    await _initialize_agent_realm()
    await _start_session_dispatcher()


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


async def _start_session_dispatcher() -> None:
    """Start the background SessionDispatcher as an asyncio task."""
    try:
        import asyncio
        from app.services.agents.session_dispatcher import SessionDispatcher
        dispatcher = SessionDispatcher()
        asyncio.create_task(dispatcher.run())
        logger.info("SessionDispatcher started")
    except Exception:
        logger.exception("Failed to start SessionDispatcher; agent sessions will not auto-execute")
