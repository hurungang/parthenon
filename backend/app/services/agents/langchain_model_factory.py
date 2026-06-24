"""LangChain Model Factory — creates LangChain ChatModel instances for all providers.

Replaces ModelBindingLayer._dispatch() and the PROVIDER_REGISTRY facade.
Supports all 12 providers via LangChain ChatModel subclasses or custom
BaseChatModel wrappers for native-API providers (Anthropic, Gemini, Cohere).

Providers are grouped:
- OpenAI-compatible (9): ChatOpenAI with provider-specific base_url
- Azure OpenAI: AzureChatOpenAI
- Anthropic: AnthropicChatModel (custom BaseChatModel using Anthropic HTTP API)
- Gemini: GeminiChatModel (custom BaseChatModel using Gemini HTTP API)
- Cohere: CohereChatModel (custom BaseChatModel using Cohere HTTP API)

All custom BaseChatModel subclasses preserve mTLS via get_ssl_context().
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Iterator, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

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


class _AnthropicChatModel(BaseChatModel):
    """Custom BaseChatModel wrapping the Anthropic Messages API.

    Uses direct HTTP dispatch via httpx to support mTLS through get_ssl_context().
    """

    model_name: str
    api_key: Optional[str] = None
    api_base_url: str = "https://api.anthropic.com/v1"
    max_tokens: int = 4096

    @property
    def _llm_type(self) -> str:
        return "anthropic-http"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            self._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        )
        return result

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        import httpx
        from app.core.ssl_context import get_ssl_context
        from langchain_core.messages import SystemMessage

        system_text = ""
        user_msgs: list[dict[str, Any]] = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_text = msg.content if isinstance(msg.content, str) else str(msg.content)
            else:
                role_map = {"human": "user", "ai": "assistant", "tool": "user"}
                role = role_map.get(msg.type, "user")
                content_str = msg.content if isinstance(msg.content, str) else str(msg.content)
                user_msgs.append({"role": role, "content": content_str})

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": user_msgs,
            "max_tokens": self.max_tokens,
        }
        if system_text:
            payload["system"] = system_text
        if stop:
            payload["stop_sequences"] = stop

        headers = {
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key

        endpoint = f"{self.api_base_url.rstrip('/')}/messages"
        async with httpx.AsyncClient(timeout=120.0, verify=get_ssl_context()) as client:
            resp = await client.post(endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        text = ""
        for block in data.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                break

        usage = data.get("usage", {})
        ai_msg = AIMessage(
            content=text,
            usage_metadata={
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "total_tokens": (usage.get("input_tokens", 0) + usage.get("output_tokens", 0)),
            } if usage else None,
        )
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    def _stream(self, messages: List[BaseMessage], **kwargs: Any) -> Iterator[Any]:
        raise NotImplementedError("Streaming not supported for AnthropicChatModel")


class _GeminiChatModel(BaseChatModel):
    """Custom BaseChatModel wrapping the Google Gemini generateContent API.

    Uses direct HTTP dispatch via httpx to support mTLS through get_ssl_context().
    """

    model_name: str
    api_key: Optional[str] = None
    api_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    max_tokens: int = 4096

    @property
    def _llm_type(self) -> str:
        return "gemini-http"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        )

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        import httpx
        from app.core.ssl_context import get_ssl_context
        from langchain_core.messages import SystemMessage

        contents: list[dict[str, Any]] = []
        system_parts: list[dict[str, Any]] = []
        for msg in messages:
            text = msg.content if isinstance(msg.content, str) else str(msg.content)
            if isinstance(msg, SystemMessage):
                system_parts.append({"text": text})
            elif msg.type == "ai":
                contents.append({"role": "model", "parts": [{"text": text}]})
            else:
                contents.append({"role": "user", "parts": [{"text": text}]})

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": self.max_tokens},
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}

        endpoint = f"{self.api_base_url.rstrip('/')}/models/{self.model_name}:generateContent"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["x-goog-api-key"] = self.api_key

        async with httpx.AsyncClient(timeout=120.0, verify=get_ssl_context()) as client:
            resp = await client.post(endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        text = ""
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                if isinstance(part.get("text"), str):
                    text = part["text"]
                    break
            if text:
                break

        meta = data.get("usageMetadata", {})
        ai_msg = AIMessage(
            content=text,
            usage_metadata={
                "input_tokens": meta.get("promptTokenCount", 0),
                "output_tokens": meta.get("candidatesTokenCount", 0),
                "total_tokens": meta.get("totalTokenCount", 0),
            } if meta else None,
        )
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    def _stream(self, messages: List[BaseMessage], **kwargs: Any) -> Iterator[Any]:
        raise NotImplementedError("Streaming not supported for GeminiChatModel")


class _CohereChatModel(BaseChatModel):
    """Custom BaseChatModel wrapping the Cohere /v1/chat API.

    Uses direct HTTP dispatch via httpx to support mTLS through get_ssl_context().
    """

    model_name: str
    api_key: Optional[str] = None
    api_base_url: str = "https://api.cohere.com/v1"
    max_tokens: int = 4096

    @property
    def _llm_type(self) -> str:
        return "cohere-http"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        )

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        import httpx
        from app.core.ssl_context import get_ssl_context
        from langchain_core.messages import SystemMessage

        chat_history: list[dict[str, str]] = []
        preamble: str | None = None
        for msg in messages:
            text = msg.content if isinstance(msg.content, str) else str(msg.content)
            if isinstance(msg, SystemMessage):
                preamble = text
            elif msg.type == "ai":
                chat_history.append({"role": "CHATBOT", "message": text})
            else:
                chat_history.append({"role": "USER", "message": text})

        message = ""
        if chat_history and chat_history[-1]["role"] == "USER":
            message = chat_history.pop(-1)["message"]

        payload: dict[str, Any] = {
            "model": self.model_name,
            "message": message,
            "chat_history": chat_history,
            "max_tokens": self.max_tokens,
        }
        if preamble:
            payload["preamble"] = preamble

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        endpoint = f"{self.api_base_url.rstrip('/')}/chat"
        async with httpx.AsyncClient(timeout=120.0, verify=get_ssl_context()) as client:
            resp = await client.post(endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        text = data.get("text", "")
        meta = (data.get("meta") or {}).get("tokens", {})
        ai_msg = AIMessage(
            content=text,
            usage_metadata={
                "input_tokens": meta.get("input_tokens", 0),
                "output_tokens": meta.get("output_tokens", 0),
                "total_tokens": (meta.get("input_tokens", 0) + meta.get("output_tokens", 0)),
            } if meta else None,
        )
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    def _stream(self, messages: List[BaseMessage], **kwargs: Any) -> Iterator[Any]:
        raise NotImplementedError("Streaming not supported for CohereChatModel")


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
            effective_url = base_url or _PROVIDER_DEFAULTS["anthropic"]
            llm: BaseChatModel = _AnthropicChatModel(
                model_name=model_id,
                api_key=api_key,
                api_base_url=effective_url,
                max_tokens=max_tokens,
            )
            return llm

        if provider_key == "gemini":
            effective_url = base_url or _PROVIDER_DEFAULTS["gemini"]
            llm = _GeminiChatModel(
                model_name=model_id,
                api_key=api_key,
                api_base_url=effective_url,
                max_tokens=max_tokens,
            )
            return llm

        if provider_key == "cohere":
            effective_url = base_url or _PROVIDER_DEFAULTS["cohere"]
            llm = _CohereChatModel(
                model_name=model_id,
                api_key=api_key,
                api_base_url=effective_url,
                max_tokens=max_tokens,
            )
            return llm

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
        """Create ChatOpenAI for any OpenAI-compatible provider.
        
        NOTE: Do NOT apply with_structured_output() here. It returns a RunnableSequence
        which doesn't support bind_tools(). Instead, let the model return normally
        and extract structured output from the AIMessage using _extract_structured_output().
        The output_json_schema is only used for the LLM's awareness (e.g., in system prompt).
        """
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

        llm = ChatOpenAI(**kwargs)
        # Don't apply with_structured_output() here - it's incompatible with bind_tools()
        return llm

    def _create_azure_openai(
        self,
        model_id: str,
        api_key: str | None,
        base_url: str | None,
        max_tokens: int,
        output_json_schema: dict[str, Any] | None,
    ) -> BaseChatModel:
        """Create AzureChatOpenAI for Azure OpenAI deployments."""
        from langchain_openai import AzureChatOpenAI

        if not base_url:
            raise LangChainModelFactoryError(
                "azure_openai provider requires api_base_url (Azure endpoint)"
            )

        llm = AzureChatOpenAI(
            azure_endpoint=base_url,
            azure_deployment=model_id,
            api_key=api_key or "placeholder",
            api_version="2024-02-01",
            max_tokens=max_tokens,
        )

        # Don't apply with_structured_output() here - it's incompatible with bind_tools()
        # Structured output extraction will happen in _extract_structured_output() instead
        return llm
