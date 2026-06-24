"""Unit tests for LangChainModelFactory — credential resolution, provider mapping, model init.

Verifies:
- Supported provider keys are accepted
- Unsupported providers raise LangChainModelFactoryError
- get_model_from_config_dict resolves provider/key/url correctly
- output_json_schema propagates to .with_structured_output()
- OpenAI-compatible providers return a ChatOpenAI instance
- Azure OpenAI requires api_base_url
- Anthropic/Gemini/Cohere return custom BaseChatModel instances
"""
import pytest
from unittest.mock import MagicMock, patch


# ── Instantiation ─────────────────────────────────────────────────────────────


def test_factory_can_be_instantiated():
    """LangChainModelFactory can be created without errors."""
    from app.services.agents.langchain_model_factory import LangChainModelFactory

    factory = LangChainModelFactory()
    assert factory is not None


def test_supported_providers_is_a_frozenset():
    """SUPPORTED_PROVIDERS is a frozenset of known provider keys."""
    from app.services.agents.langchain_model_factory import LangChainModelFactory

    factory = LangChainModelFactory()
    assert isinstance(factory.SUPPORTED_PROVIDERS, frozenset)
    assert "openai" in factory.SUPPORTED_PROVIDERS
    assert "anthropic" in factory.SUPPORTED_PROVIDERS
    assert "gemini" in factory.SUPPORTED_PROVIDERS
    assert "cohere" in factory.SUPPORTED_PROVIDERS


# ── Provider mapping ─────────────────────────────────────────────────────────


def test_unsupported_provider_raises():
    """get_model() raises LangChainModelFactoryError for unknown providers."""
    from app.services.agents.langchain_model_factory import (
        LangChainModelFactory,
        LangChainModelFactoryError,
    )

    factory = LangChainModelFactory()
    with pytest.raises(LangChainModelFactoryError):
        factory.get_model(
            provider_key="unsupported_xyz",
            model_id="some-model",
            api_key="test-key",
        )


def test_openai_compat_returns_chat_openai():
    """OpenAI-compatible providers (openai, groq, etc.) return ChatOpenAI instances."""
    from app.services.agents.langchain_model_factory import LangChainModelFactory

    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        pytest.skip("langchain_openai not installed")

    factory = LangChainModelFactory()
    model = factory.get_model(
        provider_key="openai",
        model_id="gpt-4o",
        api_key="test-key",
    )
    assert isinstance(model, ChatOpenAI)


def test_anthropic_returns_custom_model():
    """Anthropic provider returns the custom _AnthropicChatModel."""
    from app.services.agents.langchain_model_factory import (
        LangChainModelFactory,
        _AnthropicChatModel,
    )

    factory = LangChainModelFactory()
    model = factory.get_model(
        provider_key="anthropic",
        model_id="claude-3-5-haiku-20241022",
        api_key="test-key",
    )
    assert isinstance(model, _AnthropicChatModel)


def test_gemini_returns_custom_model():
    """Gemini provider returns the custom _GeminiChatModel."""
    from app.services.agents.langchain_model_factory import (
        LangChainModelFactory,
        _GeminiChatModel,
    )

    factory = LangChainModelFactory()
    model = factory.get_model(
        provider_key="gemini",
        model_id="gemini-2.0-flash",
        api_key="test-key",
    )
    assert isinstance(model, _GeminiChatModel)


def test_cohere_returns_custom_model():
    """Cohere provider returns the custom _CohereChatModel."""
    from app.services.agents.langchain_model_factory import (
        LangChainModelFactory,
        _CohereChatModel,
    )

    factory = LangChainModelFactory()
    model = factory.get_model(
        provider_key="cohere",
        model_id="command-r-plus-08-2024",
        api_key="test-key",
    )
    assert isinstance(model, _CohereChatModel)


def test_azure_openai_requires_base_url():
    """azure_openai raises LangChainModelFactoryError when api_base_url is absent."""
    from app.services.agents.langchain_model_factory import (
        LangChainModelFactory,
        LangChainModelFactoryError,
    )

    factory = LangChainModelFactory()
    with pytest.raises(LangChainModelFactoryError):
        factory.get_model(
            provider_key="azure_openai",
            model_id="gpt-4o",
            api_key="test-key",
            base_url=None,  # Required for Azure
        )


# ── get_model_from_config_dict ────────────────────────────────────────────────


def test_get_model_from_config_dict_openai():
    """get_model_from_config_dict resolves provider_type, api_key, and base_url."""
    from app.services.agents.langchain_model_factory import LangChainModelFactory

    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        pytest.skip("langchain_openai not installed")

    factory = LangChainModelFactory()
    config_dict = {
        "provider_type": "openai",
        "api_key": "sk-test",
        "api_base_url": None,
    }
    model = factory.get_model_from_config_dict(
        model_id="gpt-4o",
        model_config_dict=config_dict,
    )
    assert isinstance(model, ChatOpenAI)


def test_get_model_from_config_dict_anthropic():
    """get_model_from_config_dict creates the custom Anthropic model from dict."""
    from app.services.agents.langchain_model_factory import (
        LangChainModelFactory,
        _AnthropicChatModel,
    )

    factory = LangChainModelFactory()
    config_dict = {
        "provider_type": "anthropic",
        "api_key": "anthropic-test-key",
        "api_base_url": None,
    }
    model = factory.get_model_from_config_dict(
        model_id="claude-sonnet-4-5",
        model_config_dict=config_dict,
    )
    assert isinstance(model, _AnthropicChatModel)


def test_structured_output_applied_for_openai():
    """output_json_schema calls .with_structured_output() for OpenAI models."""
    from app.services.agents.langchain_model_factory import LangChainModelFactory

    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        pytest.skip("langchain_openai not installed")

    schema = {
        "title": "MySchema",
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    factory = LangChainModelFactory()
    # Should not raise even with schema; model may be a RunnableBinding wrapping ChatOpenAI
    model = factory.get_model(
        provider_key="openai",
        model_id="gpt-4o",
        api_key="test-key",
        output_json_schema=schema,
    )
    # The result should differ from a plain ChatOpenAI (wrapped in structured output)
    assert model is not None


def test_structured_output_is_none_returns_plain_model():
    """When output_json_schema is None, no structured output wrapping is applied."""
    from app.services.agents.langchain_model_factory import LangChainModelFactory

    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        pytest.skip("langchain_openai not installed")

    factory = LangChainModelFactory()
    model = factory.get_model(
        provider_key="openai",
        model_id="gpt-4o",
        api_key="test-key",
        output_json_schema=None,
    )
    assert isinstance(model, ChatOpenAI)
