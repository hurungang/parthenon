"""Unit tests for TelemetrySettings config model."""
import os

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.config import (
    CustomExporterOptions,
    FileExporterOptions,
    LogfireExporterOptions,
    OtlpExporterOptions,
    Settings,
    TelemetryExporterType,
    TelemetrySettings,
    get_settings,
)


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestTelemetrySettingsDefaults:
    def test_default_exporters(self) -> None:
        cfg = TelemetrySettings()
        assert cfg.exporters == [TelemetryExporterType.otlp]

    def test_default_signals_enabled(self) -> None:
        cfg = TelemetrySettings()
        assert cfg.traces_enabled is True
        assert cfg.metrics_enabled is True
        assert cfg.logs_enabled is True

    def test_default_service_name(self) -> None:
        cfg = TelemetrySettings()
        assert cfg.service_name == "parthenon-api"

    def test_default_otlp_options(self) -> None:
        cfg = TelemetrySettings()
        assert cfg.otlp.endpoint == "http://localhost:4317"
        assert cfg.otlp.protocol == "grpc"
        assert cfg.otlp.insecure is True

    def test_default_file_options(self) -> None:
        cfg = TelemetrySettings()
        assert cfg.file.path == "logs/otel.log"
        assert cfg.file.max_bytes == 10 * 1024 * 1024
        assert cfg.file.backup_count == 5

    def test_default_logfire_token_is_none(self) -> None:
        cfg = TelemetrySettings()
        assert cfg.logfire.token is None

    def test_default_log_levels(self) -> None:
        cfg = TelemetrySettings()
        assert cfg.log_levels == {"root": "INFO"}

    def test_settings_embeds_telemetry(self) -> None:
        settings = Settings()
        assert isinstance(settings.telemetry, TelemetrySettings)
        assert settings.telemetry.service_name == "parthenon-api"


class TestTelemetrySettingsEnvOverride:
    def test_service_name_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEMETRY__SERVICE_NAME", "my-custom-service")
        settings = Settings()
        assert settings.telemetry.service_name == "my-custom-service"

    def test_traces_disabled_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEMETRY__TRACES_ENABLED", "false")
        settings = Settings()
        assert settings.telemetry.traces_enabled is False

    def test_metrics_disabled_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEMETRY__METRICS_ENABLED", "false")
        settings = Settings()
        assert settings.telemetry.metrics_enabled is False


class TestTelemetrySettingsValidation:
    def test_invalid_log_level_raises(self) -> None:
        with pytest.raises(Exception):
            TelemetrySettings(log_levels={"root": "VERBOSE"})

    def test_valid_log_levels_normalised_to_uppercase(self) -> None:
        cfg = TelemetrySettings(log_levels={"root": "debug", "app.services": "warning"})
        assert cfg.log_levels["root"] == "DEBUG"
        assert cfg.log_levels["app.services"] == "WARNING"

    def test_all_valid_log_levels_accepted(self) -> None:
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            cfg = TelemetrySettings(log_levels={"root": level})
            assert cfg.log_levels["root"] == level


class TestExporterOptionModels:
    def test_otlp_options_http_protocol(self) -> None:
        opts = OtlpExporterOptions(protocol="http", endpoint="http://collector:4318")
        assert opts.protocol == "http"
        assert opts.endpoint == "http://collector:4318"

    def test_file_options_custom_path(self) -> None:
        opts = FileExporterOptions(path="/var/log/otel.log", max_bytes=5_000_000, backup_count=3)
        assert opts.path == "/var/log/otel.log"
        assert opts.max_bytes == 5_000_000
        assert opts.backup_count == 3

    def test_logfire_options_with_token(self) -> None:
        opts = LogfireExporterOptions(token="abc123")
        assert opts.token == "abc123"

    def test_custom_options_endpoint(self) -> None:
        opts = CustomExporterOptions(endpoint="https://my-collector.example.com")
        assert opts.endpoint == "https://my-collector.example.com"
