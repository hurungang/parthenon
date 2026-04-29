"""Application configuration via Pydantic BaseSettings."""
import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

_REPO_ROOT = Path(__file__).parent.parent.parent.parent


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
    log_levels: dict[str, str] = Field(default_factory=lambda: {"root": "INFO"})

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


def _identity_yaml_path() -> str:
    return os.environ.get("IDENTITY_YAML_PATH", str(_REPO_ROOT / "config" / "identity.yaml"))


class _SparseYamlSource(YamlConfigSettingsSource):
    """YamlConfigSettingsSource that drops null/empty template placeholders.

    Bare YAML keys (``provider_type:``) parse as ``None``; we treat those as
    "not set" so they don't shadow field defaults or env-var values.
    """

    def __call__(self) -> dict[str, Any]:
        data = super().__call__()
        return {k: v for k, v in data.items() if v is not None and v != ""}


class Settings(BaseSettings):
    """Platform-wide settings loaded from environment variables and config/identity.yaml.

    Priority order (highest to lowest):
    1. Environment variable / .env file
    2. config/identity.yaml (via YamlConfigSettingsSource)
    3. Hard-coded default
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

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Auth / OIDC — AliasChoices lets the YAML key name also populate this field
    oidc_provider_url: str = Field(default="http://localhost:8080/realms/parthenon")
    secret_key: str = Field(default="change-me-in-production")
    jwt_algorithm: str = Field(default="RS256")
    jwt_audience: str = Field(
        default="parthenon",
        validation_alias=AliasChoices("jwt_audience", "audience"),
    )

    # Identity provider settings — merged from config/identity.yaml + env vars
    identity_provider_type: str = Field(
        default="unconfigured",
        validation_alias=AliasChoices("identity_provider_type", "provider_type"),
    )
    identity_realm: str = Field(
        default="",
        validation_alias=AliasChoices("identity_realm", "realm_name"),
    )
    identity_setup_complete: bool = Field(
        default=False,
        validation_alias=AliasChoices("identity_setup_complete", "setup_complete"),
    )

    # Credential Vault — must be exactly 32 bytes for AES-256
    credential_vault_key: str = Field(default="change-me-32-byte-key-for-aes256!")

    @field_validator("credential_vault_key")
    @classmethod
    def validate_vault_key(cls, v: str) -> str:
        if len(v.encode()) < 32:
            raise ValueError("credential_vault_key must be at least 32 bytes")
        return v

    # OTEL — replaced by nested TelemetrySettings
    telemetry: TelemetrySettings = Field(default_factory=TelemetrySettings)

    # Agent defaults
    default_max_agent_instances: int = 5
    agent_question_timeout_seconds: int = 300

    # Scheduling
    scheduler_enabled: bool = True

    # Rate limiting
    gateway_rate_limit_per_minute: int = 60

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Place YAML below env vars so env always wins."""
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _SparseYamlSource(settings_cls, yaml_file=_identity_yaml_path()),
            file_secret_settings,
        )


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
