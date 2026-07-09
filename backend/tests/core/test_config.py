"""Unit tests for Settings and _SparseYamlSource in app.core.config."""
import os
from pathlib import Path

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestSparseYamlSource:
    """Tests for _SparseYamlSource behaviour via Settings loading."""

    def test_yaml_identity_provider_type_loaded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """App YAML with identity_provider_type: keycloak_bundled loads correctly."""
        yaml_file = tmp_path / "test_app.yaml"
        yaml_file.write_text("identity_provider_type: keycloak_bundled\n", encoding="utf-8")

        monkeypatch.setenv("APP_YAML_PATH", str(yaml_file))
        monkeypatch.delenv("IDENTITY_PROVIDER_TYPE", raising=False)

        settings = Settings()
        assert settings.identity_provider_type == "keycloak_bundled"

    def test_env_var_overrides_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env var overrides YAML value."""
        yaml_file = tmp_path / "test_app.yaml"
        yaml_file.write_text("identity_provider_type: keycloak_bundled\n", encoding="utf-8")

        monkeypatch.setenv("APP_YAML_PATH", str(yaml_file))
        monkeypatch.setenv("IDENTITY_PROVIDER_TYPE", "keycloak_external")

        settings = Settings()
        assert settings.identity_provider_type == "keycloak_external"

    def test_default_when_both_absent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """YAML and env var absent → defaults to hardcoded value."""
        monkeypatch.setenv("APP_YAML_PATH", str(tmp_path / "nonexistent.yaml"))
        monkeypatch.delenv("IDENTITY_PROVIDER_TYPE", raising=False)

        settings = Settings()
        assert settings.identity_provider_type == "unconfigured"

    def test_yaml_absent_returns_defaults_no_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("APP_YAML_PATH", str(tmp_path / "missing.yaml"))
        monkeypatch.delenv("IDENTITY_PROVIDER_TYPE", raising=False)

        settings = Settings()
        assert settings.identity_provider_type == "unconfigured"
        assert settings.identity_setup_complete is False
        assert settings.identity_realm == ""

    def test_yaml_null_value_treated_as_not_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bare YAML key (null value) does NOT override default — _SparseYamlSource drops nulls."""
        yaml_file = tmp_path / "test_app.yaml"
        yaml_file.write_text("identity_provider_type:\n", encoding="utf-8")

        monkeypatch.setenv("APP_YAML_PATH", str(yaml_file))
        monkeypatch.delenv("IDENTITY_PROVIDER_TYPE", raising=False)

        settings = Settings()
        assert settings.identity_provider_type == "unconfigured"

    def test_yaml_empty_string_value_treated_as_not_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        yaml_file = tmp_path / "test_app.yaml"
        yaml_file.write_text('identity_provider_type: ""\n', encoding="utf-8")

        monkeypatch.setenv("APP_YAML_PATH", str(yaml_file))
        monkeypatch.delenv("IDENTITY_PROVIDER_TYPE", raising=False)

        settings = Settings()
        assert settings.identity_provider_type == "unconfigured"

    def test_cache_clear_picks_up_new_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        yaml_file = tmp_path / "test_app.yaml"
        yaml_file.write_text("identity_provider_type: keycloak_bundled\n", encoding="utf-8")

        monkeypatch.setenv("APP_YAML_PATH", str(yaml_file))
        monkeypatch.delenv("IDENTITY_PROVIDER_TYPE", raising=False)

        first = Settings()
        assert first.identity_provider_type == "keycloak_bundled"

        yaml_file.write_text("identity_provider_type: keycloak_external\n", encoding="utf-8")

        get_settings.cache_clear()
        second = Settings()
        assert second.identity_provider_type == "keycloak_external"

    def test_yaml_setup_complete_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        yaml_file = tmp_path / "test_app.yaml"
        yaml_file.write_text(
            "identity_provider_type: keycloak_bundled\nidentity_setup_complete: true\n", encoding="utf-8"
        )

        monkeypatch.setenv("APP_YAML_PATH", str(yaml_file))
        monkeypatch.delenv("IDENTITY_PROVIDER_TYPE", raising=False)
        monkeypatch.delenv("IDENTITY_SETUP_COMPLETE", raising=False)

        settings = Settings()
        assert settings.identity_setup_complete is True
