"""LangChain Model Factory — creates LangChain ChatModel instances for all providers.

Replaces ModelBindingLayer._dispatch() and the PROVIDER_REGISTRY facade.
Supports all 12 providers via native LangChain provider packages:

- OpenAI-compatible (9): ChatOpenAI with provider-specific base_url
- Azure OpenAI: AzureChatOpenAI
- Anthropic: ChatAnthropic (langchain-anthropic)
- Gemini: ChatGoogleGenerativeAI (langchain-google-genai)
- Cohere: ChatCohere (langchain-cohere)

All native providers support bind_tools(), with_structured_output(), and async
streaming out of the box.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

# Default API base URLs per provider
_PROVIDER_DEFAULTS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "litellm_proxy": "",  # operator-supplied
    "mistral": "https://api.mistral.ai/v1",
    "groq": "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "perplexity": "https://api.perplexity.ai",
    "deepseek": "https://api.deepseek.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "cohere": "https://api.cohere.com/v1",
}

# OpenAI-compatible provider keys (use ChatOpenAI)
_OPENAI_COMPAT_PROVIDERS: frozenset[str] = frozenset({
    "openai",
    "litellm_proxy",
    "mistral",
    "groq",
    "together",
    "fireworks",
    "perplexity",
    "deepseek",
})


class LangChainModelFactoryError(Exception):
    """Raised when LangChainModelFactory cannot create a model."""


class LangChainModelFactory:
    """Factory that creates LangChain ChatModel instances from provider configuration.

    Replaces ModelBindingLayer._dispatch() for all 12 providers.

    Usage:
        factory = LangChainModelFactory()
        llm = factory.get_model("openai", "gpt-4o", api_key="sk-...", base_url=None)
        llm = factory.get_model_from_config_dict("gpt-4o", model_config_dict)
    """

    # All 12 supported provider keys
    SUPPORTED_PROVIDERS: frozenset[str] = frozenset({
        "openai",
        "litellm_proxy",
        "azure_openai",
        "mistral",
        "groq",
        "together",
        "fireworks",
        "perplexity",
        "deepseek",
        "anthropic",
        "gemini",
        "cohere",
    })

    def get_model(
        self,
        provider_key: str,
        model_id: str,
        api_key: str | None,
        base_url: str | None = None,
        max_tokens: int = 4096,
        output_json_schema: dict[str, Any] | None = None,
    ) -> BaseChatModel:
        """Create and return a LangChain ChatModel for the given provider.

        Args:
            provider_key: Provider identifier string (e.g. "openai", "anthropic").
            model_id: Model name (e.g. "gpt-4o", "claude-sonnet-4-5").
            api_key: Decrypted API key for the provider.
            base_url: Optional custom API base URL (overrides provider default).
            max_tokens: Maximum tokens in the response.
            output_json_schema: Optional JSON Schema for structured output.

        Returns:
            Initialised LangChain BaseChatModel instance.

        Raises:
            LangChainModelFactoryError: If provider is unsupported.
        """
        if provider_key not in self.SUPPORTED_PROVIDERS:
            raise LangChainModelFactoryError(
                f"Unsupported provider: '{provider_key}'. "
                f"Supported: {sorted(self.SUPPORTED_PROVIDERS)}"
            )

        if provider_key == "azure_openai":
            return self._create_azure_openai(model_id, api_key, base_url, max_tokens, output_json_schema)

        if provider_key in _OPENAI_COMPAT_PROVIDERS:
            return self._create_openai_compat(provider_key, model_id, api_key, base_url, max_tokens, output_json_schema)

        if provider_key == "anthropic":
            return self._create_anthropic(model_id, api_key, base_url, max_tokens)

        if provider_key == "gemini":
            return self._create_gemini(model_id, api_key, max_tokens)

        if provider_key == "cohere":
            return self._create_cohere(model_id, api_key, max_tokens)

        raise LangChainModelFactoryError(f"Unhandled provider: '{provider_key}'")

    def get_model_from_config_dict(
        self,
        model_id: str,
        model_config_dict: dict[str, Any],
        max_tokens: int = 4096,
        output_json_schema: dict[str, Any] | None = None,
        callbacks: list[Any] | None = None,
    ) -> BaseChatModel:
        """Create a ChatModel from a context dict (AR path — no DB access).

        Args:
            model_id: Model identifier string.
            model_config_dict: Dict from ControlCenterDataClient.get_model_config():
                Keys: provider_type, api_base_url, api_key (already decrypted).
            max_tokens: Maximum tokens.
            output_json_schema: Optional JSON Schema for structured output.
            callbacks: Optional LangChain callbacks to attach.

        Returns:
            Initialised LangChain BaseChatModel.
        """
        provider = model_config_dict.get("provider_type") or "openai"
        api_key = model_config_dict.get("api_key")
        base_url = model_config_dict.get("api_base_url")

        llm = self.get_model(
            provider_key=provider,
            model_id=model_id,
            api_key=api_key,
            base_url=base_url,
            max_tokens=max_tokens,
            output_json_schema=output_json_schema,
        )
        return llm

    # ── Private helpers ──────────────────────────────────────────────────────

    def _create_openai_compat(
        self,
        provider_key: str,
        model_id: str,
        api_key: str | None,
        base_url: str | None,
        max_tokens: int,
        output_json_schema: dict[str, Any] | None,
    ) -> BaseChatModel:
        """Create ChatOpenAI for any OpenAI-compatible provider."""
        from langchain_openai import ChatOpenAI

        effective_base = base_url or _PROVIDER_DEFAULTS.get(provider_key)
        if not effective_base:
            raise LangChainModelFactoryError(
                f"Provider '{provider_key}' requires api_base_url (no default configured)"
            )

        kwargs: dict[str, Any] = {
            "model": model_id,
            "api_key": api_key or "placeholder",  # Some providers need non-empty key
            "base_url": effective_base,
            "max_tokens": max_tokens,
        }

        return ChatOpenAI(**kwargs)

    def _create_azure_openai(
        self,
        model_id: str,
        api_key: str | None,
        base_url: str | None,
        max_tokens: int,
        output_json_schema: dict[str, Any] | None,
    ) -> BaseChatModel:
        """Create AzureChatOpenAI for Azure OpenAI deployments."""
        if not base_url:
            raise LangChainModelFactoryError(
                "azure_openai provider requires api_base_url (Azure endpoint)"
            )

        from langchain_openai import AzureChatOpenAI

        return AzureChatOpenAI(
            azure_endpoint=base_url,
            azure_deployment=model_id,
            api_key=api_key or "placeholder",
            api_version="2024-02-01",
            max_tokens=max_tokens,
        )

    def _create_anthropic(
        self,
        model_id: str,
        api_key: str | None,
        base_url: str | None,
        max_tokens: int,
    ) -> BaseChatModel:
        """Create ChatAnthropic using the native langchain-anthropic package."""
        from langchain_anthropic import ChatAnthropic

        kwargs: dict[str, Any] = {
            "model": model_id,
            "max_tokens": max_tokens,
        }
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        return ChatAnthropic(**kwargs)

    def _create_gemini(
        self,
        model_id: str,
        api_key: str | None,
        max_tokens: int,
    ) -> BaseChatModel:
        """Create ChatGoogleGenerativeAI using the native langchain-google-genai package."""
        from langchain_google_genai import ChatGoogleGenerativeAI

        kwargs: dict[str, Any] = {
            "model": model_id,
            "max_output_tokens": max_tokens,
        }
        if api_key:
            kwargs["google_api_key"] = api_key
        return ChatGoogleGenerativeAI(**kwargs)

    def _create_cohere(
        self,
        model_id: str,
        api_key: str | None,
        max_tokens: int,
    ) -> BaseChatModel:
        """Create ChatCohere using the native langchain-cohere package."""
        from langchain_cohere import ChatCohere

        kwargs: dict[str, Any] = {
            "model": model_id,
            "max_tokens": max_tokens,
        }
        if api_key:
            kwargs["cohere_api_key"] = api_key
        return ChatCohere(**kwargs)
