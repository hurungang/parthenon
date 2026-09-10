"""Application configuration via Pydantic BaseSettings."""
import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import AliasChoices, BaseModel, Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

_REPO_ROOT = Path(__file__).parent.parent.parent.parent


def _app_yaml_path() -> str:
    """Return path to config/app.yaml (static defaults checked into git)."""
    return os.environ.get(
        "APP_YAML_PATH", str(_REPO_ROOT / "config" / "app.yaml")
    )


def _resolve_app_yaml_path() -> Path:
    """Return resolved Path for app.yaml (used for writing settings back)."""
    return Path(_app_yaml_path())


# ---------------------------------------------------------------------------
# Telemetry — exporter type enum and per-exporter option models
# ---------------------------------------------------------------------------


class TelemetryExporterType(str, Enum):
    """Identifies which export target is active."""

    console = "console"
    file = "file"
    otlp = "otlp"
    logfire = "logfire"
    custom = "custom"


class OtlpExporterOptions(BaseModel):
    """Options for the OTLP (OpenTelemetry Protocol) exporter."""

    endpoint: str = "http://localhost:4317"
    protocol: Literal["grpc", "http"] = "grpc"
    insecure: bool = True


class FileExporterOptions(BaseModel):
    """Options for the rotating-file exporter."""

    path: str = "logs/otel.log"
    max_bytes: int = 10 * 1024 * 1024  # 10 MB
    backup_count: int = 5


class LogfireExporterOptions(BaseModel):
    """Options for the Logfire exporter."""

    token: str | None = None


class CustomExporterOptions(BaseModel):
    """Options for a custom OTLP-HTTP endpoint."""

    endpoint: str = "http://localhost:4318"


# ---------------------------------------------------------------------------
# TelemetrySettings — central config model embedded in Settings
# ---------------------------------------------------------------------------


class TelemetrySettings(BaseModel):
    """All telemetry configuration options.

    Fields are intentionally a ``BaseModel`` (not ``BaseSettings``) so the
    whole block nests cleanly as a single ``telemetry`` field on ``Settings``.
    """

    # Active export targets — can list multiple simultaneously
    exporters: list[TelemetryExporterType] = Field(
        default_factory=lambda: [TelemetryExporterType.otlp]
    )

    # Signal enable flags
    traces_enabled: bool = True
    metrics_enabled: bool = True
    logs_enabled: bool = True

    # Service name forwarded to OTEL SDK resource
    service_name: str = "parthenon-api"

    # Per-exporter options
    otlp: OtlpExporterOptions = Field(default_factory=OtlpExporterOptions)
    file: FileExporterOptions = Field(default_factory=FileExporterOptions)
    logfire: LogfireExporterOptions = Field(default_factory=LogfireExporterOptions)
    custom: CustomExporterOptions = Field(default_factory=CustomExporterOptions)

    # Component → log level map; "root" maps to the root logger
    log_levels: dict[str, str] = Field(
        default_factory=lambda: {
            "root": "INFO",
        }
    )

    # Dedicated control for httpx / httpcore log verbosity.
    # Defaults to WARNING (silent in normal operation).
    # Set TELEMETRY__HTTP_CLIENT_LOG_LEVEL=DEBUG to see full HTTP wire traffic.
    http_client_log_level: str = Field(default="WARNING")

    @field_validator("log_levels", mode="before")
    @classmethod
    def validate_log_levels(cls, v: dict[str, str]) -> dict[str, str]:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        for component, level in v.items():
            if level.upper() not in valid_levels:
                raise ValueError(
                    f"Invalid log level '{level}' for component '{component}'. "
                    f"Must be one of: {', '.join(sorted(valid_levels))}"
                )
        return {k: lv.upper() for k, lv in v.items()}

    @field_validator("http_client_log_level", mode="before")
    @classmethod
    def validate_http_client_log_level(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(
                f"Invalid http_client_log_level '{v}'. "
                f"Must be one of: {', '.join(sorted(valid_levels))}"
            )
        return v.upper()


class _SparseYamlSource(YamlConfigSettingsSource):
    """YamlConfigSettingsSource that drops null/empty template placeholders.

    Bare YAML keys (``provider_type:``) parse as ``None``; we treat those as
    "not set" so they don't shadow field defaults or env-var values.
    """

    def __call__(self) -> dict[str, Any]:
        data = super().__call__()
        return {k: v for k, v in data.items() if v is not None and v != ""}


# ---------------------------------------------------------------------------
# Runtime helper: detect which source resolved a value
# ---------------------------------------------------------------------------


def _load_yaml_keys(yaml_path: str) -> set[str]:
    """Return the set of top-level keys present in a YAML file.

    Returns an empty set if the file does not exist or is empty.
    """
    try:
        with open(yaml_path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except Exception:
        return set()
    if isinstance(raw, dict):
        return {k for k, v in raw.items() if v is not None and v != ""}
    return set()

class Settings(BaseSettings):
    """Platform-wide settings loaded from environment variables and app.yaml.

    Priority order (highest to lowest):
    1. Environment variable / .env file
    2. config/app.yaml (application-wide static defaults)
    3. Hard-coded field default
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__",
    )

    # Application
    app_name: str = "Parthenon AI Harness"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Per-component PostgreSQL fields (override database_url when set)
    postgres_host: str | None = Field(default=None)
    postgres_port: int | None = Field(default=None)
    postgres_user: str | None = Field(default=None)
    postgres_password: str | None = Field(default=None)
    postgres_db: str | None = Field(default=None)

    @property
    def computed_database_url(self) -> str:
        """Return the composed database URL from per-component env vars.

        When any per-component PostgreSQL env var is set, composes a full
        ``postgresql+asyncpg://`` URL.  Falls back to ``database_url``
        when no per-component vars are present.
        """
        if any(
            getattr(self, f) is not None
            for f in ("postgres_host", "postgres_port", "postgres_user", "postgres_password", "postgres_db")
        ):
            host = self.postgres_host or "localhost"
            port = self.postgres_port or 5432
            user = self.postgres_user or "parthenon"
            password = self.postgres_password or ""
            db = self.postgres_db or "parthenon"
            return (
                f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"
            )
        return self.database_url

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Per-component Redis fields (override redis_url when set)
    redis_host: str | None = Field(default=None)
    redis_port: int | None = Field(default=None)
    redis_password: str | None = Field(default=None)
    redis_db: int | None = Field(default=None)

    @property
    def computed_redis_url(self) -> str:
        """Return the composed Redis URL from per-component env vars.

        When any per-component Redis env var is set, composes a full
        ``redis://`` URL.  Falls back to ``redis_url`` when no
        per-component vars are present.
        """
        if any(
            getattr(self, f) is not None
            for f in ("redis_host", "redis_port", "redis_password", "redis_db")
        ):
            host = self.redis_host or "localhost"
            port = self.redis_port or 6379
            db = self.redis_db if self.redis_db is not None else 0
            password_segment = f":{self.redis_password}@" if self.redis_password else ""
            # If no password, don't include the colon
            if password_segment == ":None@":
                password_segment = "@"
            return f"redis://{password_segment}{host}:{port}/{db}" if self.redis_password else f"redis://{host}:{port}/{db}"
        return self.redis_url

    # Auth / OIDC
    oidc_provider_url: str = Field(default="http://localhost:8080/realms/parthenon")
    secret_key: str = Field(default="change-me-in-production")
    jwt_algorithm: str = Field(default="RS256")
    jwt_audience: str = Field(default="parthenon")

    # Identity provider settings — populated from DB IdentityProviderConfig at runtime
    identity_provider_type: str = Field(default="unconfigured")
    identity_realm: str = Field(default="")
    identity_setup_complete: bool = Field(default=False)
    agent_realm_name: str = Field(default="ai_agents")
    workflow_generation_model_id: str = Field(default="")

    # Credential Vault — must be exactly 32 bytes for AES-256
    credential_vault_key: str = Field(default="change-me-32-byte-key-for-aes256!")

    @field_validator("credential_vault_key")
    @classmethod
    def validate_vault_key(cls, v: str) -> str:
        if len(v.encode()) < 32:
            raise ValueError("credential_vault_key must be at least 32 bytes")
        return v

    # Bootstrap keys — Control Center reads these from env via the bootstrap endpoint.
    # Defined here so they appear in settings validation and startup logging.
    agent_runtime_bootstrap_key: str | None = Field(default=None)
    comm_hub_bootstrap_key: str | None = Field(default=None)
    # Key used by the backend integration test suite to obtain a service certificate
    test_service_bootstrap_key: str | None = Field(default=None)

    # Service URLs for inter-service communication
    communication_hub_url: str = Field(default="http://localhost:8002")
    control_center_url: str = Field(default="http://localhost:8000")
    agent_runtime_url: str = Field(default="http://localhost:8001")

    # Communication Hub — MCP protocol server feature flag (opt-in)
    # When enabled, the CH exposes a standard MCP protocol endpoint (initialize /
    # tools/list / tools/call over Streamable HTTP and SSE) authenticated by API keys.
    ch_mcp_protocol_server_enabled: bool = Field(default=False)

    # OTEL — replaced by nested TelemetrySettings
    telemetry: TelemetrySettings = Field(default_factory=TelemetrySettings)

    # Agent defaults
    default_max_agent_instances: int = 5
    agent_question_timeout_seconds: int = 300

    # Scheduling
    scheduler_enabled: bool = True
    scheduler_check_interval_seconds: int = 60

    # Rate limiting
    gateway_rate_limit_per_minute: int = 60

    # ══════════════════════════════════════════════════════════════════════
    # Keycloak admin credentials — SETUP TOOL ONLY
    #
    # These are consumed exclusively by the ``setup/`` CLI and the
    # ``IdentityBootstrapService`` during initial provisioning.  The
    # Control Center runtime does NOT require or load them — setting
    # them at runtime is harmless but unnecessary.
    # ══════════════════════════════════════════════════════════════════════
    keycloak_admin_user: str | None = Field(
        default=None,
        description="Keycloak master-realm admin username (setup tool only)",
    )
    keycloak_admin_password: str | None = Field(
        default=None,
        description="Keycloak master-realm admin password (setup tool only)",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Place YAML source below env vars so env always wins.

        Priority (highest to lowest):
        1. init_settings      — values passed to Settings() constructor
        2. env_settings       — environment variables
        3. dotenv_settings    — .env file
        4. app.yaml           — application-wide static defaults
        5. file_secret_settings — secrets directory
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _SparseYamlSource(settings_cls, yaml_file=_app_yaml_path()),
            file_secret_settings,
        )

    def log_config_sources(self) -> None:
        """Log the resolved source for every infrastructure connection.

        Uses INFO level.  Passwords are redacted in log output.
        Called by each service's startup event.
        """
        import logging as _logging
        _log = _logging.getLogger(__name__)

        _app_keys = _load_yaml_keys(_app_yaml_path())

        def _source(field_name: str, env_names: list[str]) -> str:
            """Infer config source: env → app.yaml → default."""
            for ename in env_names:
                if ename in os.environ:
                    return f"env:{ename}"
            if field_name in _app_keys:
                return "yaml:config/app.yaml"
            return "default"

        # PostgreSQL
        pg_source = _source(
            "database_url",
            ["POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_USER",
             "POSTGRES_PASSWORD", "POSTGRES_DB", "DATABASE_URL"],
        )
        _log.info(
            "resolved PostgreSQL from %s: %s",
            pg_source, _redact_url(self.computed_database_url),
        )

        # Redis
        redis_source = _source(
            "redis_url",
            ["REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD", "REDIS_DB", "REDIS_URL"],
        )
        _log.info(
            "resolved Redis from %s: %s",
            redis_source, _redact_url(self.computed_redis_url),
        )

        # OIDC Provider
        oidc_source = _source("oidc_provider_url", ["OIDC_PROVIDER_URL"])
        _log.info(
            "resolved OIDC provider from %s: %s",
            oidc_source, self.oidc_provider_url,
        )

        # OTEL
        otel_env_keys = [k for k in os.environ if k.startswith("TELEMETRY__")]
        otel_source = "env" if otel_env_keys else (
            "yaml:config/app.yaml" if "telemetry" in _app_keys else "default"
        )
        _log.info(
            "resolved OTEL exporters=%s traces=%s metrics=%s logs=%s from %s",
            [e.value for e in self.telemetry.exporters],
            self.telemetry.traces_enabled,
            self.telemetry.metrics_enabled,
            self.telemetry.logs_enabled,
            otel_source,
        )


import re as _re


def _redact_url(url: str) -> str:
    """Redact password from a database or Redis URL for safe logging."""
    return _re.sub(r"://[^:]+:[^@]+@", "://***:***@", url)


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
