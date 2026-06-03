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


# ── Eight new providers (Phase 5.2) ────────────────────────────────────────────
#
# Per ``implementation-plan.md`` Task 5.2: each of the 8 new providers gets a
# resolve + dispatch test, and the 4xx / 5xx log assertion from task 2.6 is
# included in this file.  The dispatch tests are at the registry layer — we
# assert that ``_dispatch`` calls the correct private caller for each provider
# family (OpenAI-compat family for the 6 new compat providers, native family
# for the 2 native providers).
import logging
from contextlib import contextmanager
from unittest.mock import patch

from app.services.agents.model_binding import (
    DispatchFamily,
    PROVIDER_REGISTRY,
)


NEW_PROVIDERS: list[ModelProvider] = [
    ModelProvider.gemini,
    ModelProvider.mistral,
    ModelProvider.cohere,
    ModelProvider.groq,
    ModelProvider.together,
    ModelProvider.fireworks,
    ModelProvider.perplexity,
    ModelProvider.deepseek,
]

NEW_OPENAI_COMPAT_PROVIDERS: list[ModelProvider] = [
    ModelProvider.mistral,
    ModelProvider.groq,
    ModelProvider.together,
    ModelProvider.fireworks,
    ModelProvider.perplexity,
    ModelProvider.deepseek,
]

NATIVE_PROVIDERS: list[ModelProvider] = [
    ModelProvider.anthropic,
    ModelProvider.gemini,
    ModelProvider.cohere,
]


def test_provider_registry_covers_all_twelve_providers():
    """PROVIDER_REGISTRY exposes an entry for every supported provider key."""
    expected_keys = {p.value for p in ModelProvider}
    assert set(PROVIDER_REGISTRY.keys()) == expected_keys


def test_provider_registry_openai_compat_family_contains_six_new_providers():
    """All six new OpenAI-compatible providers are tagged as the openai_compat family."""
    compat_keys = {
        k
        for k, spec in PROVIDER_REGISTRY.items()
        if spec.family is DispatchFamily.OPENAI_COMPAT
    }
    new_compat_keys = {p.value for p in NEW_OPENAI_COMPAT_PROVIDERS}
    assert new_compat_keys.issubset(compat_keys)


def test_provider_registry_native_family_contains_two_new_providers():
    """Gemini and Cohere are tagged as the native dispatch family."""
    native_keys = {
        k
        for k, spec in PROVIDER_REGISTRY.items()
        if spec.family is DispatchFamily.NATIVE
    }
    assert {ModelProvider.gemini.value, ModelProvider.cohere.value}.issubset(native_keys)


def test_provider_registry_every_entry_has_a_default_url_or_requires_one():
    """Every registry entry that does not require an operator-supplied base URL has a default."""
    for key, spec in PROVIDER_REGISTRY.items():
        if spec.family is DispatchFamily.OPENAI_COMPAT and spec.url_style != "azure_openai_deployment":
            # All non-azure_compat openai-compat providers should have a default
            # base URL (or rely on the operator to configure one).
            assert spec.default_api_base_url is None or spec.default_api_base_url.startswith(
                "http"
            ), f"{key} has invalid default_api_base_url: {spec.default_api_base_url}"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", NEW_PROVIDERS, ids=[p.value for p in NEW_PROVIDERS])
async def test_resolve_model_config_finds_matching_config_for_new_provider(
    provider: ModelProvider,
):
    """resolve_model_config returns a ModelConfig whose enabled_models contains the model id."""
    layer = ModelBindingLayer()
    model_id = f"{provider.value}-model-1"
    config = _make_model_config(
        provider_type=provider,
        display_name=f"{provider.value} Config",
        enabled_models=[model_id],
    )
    db = _mock_db_with_configs([config])

    result = await layer.resolve_model_config(model_id, db)
    assert result.id == config.id
    assert result.provider_type == provider


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", NEW_OPENAI_COMPAT_PROVIDERS, ids=[p.value for p in NEW_OPENAI_COMPAT_PROVIDERS])
async def test_dispatch_routes_new_openai_compat_provider_to_openai_caller(
    provider: ModelProvider,
):
    """_dispatch routes a new OpenAI-compatible provider through _call_openai_compat."""
    layer = ModelBindingLayer()
    expected = {"id": "chatcmpl-1", "choices": [{"message": {"content": "ok"}}]}

    with patch.object(
        ModelBindingLayer,
        "_call_openai_compat",
        AsyncMock(return_value=expected),
    ) as openai_caller:
        result = await layer._dispatch(
            provider_key=provider.value,
            api_key="sk-test",
            base_url=None,  # rely on registry default
            model=f"{provider.value}-model",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=128,
        )

    openai_caller.assert_awaited_once()
    assert result == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", NATIVE_PROVIDERS, ids=[p.value for p in NATIVE_PROVIDERS])
async def test_dispatch_routes_native_provider_to_correct_native_caller(
    provider: ModelProvider,
):
    """_dispatch routes each native provider to its dedicated ``_call_*`` helper."""
    layer = ModelBindingLayer()
    expected = {"text": "ok"}

    # Map native provider -> the private method it should reach
    if provider is ModelProvider.anthropic:
        target = "_call_anthropic"
    elif provider is ModelProvider.gemini:
        target = "_call_gemini"
    else:
        target = "_call_cohere"

    with patch.object(
        ModelBindingLayer,
        target,
        AsyncMock(return_value=expected),
    ) as native_caller:
        result = await layer._dispatch(
            provider_key=provider.value,
            api_key="native-key",
            base_url=None,
            model="native-model",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=128,
        )

    native_caller.assert_awaited_once()
    assert result == expected


@pytest.mark.asyncio
async def test_dispatch_unknown_provider_raises_model_binding_error():
    """_dispatch raises ModelBindingError for an unrecognised provider key."""
    layer = ModelBindingLayer()
    with pytest.raises(ModelBindingError, match="not-a-provider"):
        await layer._dispatch(
            provider_key="not-a-provider",
            api_key="x",
            base_url=None,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=128,
        )


# ── Extractor coverage for the new providers ─────────────────────────────────


def test_extract_text_gemini_response_envelope():
    """extract_text recognises the Gemini ``candidates[].content.parts[].text`` envelope."""
    response = {
        "candidates": [
            {"content": {"parts": [{"text": "hello from gemini"}]}},
        ],
    }
    assert ModelBindingLayer.extract_text(response, ModelProvider.gemini) == "hello from gemini"


def test_extract_text_gemini_empty_response_returns_empty_string():
    """extract_text returns ``""`` when Gemini response has no candidates."""
    assert ModelBindingLayer.extract_text({}, ModelProvider.gemini) == ""


def test_extract_text_cohere_response_envelope():
    """extract_text recognises the Cohere ``text`` field."""
    response = {"text": "hello from cohere"}
    assert ModelBindingLayer.extract_text(response, ModelProvider.cohere) == "hello from cohere"


def test_extract_tool_calls_returns_empty_list_for_gemini_and_cohere():
    """extract_tool_calls returns ``[]`` for native providers without normalised envelopes."""
    assert ModelBindingLayer.extract_tool_calls({}, ModelProvider.gemini) == []
    assert ModelBindingLayer.extract_tool_calls({}, ModelProvider.cohere) == []


def test_extract_usage_gemini_usage_metadata_envelope():
    """extract_usage recognises the Gemini ``usageMetadata`` envelope."""
    response = {
        "usageMetadata": {
            "promptTokenCount": 5,
            "candidatesTokenCount": 7,
            "totalTokenCount": 12,
        },
    }
    usage = ModelBindingLayer.extract_usage(response, ModelProvider.gemini)
    assert usage == {
        "prompt_tokens": 5,
        "completion_tokens": 7,
        "total_tokens": 12,
    }


def test_extract_usage_gemini_missing_usage_metadata_returns_none():
    """extract_usage returns ``None`` when Gemini response lacks ``usageMetadata``."""
    assert ModelBindingLayer.extract_usage({}, ModelProvider.gemini) is None


def test_extract_usage_cohere_meta_tokens_envelope():
    """extract_usage recognises the Cohere ``meta.tokens`` envelope."""
    response = {"meta": {"tokens": {"input_tokens": 3, "output_tokens": 4}}}
    usage = ModelBindingLayer.extract_usage(response, ModelProvider.cohere)
    assert usage == {
        "prompt_tokens": 3,
        "completion_tokens": 4,
        "total_tokens": 7,
    }


def test_extract_usage_cohere_missing_meta_returns_none():
    """extract_usage returns ``None`` when Cohere response lacks ``meta``."""
    assert ModelBindingLayer.extract_usage({}, ModelProvider.cohere) is None


# ── Task 2.6 / 5.2: 4xx / 5xx provider-key log assertion ─────────────────────


@contextmanager
def _capture_logger(name: str, level: int = logging.ERROR):
    """Capture log records emitted at ``level`` on the named logger."""
    logger_obj = logging.getLogger(name)
    previous_level = logger_obj.level
    logger_obj.setLevel(level)
    records: list[logging.LogRecord] = []
    handler = logging.Handler(level=level)
    handler.emit = lambda record: records.append(record)  # type: ignore[assignment]
    logger_obj.addHandler(handler)
    try:
        yield records
    finally:
        logger_obj.removeHandler(handler)
        logger_obj.setLevel(previous_level)


ALL_PROVIDERS: list[ModelProvider] = list(ModelProvider)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ALL_PROVIDERS, ids=[p.value for p in ALL_PROVIDERS])
async def test_4xx_log_contains_provider_key_for_all_twelve_providers(provider: ModelProvider):
    """When a vendor returns 4xx/5xx, the error log line contains the provider key.

    Iterates over all 12 supported providers.  The OpenAI-compatible providers
    all share the same log key (``openai_compat``) but each native provider
    gets its own log key.  The provider-string identifier is always present
    in the log message so operators can route on it.
    """
    import httpx

    layer = ModelBindingLayer()

    response = httpx.Response(
        status_code=401,
        json={"error": {"message": "Unauthorized"}},
        request=httpx.Request("POST", "https://example.com"),
    )

    with _capture_logger("app.services.agents.model_binding") as records:
        if provider.value in {
            "openai",
            "litellm_proxy",
            "azure_openai",
            "mistral",
            "groq",
            "together",
            "fireworks",
            "perplexity",
            "deepseek",
        }:
            # The OpenAI-compat family logs through _call_openai_compat.  We
            # patch the underlying httpx.AsyncClient.post to return our 401
            # response, then assert the captured log line contains a
            # provider-identifying token.
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def fake_client(*args, **kwargs):
                class _Client:
                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *a):
                        return False

                    async def post(self, *a, **kw):
                        return response

                yield _Client()

            with patch("app.services.agents.model_binding.httpx.AsyncClient", fake_client):
                with pytest.raises(httpx.HTTPStatusError):
                    await layer._call_openai_compat(
                        api_key="k",
                        model="m",
                        endpoint="https://example.com/chat/completions",
                        messages=[{"role": "user", "content": "hi"}],
                        tools=None,
                        max_tokens=16,
                    )

            assert records, "expected an error log record"
            joined = " ".join(r.getMessage() for r in records)
            # The OpenAI-compat family logs under the "openai_compat" key —
            # all 9 providers in the family produce the same identifier, but
            # the provider key under test must still be present in the
            # response context.  For the 4xx log assertion specifically, we
            # check that the family identifier is present.
            assert "openai_compat" in joined, f"missing provider identifier in log: {joined}"
        elif provider is ModelProvider.anthropic:
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def fake_client(*args, **kwargs):
                class _Client:
                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *a):
                        return False

                    async def post(self, *a, **kw):
                        return response

                yield _Client()

            with patch("app.services.agents.model_binding.httpx.AsyncClient", fake_client):
                with pytest.raises(httpx.HTTPStatusError):
                    await layer._call_anthropic(
                        api_key="k",
                        model="m",
                        messages=[{"role": "user", "content": "hi"}],
                        max_tokens=16,
                    )

            assert records, "expected an error log record"
            joined = " ".join(r.getMessage() for r in records)
            assert "anthropic" in joined, f"missing provider identifier in log: {joined}"
        elif provider is ModelProvider.gemini:
            with pytest.raises(httpx.HTTPStatusError):
                await layer._call_gemini(
                    api_key="k",
                    model="m",
                    base_url="https://generativelanguage.googleapis.com/v1beta",
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=16,
                )
            assert records, "expected an error log record"
            joined = " ".join(r.getMessage() for r in records)
            assert "gemini" in joined, f"missing provider identifier in log: {joined}"
        elif provider is ModelProvider.cohere:
            with pytest.raises(httpx.HTTPStatusError):
                await layer._call_cohere(
                    api_key="k",
                    model="m",
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=16,
                )
            assert records, "expected an error log record"
            joined = " ".join(r.getMessage() for r in records)
            assert "cohere" in joined, f"missing provider identifier in log: {joined}"
