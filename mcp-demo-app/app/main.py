from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.auth import keycloak_client
from app.booking_store import booking_store
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

    # Seed the in-memory booking store (deterministic; restart = reset)
    booking_store.reset()
    logger.info(
        "Booking store seeded: %d flights, %d bookings",
        len(booking_store.flights),
        len(booking_store.bookings),
    )

    # Validate Keycloak connectivity — fail fast if credentials are wrong
    try:
        token = await keycloak_client.get_own_access_token()
        logger.info("Keycloak connectivity OK — access token obtained")
    except Exception as exc:
        logger.error("FATAL: Could not obtain Keycloak access token: %s", exc)
        raise SystemExit(1) from exc

    # Register with the Parthenon MCP Hub — use a fresh Keycloak access
    # token (the static HUB_API_TOKEN is only a fallback) and the tenant
    # header so CC's tenant-resolution middleware can bind the context.
    try:
        hub_token = await keycloak_client.get_own_access_token()
        await register_with_hub(
            hub_base_url=settings.HUB_BASE_URL,
            api_token=hub_token,
            slug=settings.APP_SLUG,
            app_base_url=settings.APP_BASE_URL,
            tenant=settings.HUB_TENANT,
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
        version="0.2.0",
        description=(
            "Standalone MCP demo service with two demo modes: greeting tools "
            "that demonstrate identity propagation and tool-level access "
            "control, and fictional airline booking tools (search, book, pay, "
            "status, check-in, seat selection, cancel) backed by an "
            "in-memory store that resets deterministically on startup."
        ),
        lifespan=lifespan,
    )
    application.include_router(health_router)
    application.include_router(mcp_router)
    return application


app = create_app()
