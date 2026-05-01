"""Unit tests for Settings and _SparseYamlSource in app.core.config."""

import os
from pathlib import Path

import pytest

# Set required env vars before importing app modules
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """Clear the LRU cache before and after each test to avoid pollution."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestSparseYamlSource:
    """Tests for _SparseYamlSource behaviour via Settings loading."""

    def test_yaml_provider_type_loaded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """YAML file with provider_type: keycloak_bundled → settings.identity_provider_type == 'keycloak_bundled'."""
        yaml_file = tmp_path / "test_identity.yaml"
        yaml_file.write_text("provider_type: keycloak_bundled\n", encoding="utf-8")

        monkeypatch.setenv("IDENTITY_YAML_PATH", str(yaml_file))
        # Ensure env var does NOT override the YAML value for this test
        monkeypatch.delenv("IDENTITY_PROVIDER_TYPE", raising=False)

        settings = Settings()
        assert settings.identity_provider_type == "keycloak_bundled"

    def test_env_var_overrides_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env var IDENTITY_PROVIDER_TYPE=keycloak_external overrides YAML value."""
        yaml_file = tmp_path / "test_identity.yaml"
        yaml_file.write_text("provider_type: keycloak_bundled\n", encoding="utf-8")

        monkeypatch.setenv("IDENTITY_YAML_PATH", str(yaml_file))
        monkeypatch.setenv("IDENTITY_PROVIDER_TYPE", "keycloak_external")

        settings = Settings()
        assert settings.identity_provider_type == "keycloak_external"

    def test_default_when_both_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both YAML and env var absent → identity_provider_type defaults to 'unconfigured'."""
        # Point to a non-existent file so YAML is absent
        monkeypatch.setenv("IDENTITY_YAML_PATH", str(tmp_path / "nonexistent.yaml"))
        monkeypatch.delenv("IDENTITY_PROVIDER_TYPE", raising=False)

        settings = Settings()
        assert settings.identity_provider_type == "unconfigured"

    def test_yaml_absent_returns_defaults_no_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """YAML file absent → Settings loads without error and returns all defaults."""
        monkeypatch.setenv("IDENTITY_YAML_PATH", str(tmp_path / "missing.yaml"))
        monkeypatch.delenv("IDENTITY_PROVIDER_TYPE", raising=False)

        # Should not raise
        settings = Settings()
        assert settings.identity_provider_type == "unconfigured"
        assert settings.identity_setup_complete is False
        assert settings.identity_realm == ""

    def test_yaml_null_value_treated_as_not_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bare YAML key (null value) does NOT override the default — _SparseYamlSource drops nulls."""
        yaml_file = tmp_path / "test_identity.yaml"
        # Bare key without value parses as null in YAML
        yaml_file.write_text("provider_type:\n", encoding="utf-8")

        monkeypatch.setenv("IDENTITY_YAML_PATH", str(yaml_file))
        monkeypatch.delenv("IDENTITY_PROVIDER_TYPE", raising=False)

        settings = Settings()
        # Null value should be dropped, so default "unconfigured" is returned
        assert settings.identity_provider_type == "unconfigured"

    def test_yaml_empty_string_value_treated_as_not_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty string in YAML does NOT override the default — _SparseYamlSource drops empty strings."""
        yaml_file = tmp_path / "test_identity.yaml"
        yaml_file.write_text('provider_type: ""\n', encoding="utf-8")

        monkeypatch.setenv("IDENTITY_YAML_PATH", str(yaml_file))
        monkeypatch.delenv("IDENTITY_PROVIDER_TYPE", raising=False)

        settings = Settings()
        assert settings.identity_provider_type == "unconfigured"

    def test_cache_clear_picks_up_new_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After cache_clear(), a fresh Settings instance reads updated YAML values."""
        yaml_file = tmp_path / "test_identity.yaml"
        yaml_file.write_text("provider_type: keycloak_bundled\n", encoding="utf-8")

        monkeypatch.setenv("IDENTITY_YAML_PATH", str(yaml_file))
        monkeypatch.delenv("IDENTITY_PROVIDER_TYPE", raising=False)

        first = Settings()
        assert first.identity_provider_type == "keycloak_bundled"

        # Update YAML content
        yaml_file.write_text("provider_type: keycloak_external\n", encoding="utf-8")

        get_settings.cache_clear()
        second = Settings()
        assert second.identity_provider_type == "keycloak_external"

    def test_yaml_setup_complete_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """YAML setup_complete: true → settings.identity_setup_complete is True."""
        yaml_file = tmp_path / "test_identity.yaml"
        yaml_file.write_text(
            "provider_type: keycloak_bundled\nsetup_complete: true\n", encoding="utf-8"
        )

        monkeypatch.setenv("IDENTITY_YAML_PATH", str(yaml_file))
        monkeypatch.delenv("IDENTITY_PROVIDER_TYPE", raising=False)
        monkeypatch.delenv("IDENTITY_SETUP_COMPLETE", raising=False)

        settings = Settings()
        assert settings.identity_setup_complete is True
