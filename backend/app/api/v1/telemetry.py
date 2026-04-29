"""Telemetry configuration API router."""
import logging
from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_current_claims
from app.core.config import TelemetryExporterType, get_settings
from app.schemas.telemetry import FrontendTelemetryConfigSchema

logger = logging.getLogger(__name__)

TelemetryRouter = APIRouter(prefix="/telemetry", tags=["Telemetry"])


def _resolve_otlp_http_endpoint() -> str:
    """Derive the OTLP HTTP endpoint the frontend browser should export to.

    Resolution order:
    1. If ``otlp`` is an active exporter and ``protocol=http``, use that endpoint.
    2. If ``otlp`` is an active exporter with ``protocol=grpc``, derive the HTTP
       equivalent by replacing the default gRPC port (4317) with the OTLP HTTP
       port (4318).
    3. If ``custom`` is an active exporter, use the custom endpoint.
    4. Fall back to the standard local OTLP HTTP endpoint.
    """
    settings = get_settings()
    cfg = settings.telemetry
    exporters = cfg.exporters

    if TelemetryExporterType.otlp in exporters:
        if cfg.otlp.protocol == "http":
            return cfg.otlp.endpoint
        # gRPC endpoint — derive HTTP equivalent
        return cfg.otlp.endpoint.replace(":4317", ":4318")

    if TelemetryExporterType.custom in exporters:
        return cfg.custom.endpoint

    return "http://localhost:4318"


@TelemetryRouter.get("/config", response_model=FrontendTelemetryConfigSchema)
async def get_telemetry_config(
    _claims: dict[str, Any] = Depends(get_current_claims),
) -> FrontendTelemetryConfigSchema:
    """Return the frontend-relevant telemetry configuration subset.

    Requires a valid JWT (enforced by the auth middleware; dependency makes
    the requirement explicit in the OpenAPI schema).
    """
    settings = get_settings()
    cfg = settings.telemetry

    return FrontendTelemetryConfigSchema(
        otlp_http_endpoint=_resolve_otlp_http_endpoint(),
        service_name=cfg.service_name,
        traces_enabled=cfg.traces_enabled,
        metrics_enabled=cfg.metrics_enabled,
    )
