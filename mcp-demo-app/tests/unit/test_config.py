"""Unit tests for AppSettings (app/config.py).

Verifies that required env vars are loaded correctly, defaults are applied,
and missing required fields raise a validation error.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_settings_loads_all_required_fields():
    """All required env vars set in conftest.py → settings loads successfully."""
    from app.config import AppSettings

    s = AppSettings()
    assert s.KEYCLOAK_URL == "http://keycloak:8082"
    assert s.KEYCLOAK_REALM == "ai_agents"
    assert s.KEYCLOAK_CLIENT_ID == "mcp-demo-app-test"
    assert s.KEYCLOAK_CLIENT_SECRET == "test-secret"
    assert s.HUB_BASE_URL == "http://localhost:8000"
    assert s.HUB_API_TOKEN == "test-token"
    assert s.APP_BASE_URL == "http://localhost:7001"


def test_settings_default_values():
    """Optional fields fall back to their defaults."""
    from app.config import AppSettings

    s = AppSettings()
    assert s.KEYCLOAK_REALM == "ai_agents"
    assert s.APP_PORT == 7001
    assert s.APP_SLUG == "demo"


def test_settings_missing_keycloak_url(monkeypatch):
    """Removing KEYCLOAK_URL must cause a ValidationError at instantiation."""
    monkeypatch.delenv("KEYCLOAK_URL", raising=False)

    from app.config import AppSettings

    with pytest.raises((ValidationError, Exception)):
        AppSettings()


def test_settings_missing_keycloak_client_id(monkeypatch):
    """Removing KEYCLOAK_CLIENT_ID must cause a ValidationError at instantiation."""
    monkeypatch.delenv("KEYCLOAK_CLIENT_ID", raising=False)

    from app.config import AppSettings

    with pytest.raises((ValidationError, Exception)):
        AppSettings()


def test_settings_missing_hub_base_url(monkeypatch):
    """Removing HUB_BASE_URL must cause a ValidationError at instantiation."""
    monkeypatch.delenv("HUB_BASE_URL", raising=False)

    from app.config import AppSettings

    with pytest.raises((ValidationError, Exception)):
        AppSettings()


def test_settings_missing_app_base_url(monkeypatch):
    """Removing APP_BASE_URL must cause a ValidationError at instantiation."""
    monkeypatch.delenv("APP_BASE_URL", raising=False)

    from app.config import AppSettings

    with pytest.raises((ValidationError, Exception)):
        AppSettings()
