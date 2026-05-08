"""Unit tests for ModelConfigService — CRUD with AES-256 credential encryption."""
import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.agents.model_config_service import (
    ModelConfigService,
    ModelConfigNotFoundError,
    ModelConfigConflictError,
)
from app.db.models.agents import ModelConfig, ModelProvider


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_config(
    config_id: uuid.UUID | None = None,
    display_name: str = "Test Config",
    provider_type: ModelProvider = ModelProvider.openai,
    api_base_url: str | None = None,
    encrypted_api_key: str | None = "enc:test-key",
    enabled_models: list[str] | None = None,
) -> ModelConfig:
    cfg = MagicMock(spec=ModelConfig)
    cfg.id = config_id or uuid.uuid4()
    cfg.display_name = display_name
    cfg.provider_type = provider_type
    cfg.api_base_url = api_base_url
    cfg.encrypted_api_key = encrypted_api_key
    cfg.enabled_models = enabled_models if enabled_models is not None else []
    return cfg


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.get = AsyncMock()
    db.execute = AsyncMock()
    return db


def _mock_vault(encrypted: str = "enc:test-key") -> MagicMock:
    vault = MagicMock()
    vault.encrypt = MagicMock(return_value=encrypted)
    vault.decrypt = MagicMock(return_value=json.dumps({"api_key": "raw-key"}))
    return vault


# ── Create ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_model_config_openai_encrypts_api_key():
    """create_model_config encrypts the api_key before storing it."""
    service = ModelConfigService()
    db = _mock_db()
    vault = _mock_vault("enc:openai-key")
    config = _make_config(encrypted_api_key="enc:openai-key")

    async def flush():
        pass

    db.flush.side_effect = flush

    async def refresh(obj, attrs=None):
        pass

    db.refresh.side_effect = refresh

    with (
        patch("app.services.agents.model_config_service.ModelConfig", return_value=config),
        patch("app.services.agents.model_config_service.get_vault", return_value=vault),
    ):
        result = await service.create_model_config(
            display_name="GPT-4 Config",
            provider_type=ModelProvider.openai,
            api_base_url="https://api.openai.com/v1",
            api_key="sk-rawkey",
            enabled_models=[],
            db=db,
        )

    vault.encrypt.assert_called_once()
    call_arg = vault.encrypt.call_args[0][0]
    assert "sk-rawkey" in call_arg
    assert result.id == config.id


@pytest.mark.asyncio
async def test_create_model_config_no_api_key_skips_encryption():
    """create_model_config with no api_key does not call the vault."""
    service = ModelConfigService()
    db = _mock_db()
    vault = _mock_vault()
    config = _make_config(encrypted_api_key=None)

    async def refresh(obj, attrs=None):
        pass

    db.refresh.side_effect = refresh

    with (
        patch("app.services.agents.model_config_service.ModelConfig", return_value=config),
        patch("app.services.agents.model_config_service.get_vault", return_value=vault),
    ):
        await service.create_model_config(
            display_name="LiteLLM Proxy",
            provider_type=ModelProvider.litellm_proxy,
            api_base_url="http://proxy:4000",
            api_key=None,
            enabled_models=[],
            db=db,
        )

    vault.encrypt.assert_not_called()


@pytest.mark.asyncio
async def test_create_model_config_litellm_proxy_optional_key():
    """create_model_config with litellm_proxy and optional api_key both succeed."""
    service = ModelConfigService()
    db = _mock_db()
    vault = _mock_vault("enc:proxy-key")
    config = _make_config(provider_type=ModelProvider.litellm_proxy)

    async def refresh(obj, attrs=None):
        pass

    db.refresh.side_effect = refresh

    with (
        patch("app.services.agents.model_config_service.ModelConfig", return_value=config),
        patch("app.services.agents.model_config_service.get_vault", return_value=vault),
    ):
        result = await service.create_model_config(
            display_name="LiteLLM Proxy with Key",
            provider_type=ModelProvider.litellm_proxy,
            api_base_url="http://proxy:4000",
            api_key="proxy-api-key",
            enabled_models=[],
            db=db,
        )

    assert result.id == config.id
    vault.encrypt.assert_called_once()


# ── Read ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_model_config_returns_record():
    """get_model_config returns the matching ModelConfig."""
    service = ModelConfigService()
    db = _mock_db()
    config_id = uuid.uuid4()
    config = _make_config(config_id=config_id)
    db.get.return_value = config

    result = await service.get_model_config(config_id, db)

    assert result.id == config_id


@pytest.mark.asyncio
async def test_get_model_config_raises_not_found():
    """get_model_config raises ModelConfigNotFoundError when not found."""
    service = ModelConfigService()
    db = _mock_db()
    db.get.return_value = None

    with pytest.raises(ModelConfigNotFoundError):
        await service.get_model_config(uuid.uuid4(), db)


@pytest.mark.asyncio
async def test_list_model_configs_returns_all():
    """list_model_configs returns all records from the DB."""
    service = ModelConfigService()
    db = _mock_db()
    configs = [_make_config(), _make_config()]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = configs
    db.execute.return_value = mock_result

    result = await service.list_model_configs(db)
    assert len(result) == 2


# ── Update ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_model_config_re_encrypts_new_api_key():
    """update_model_config re-encrypts credentials when a new api_key is provided."""
    service = ModelConfigService()
    db = _mock_db()
    vault = _mock_vault("enc:new-key")
    config = _make_config()
    db.get.return_value = config

    async def refresh(obj, attrs=None):
        pass

    db.refresh.side_effect = refresh

    with patch("app.services.agents.model_config_service.get_vault", return_value=vault):
        await service.update_model_config(
            config.id,
            display_name=None,
            provider_type=None,
            api_base_url=None,
            api_key="new-raw-key",
            enabled_models=None,
            db=db,
        )

    vault.encrypt.assert_called_once()
    assert config.encrypted_api_key == "enc:new-key"


@pytest.mark.asyncio
async def test_update_model_config_no_new_key_skips_encryption():
    """update_model_config without a new api_key does not re-encrypt."""
    service = ModelConfigService()
    db = _mock_db()
    vault = _mock_vault()
    config = _make_config(display_name="Old Name")
    db.get.return_value = config

    async def refresh(obj, attrs=None):
        pass

    db.refresh.side_effect = refresh

    with patch("app.services.agents.model_config_service.get_vault", return_value=vault):
        await service.update_model_config(
            config.id,
            display_name="New Name",
            provider_type=None,
            api_base_url=None,
            api_key=None,
            enabled_models=None,
            db=db,
        )

    vault.encrypt.assert_not_called()
    assert config.display_name == "New Name"


# ── Delete ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_model_config_succeeds_when_not_referenced():
    """delete_model_config succeeds when enabled_models has entries but no AgentType uses them."""
    service = ModelConfigService()
    db = _mock_db()
    config = _make_config(enabled_models=["gpt-4o"])
    db.get.return_value = config

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # no AgentType references this model
    db.execute.return_value = mock_result

    await service.delete_model_config(config.id, db)
    db.delete.assert_called_once_with(config)


@pytest.mark.asyncio
async def test_delete_model_config_raises_409_when_referenced():
    """delete_model_config raises ModelConfigConflictError when an AgentType.model_id is in enabled_models."""
    service = ModelConfigService()
    db = _mock_db()
    config = _make_config(enabled_models=["gpt-4o"])  # non-empty triggers the guard
    db.get.return_value = config

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = MagicMock()  # found a referencing AgentType
    db.execute.return_value = mock_result

    with pytest.raises(ModelConfigConflictError):
        await service.delete_model_config(config.id, db)


# ── Available Models (get_available_models / list_models_for_config) ───────────


@pytest.mark.asyncio
async def test_list_models_for_anthropic_returns_static_list():
    """Anthropic provider returns a static known-model list (no API call)."""
    service = ModelConfigService()
    db = _mock_db()
    config = _make_config(provider_type=ModelProvider.anthropic)
    db.get.return_value = config

    vault = _mock_vault()
    with patch("app.services.agents.model_config_service.get_vault", return_value=vault):
        models = await service.list_models_for_config(config.id, db)

    assert len(models) > 0
    # Anthropic models should include claude variants
    assert any("claude" in m.lower() for m in models)


# ── enabled_models ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_model_config_stores_enabled_models():
    """create_model_config persists the enabled_models list on the record."""
    service = ModelConfigService()
    db = _mock_db()
    vault = _mock_vault()
    models = ["gpt-4o", "gpt-4-turbo"]
    config = _make_config(enabled_models=models)

    async def refresh(obj, attrs=None):
        pass

    db.refresh.side_effect = refresh

    with (
        patch("app.services.agents.model_config_service.ModelConfig", return_value=config),
        patch("app.services.agents.model_config_service.get_vault", return_value=vault),
    ):
        result = await service.create_model_config(
            display_name="Models Config",
            provider_type=ModelProvider.openai,
            api_base_url=None,
            api_key="sk-key",
            enabled_models=models,
            db=db,
        )

    assert result.enabled_models == models


@pytest.mark.asyncio
async def test_update_model_config_updates_enabled_models():
    """update_model_config replaces enabled_models when provided."""
    service = ModelConfigService()
    db = _mock_db()
    vault = _mock_vault()
    config = _make_config(enabled_models=["gpt-4o"])
    db.get.return_value = config

    async def refresh(obj, attrs=None):
        pass

    db.refresh.side_effect = refresh

    new_models = ["gpt-4o", "gpt-4-turbo", "gpt-4o-mini"]
    with patch("app.services.agents.model_config_service.get_vault", return_value=vault):
        await service.update_model_config(
            config.id,
            display_name=None,
            provider_type=None,
            api_base_url=None,
            api_key=None,
            enabled_models=new_models,
            db=db,
        )

    assert config.enabled_models == new_models


@pytest.mark.asyncio
async def test_fetch_available_models_returns_enabled_list_when_non_empty():
    """fetch_available_models returns enabled_models list directly (no live API call)."""
    service = ModelConfigService()
    db = _mock_db()
    config = _make_config(enabled_models=["gpt-4o", "gpt-4-turbo"])
    db.get.return_value = config

    result = await service.fetch_available_models(config.id, db)

    # Returns the enabled_models list — no provider API call needed
    assert result == ["gpt-4o", "gpt-4-turbo"]


@pytest.mark.asyncio
async def test_fetch_available_models_falls_back_to_list_models_when_empty():
    """fetch_available_models calls list_models_for_config when enabled_models is empty."""
    service = ModelConfigService()
    db = _mock_db()
    config = _make_config(enabled_models=[], provider_type=ModelProvider.anthropic)
    db.get.return_value = config

    vault = _mock_vault()
    with patch("app.services.agents.model_config_service.get_vault", return_value=vault):
        result = await service.fetch_available_models(config.id, db)

    # Falls back to live listing — anthropic returns a static list
    assert isinstance(result, list)
    assert len(result) > 0


# ── Available Models (get_available_models / list_models_for_config) ───────────


@pytest.mark.asyncio
async def test_list_models_for_openai_returns_structured_error_on_failure():
    """list_models_for_config returns a clear structured list (not raises 500) on provider failure."""
    service = ModelConfigService()
    db = _mock_db()
    config = _make_config(provider_type=ModelProvider.openai, api_base_url="http://bad-host")
    db.get.return_value = config

    vault = _mock_vault()

    with (
        patch("app.services.agents.model_config_service.get_vault", return_value=vault),
        patch(
            "app.services.agents.model_config_service.ModelConfigService._list_openai_models",
            side_effect=Exception("connection refused"),
        ),
    ):
        result = await service.list_models_for_config(config.id, db)

    # Must not raise; returns an empty list or error-indicator list
    assert isinstance(result, list)
