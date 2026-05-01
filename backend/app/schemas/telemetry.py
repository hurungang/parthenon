"""Pydantic schemas for the telemetry config API."""

from pydantic import BaseModel


class FrontendTelemetryConfigSchema(BaseModel):
    """Frontend-safe subset of TelemetrySettings.

    Contains only the fields the browser OTEL SDK needs.
    No credentials, tokens, or full config dumps.
    """

    otlp_http_endpoint: str
    service_name: str
    traces_enabled: bool
    metrics_enabled: bool
