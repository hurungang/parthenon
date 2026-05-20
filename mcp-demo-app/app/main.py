from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.auth import keycloak_client
from app.config import settings
from app.registration import register_with_hub
from app.routes.health import health_router
from app.routes.mcp import mcp_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ── Startup ────────────────────────────────────────────────────────────
    logger.info("Starting MCP Demo App (slug=%s)", settings.APP_SLUG)

    # Validate Keycloak connectivity — fail fast if credentials are wrong
    try:
        token = await keycloak_client.get_own_access_token()
        logger.info("Keycloak connectivity OK — access token obtained")
    except Exception as exc:
        logger.error("FATAL: Could not obtain Keycloak access token: %s", exc)
        raise SystemExit(1) from exc

    # Register with the Parthenon MCP Hub
    try:
        await register_with_hub(
            hub_base_url=settings.HUB_BASE_URL,
            api_token=settings.HUB_API_TOKEN,
            slug=settings.APP_SLUG,
            app_base_url=settings.APP_BASE_URL,
        )
        logger.info("Hub registration complete")
    except Exception as exc:
        logger.warning("Hub registration failed (non-fatal for demo): %s", exc)
        logger.warning("The app will start without Hub registration. Health and MCP endpoints will still work.")

    yield

    # ── Shutdown ───────────────────────────────────────────────────────────
    logger.info("MCP Demo App shutting down")


def create_app() -> FastAPI:
    application = FastAPI(
        title="MCP Demo App",
        version="0.1.0",
        description=(
            "Standalone MCP demo service that authenticates with the Keycloak "
            "ai_agents realm and exposes a single helloWorld tool."
        ),
        lifespan=lifespan,
    )
    application.include_router(health_router)
    application.include_router(mcp_router)
    return application


app = create_app()
