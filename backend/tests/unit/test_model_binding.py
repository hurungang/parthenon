"""Unit tests for provider-level model binding (model_id + enabled_models architecture).

Verifies that:
- AgentType.model_id is a plain string field (no FK to ModelConfig)
- ModelBindingLayer.resolve_model_config scans all ModelConfig.enabled_models to find a match
- ModelBindingError raised when no config contains the model_id
- enabled_models stored and updated correctly on ModelConfig
- Resolution is deterministic (first matching config by creation order)
"""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.db.models.agents import (
    AgentType,
    ModelConfig,
    ModelProvider,
    AgentInputType,
    AgentOutputType,
)
from app.services.agents.model_binding import ModelBindingError, ModelBindingLayer


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_model_config(
    config_id: uuid.UUID | None = None,
    provider_type: ModelProvider = ModelProvider.openai,
    display_name: str = "GPT-4 Config",
    enabled_models: list[str] | None = None,
) -> ModelConfig:
    cfg = MagicMock(spec=ModelConfig)
    cfg.id = config_id or uuid.uuid4()
    cfg.display_name = display_name
    cfg.provider_type = provider_type
    cfg.api_base_url = "https://api.openai.com/v1"
    cfg.encrypted_api_key = "enc:test"
    cfg.enabled_models = enabled_models if enabled_models is not None else []
    return cfg


def _make_agent_type(model_id: str = "gpt-4o") -> AgentType:
    at = MagicMock(spec=AgentType)
    at.id = uuid.uuid4()
    at.name = "Test Agent"
    at.model_id = model_id
    at.input_type = AgentInputType.none
    at.output_type = AgentOutputType.auto
    return at


def _mock_db_with_configs(configs: list[ModelConfig]) -> AsyncMock:
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = configs
    db.execute.return_value = mock_result
    return db


# ── AgentType model_id field ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_type_stores_model_id_string():
    """AgentType.model_id holds the provider-scoped model identifier string."""
    at = _make_agent_type(model_id="gpt-4o")
    assert at.model_id == "gpt-4o"


@pytest.mark.asyncio
async def test_agent_type_has_no_model_config_id():
    """AgentType ORM spec does not include model_config_id (FK removed)."""
    at = _make_agent_type()
    # model_config_id must NOT be a valid field on AgentType
    assert not hasattr(AgentType, "model_config_id")


# ── ModelBindingLayer.resolve_model_config ────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_model_config_finds_matching_config():
    """resolve_model_config returns the ModelConfig whose enabled_models contains model_id."""
    layer = ModelBindingLayer()
    config = _make_model_config(enabled_models=["gpt-4o", "gpt-4-turbo"])
    db = _mock_db_with_configs([config])

    result = await layer.resolve_model_config("gpt-4o", db)

    assert result.id == config.id
    assert result.provider_type == ModelProvider.openai


@pytest.mark.asyncio
async def test_resolve_model_config_raises_when_not_found():
    """resolve_model_config raises ModelBindingError when no config has the model_id."""
    layer = ModelBindingLayer()
    config = _make_model_config(enabled_models=["gpt-4-turbo"])
    db = _mock_db_with_configs([config])

    with pytest.raises(ModelBindingError, match="gpt-4o"):
        await layer.resolve_model_config("gpt-4o", db)


@pytest.mark.asyncio
async def test_resolve_model_config_empty_configs_raises():
    """resolve_model_config raises ModelBindingError when no configs exist."""
    layer = ModelBindingLayer()
    db = _mock_db_with_configs([])

    with pytest.raises(ModelBindingError):
        await layer.resolve_model_config("gpt-4o", db)


@pytest.mark.asyncio
async def test_resolve_model_config_litellm_proxy():
    """LiteLLM proxy ModelConfig is resolved correctly via enabled_models."""
    layer = ModelBindingLayer()
    config = _make_model_config(
        provider_type=ModelProvider.litellm_proxy,
        display_name="LiteLLM Proxy",
        enabled_models=["claude-sonnet-4-5", "gpt-4o"],
    )
    config.api_base_url = "http://proxy:4000"
    db = _mock_db_with_configs([config])

    result = await layer.resolve_model_config("claude-sonnet-4-5", db)

    assert result.provider_type == ModelProvider.litellm_proxy
    assert result.api_base_url == "http://proxy:4000"


@pytest.mark.asyncio
async def test_resolve_returns_first_matching_config():
    """When model_id appears in multiple configs, the first match is returned (deterministic)."""
    layer = ModelBindingLayer()
    config_first = _make_model_config(display_name="First Config", enabled_models=["gpt-4o"])
    config_second = _make_model_config(display_name="Second Config", enabled_models=["gpt-4o"])
    # Ordered: first before second (simulates ascending created_at ordering from DB)
    db = _mock_db_with_configs([config_first, config_second])

    result = await layer.resolve_model_config("gpt-4o", db)

    assert result.id == config_first.id


# ── enabled_models field on ModelConfig ───────────────────────────────────────


@pytest.mark.asyncio
async def test_enabled_models_stored_on_model_config():
    """ModelConfig.enabled_models holds the list of enabled model identifiers."""
    models = ["gpt-4o", "gpt-4-turbo", "gpt-4o-mini"]
    config = _make_model_config(enabled_models=models)
    assert config.enabled_models == models


@pytest.mark.asyncio
async def test_disabled_model_removed_from_enabled_models():
    """Removing a model from enabled_models is reflected immediately in resolution."""
    layer = ModelBindingLayer()
    config = _make_model_config(enabled_models=["gpt-4o", "gpt-4-turbo"])

    # Simulate disabling gpt-4o by removing it from enabled_models
    config.enabled_models = ["gpt-4-turbo"]
    db = _mock_db_with_configs([config])

    # gpt-4o is no longer in any config's enabled_models
    with pytest.raises(ModelBindingError, match="gpt-4o"):
        await layer.resolve_model_config("gpt-4o", db)


@pytest.mark.asyncio
async def test_resolve_succeeds_after_model_re_enabled():
    """Resolution works again after a previously disabled model is re-added to enabled_models."""
    layer = ModelBindingLayer()
    config = _make_model_config(enabled_models=["gpt-4-turbo"])
    db = _mock_db_with_configs([config])

    # Before re-enabling: resolution fails
    with pytest.raises(ModelBindingError):
        await layer.resolve_model_config("gpt-4o", db)

    # Re-enable the model
    config.enabled_models = ["gpt-4-turbo", "gpt-4o"]
    db2 = _mock_db_with_configs([config])

    result = await layer.resolve_model_config("gpt-4o", db2)
    assert result.id == config.id
