"""Unit tests for the conversational turn-resume settings in app.core.config.

Covers the four durable-paused-turn knobs introduced for the resumable agent
turn persistence change:

* ``conversation_turn_resume_ttl_seconds`` (answerable window, default 900)
* ``conversation_turn_claim_ttl_seconds`` (claim lease, default 45)
* ``conversation_turn_checkpoint_max_bytes`` (payload cap, default 2 MB)
* ``conversation_turn_checkpoint_purge_after_seconds`` (purge horizon, 3600)
"""
import os

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.config import Settings, get_settings

# field name → env var name
_ENV_VARS: dict[str, str] = {
    "conversation_turn_resume_ttl_seconds": "CONVERSATION_TURN_RESUME_TTL_SECONDS",
    "conversation_turn_claim_ttl_seconds": "CONVERSATION_TURN_CLAIM_TTL_SECONDS",
    "conversation_turn_checkpoint_max_bytes": (
        "CONVERSATION_TURN_CHECKPOINT_MAX_BYTES"
    ),
    "conversation_turn_checkpoint_purge_after_seconds": (
        "CONVERSATION_TURN_CHECKPOINT_PURGE_AFTER_SECONDS"
    ),
}

_DEFAULTS: dict[str, int] = {
    "conversation_turn_resume_ttl_seconds": 900,
    "conversation_turn_claim_ttl_seconds": 45,
    "conversation_turn_checkpoint_max_bytes": 2 * 1024 * 1024,
    "conversation_turn_checkpoint_purge_after_seconds": 3600,
}

# Must stay in sync with _CONVERSATION_TURN_SETTING_MINIMUMS in app.core.config.
_MINIMUMS: dict[str, int] = {
    "conversation_turn_resume_ttl_seconds": 30,
    "conversation_turn_claim_ttl_seconds": 1,
    "conversation_turn_checkpoint_max_bytes": 1024,
    "conversation_turn_checkpoint_purge_after_seconds": 60,
}

# Values safely above every minimum, used for env-resolution assertions.
_ENV_VALUES: dict[str, int] = {
    "conversation_turn_resume_ttl_seconds": 1800,
    "conversation_turn_claim_ttl_seconds": 90,
    "conversation_turn_checkpoint_max_bytes": 4 * 1024 * 1024,
    "conversation_turn_checkpoint_purge_after_seconds": 7200,
}


@pytest.fixture(autouse=True)
def isolated_settings(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ignore app.yaml / home .env noise and clear the settings cache."""
    monkeypatch.setenv("APP_YAML_PATH", str(tmp_path / "missing.yaml"))
    for env_name in _ENV_VARS.values():
        monkeypatch.delenv(env_name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestConversationTurnSettingDefaults:
    def test_documented_defaults(self) -> None:
        settings = Settings()
        for field_name, expected in _DEFAULTS.items():
            assert getattr(settings, field_name) == expected, field_name

    def test_resume_ttl_default_is_fifteen_minutes(self) -> None:
        assert Settings().conversation_turn_resume_ttl_seconds == 900


class TestConversationTurnSettingEnvResolution:
    @pytest.mark.parametrize("field_name", sorted(_ENV_VARS))
    def test_env_var_sets_value(
        self, field_name: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_ENV_VARS[field_name], str(_ENV_VALUES[field_name]))

        assert getattr(Settings(), field_name) == _ENV_VALUES[field_name]

    def test_all_four_resolve_together_through_get_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for field_name, env_name in _ENV_VARS.items():
            monkeypatch.setenv(env_name, str(_ENV_VALUES[field_name]))

        settings = get_settings()

        for field_name, expected in _ENV_VALUES.items():
            assert getattr(settings, field_name) == expected, field_name


class TestConversationTurnSettingClamping:
    @pytest.mark.parametrize("field_name", sorted(_ENV_VARS))
    @pytest.mark.parametrize("raw_value", ["0", "-1", "-3600"])
    def test_non_positive_env_value_clamps_to_minimum(
        self,
        field_name: str,
        raw_value: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(_ENV_VARS[field_name], raw_value)

        assert getattr(Settings(), field_name) == _MINIMUMS[field_name]

    @pytest.mark.parametrize("field_name", sorted(_ENV_VARS))
    def test_just_below_minimum_env_value_clamps_up(
        self, field_name: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        minimum = _MINIMUMS[field_name]
        monkeypatch.setenv(_ENV_VARS[field_name], str(minimum - 1))

        assert getattr(Settings(), field_name) == minimum

    @pytest.mark.parametrize("field_name", sorted(_ENV_VARS))
    def test_minimum_and_above_are_preserved(
        self, field_name: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        minimum = _MINIMUMS[field_name]
        for raw_value in (minimum, minimum + 1):
            monkeypatch.setenv(_ENV_VARS[field_name], str(raw_value))
            assert getattr(Settings(), field_name) == raw_value

    @pytest.mark.parametrize("field_name", sorted(_ENV_VARS))
    def test_constructor_values_are_clamped_too(self, field_name: str) -> None:
        settings = Settings(**{field_name: 0})

        assert getattr(settings, field_name) == _MINIMUMS[field_name]
