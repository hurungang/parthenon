"""Model Binding Layer — resolves LLM provider config from ModelConfig and sends prompts."""
import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Coroutine

import httpx
from sqlalchemy import select

from app.core.credential_vault import get_vault
from app.core.ssl_context import get_ssl_context
from app.db.models.agents import AgentType, ModelConfig, ModelProvider

if TYPE_CHECKING:
    from app.agent_runtime.data_client import ControlCenterDataClient

logger = logging.getLogger(__name__)

# Default endpoints per provider
OPENAI_DEFAULT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_DEFAULT_ENDPOINT = "https://api.anthropic.com/v1/messages"
GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
COHERE_DEFAULT_ENDPOINT = "https://api.cohere.com/v1/chat"


# ── Provider registry facade ──────────────────────────────────────────────────


class DispatchFamily(str, Enum):
    """Dispatch family tag used by the provider-registry facade."""

    OPENAI_COMPAT = "openai_compat"
    NATIVE = "native"


@dataclass(frozen=True)
class DispatchSpec:
    """Per-provider dispatch metadata used by the provider-registry facade.

    Attributes:
        family: Which dispatch family the provider belongs to.
        default_api_base_url: Default API base URL (when the operator does not
            provide an explicit ``api_base_url`` in the model config).
        url_style: How the per-request URL is composed:
            * ``"openai_chat_completions"`` — append ``/chat/completions``
            * ``"azure_openai_deployment"`` — compose
              ``{base}/openai/deployments/{model}/chat/completions?api-version=2024-02-01``
            * ``"anthropic_messages"`` — POST to the Anthropic Messages API
            * ``"gemini_generate_content"`` — POST to
              ``{base}/models/{model}:generateContent``
            * ``"cohere_chat"`` — POST to ``{base}/chat``
        credential_header: HTTP header used to carry the API key.  The header
            value is always the API key directly (bearer for OpenAI-compat and
            Cohere; literal key for Anthropic and Gemini).
    """

    family: DispatchFamily
    default_api_base_url: str | None
    url_style: str
    credential_header: str


# Per-provider registry — the single source of truth for the dispatcher.
# Adding a new provider means adding one entry here, one Pydantic enum
# member, and one Alembic migration; nothing else needs to change.
PROVIDER_REGISTRY: dict[str, DispatchSpec] = {
    ModelProvider.openai.value: DispatchSpec(
        family=DispatchFamily.OPENAI_COMPAT,
        default_api_base_url="https://api.openai.com/v1",
        url_style="openai_chat_completions",
        credential_header="Authorization",
    ),
    ModelProvider.litellm_proxy.value: DispatchSpec(
        family=DispatchFamily.OPENAI_COMPAT,
        default_api_base_url=None,  # operator must configure
        url_style="openai_chat_completions",
        credential_header="Authorization",
    ),
    ModelProvider.azure_openai.value: DispatchSpec(
        family=DispatchFamily.OPENAI_COMPAT,
        default_api_base_url=None,  # operator must configure
        url_style="azure_openai_deployment",
        credential_header="Authorization",
    ),
    ModelProvider.mistral.value: DispatchSpec(
        family=DispatchFamily.OPENAI_COMPAT,
        default_api_base_url="https://api.mistral.ai/v1",
        url_style="openai_chat_completions",
        credential_header="Authorization",
    ),
    ModelProvider.groq.value: DispatchSpec(
        family=DispatchFamily.OPENAI_COMPAT,
        default_api_base_url="https://api.groq.com/openai/v1",
        url_style="openai_chat_completions",
        credential_header="Authorization",
    ),
    ModelProvider.together.value: DispatchSpec(
        family=DispatchFamily.OPENAI_COMPAT,
        default_api_base_url="https://api.together.xyz/v1",
        url_style="openai_chat_completions",
        credential_header="Authorization",
    ),
    ModelProvider.fireworks.value: DispatchSpec(
        family=DispatchFamily.OPENAI_COMPAT,
        default_api_base_url="https://api.fireworks.ai/inference/v1",
        url_style="openai_chat_completions",
        credential_header="Authorization",
    ),
    ModelProvider.perplexity.value: DispatchSpec(
        family=DispatchFamily.OPENAI_COMPAT,
        default_api_base_url="https://api.perplexity.ai",
        url_style="openai_chat_completions",
        credential_header="Authorization",
    ),
    ModelProvider.deepseek.value: DispatchSpec(
        family=DispatchFamily.OPENAI_COMPAT,
        default_api_base_url="https://api.deepseek.com/v1",
        url_style="openai_chat_completions",
        credential_header="Authorization",
    ),
    ModelProvider.anthropic.value: DispatchSpec(
        family=DispatchFamily.NATIVE,
        default_api_base_url="https://api.anthropic.com/v1",
        url_style="anthropic_messages",
        credential_header="x-api-key",
    ),
    ModelProvider.gemini.value: DispatchSpec(
        family=DispatchFamily.NATIVE,
        default_api_base_url="https://generativelanguage.googleapis.com/v1beta",
        url_style="gemini_generate_content",
        credential_header="x-goog-api-key",
    ),
    ModelProvider.cohere.value: DispatchSpec(
        family=DispatchFamily.NATIVE,
        default_api_base_url="https://api.cohere.com/v1",
        url_style="cohere_chat",
        credential_header="Authorization",
    ),
}


# Call signature shared by all _call_* private methods.
CallFn = Callable[..., Coroutine[Any, Any, dict[str, Any]]]


class ModelBindingError(Exception):
    """Raised when model binding or inference fails."""


class ModelBindingLayer:
    """
    Resolves LLM provider credentials and model config from a ModelConfig record,
    sends prompts, and returns model responses.

    AgentType.model_id is a provider-scoped model name string (e.g., "gpt-4o").
    resolve_model_config() searches all ModelConfig records whose enabled_models list
    contains the model_id to find the correct provider configuration.
    """

    async def resolve_model_config(
        self, model_id: str, db: "AsyncSession"
    ) -> ModelConfig:
        """Find the ModelConfig whose enabled_models list contains model_id.

        Used by Control Center (has DB access).  Agent Runtime uses
        ``fetch_model_config_via_client`` instead.

        Raises ModelBindingError if no config has the model enabled.
        """
        result = await db.execute(select(ModelConfig))
        configs: list[ModelConfig] = list(result.scalars().all())
        for config in configs:
            if model_id in (config.enabled_models or []):
                return config
        raise ModelBindingError(
            f"No ModelConfig found with model '{model_id}' in its enabled_models list. "
            "Add the model to a provider configuration's enabled models first."
        )

    async def fetch_model_config_via_client(
        self, model_config_id: str, data_client: "ControlCenterDataClient"
    ) -> dict[str, Any]:
        """Return model config dict with decrypted credentials from Control Center.

        Used by Agent Runtime (no DB access).  model_config_id is a UUID string
        resolved by the CC agent context endpoint.

        Returns dict with keys: id, display_name, provider_type, api_base_url,
        api_key (decrypted), enabled_models.
        """
        import uuid

        return await data_client.get_model_config(uuid.UUID(model_config_id))

    async def complete_from_context(
        self,
        model_id: str,
        model_config_dict: dict[str, Any],
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """Send a chat completion using context dicts from the CC data API.

        Used by Agent Runtime where there are no ORM objects.

        Args:
            model_id: The model identifier string (e.g. "gpt-4o").
            model_config_dict: Dict from ``data_client.get_model_config()``.
                Keys: provider_type, api_base_url, api_key (decrypted).
            messages: Chat messages.
            tools: Optional tool definitions.
            max_tokens: Maximum tokens in the response.
        """
        provider = model_config_dict.get("provider_type")
        base_url = model_config_dict.get("api_base_url")
        api_key = model_config_dict.get("api_key")  # already decrypted by CC

        return await self._dispatch(
            provider_key=provider,
            api_key=api_key,
            base_url=base_url,
            model=model_id,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
        )

    async def complete(
        self,
        agent_type: AgentType,
        model_config: ModelConfig | None,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """
        Send a chat completion request to the configured LLM provider.

        Args:
            agent_type: The AgentType that defines the model_id.
            model_config: The ModelConfig with provider type and encrypted credentials.
                          If None the call will fail with ModelBindingError.
                          Use resolve_model_config(agent_type.model_id, db) to obtain it.
            messages: List of chat messages (role + content).
            tools: Optional tool definitions for function calling.
            max_tokens: Maximum tokens in the response.

        Returns:
            Raw model response dict.
        """
        if model_config is None:
            raise ModelBindingError(
                f"AgentType '{agent_type.name}' has no model configuration assigned"
            )

        model_name = agent_type.model_id
        if not model_name:
            raise ModelBindingError(
                f"AgentType '{agent_type.name}' has no model_id set"
            )

        api_key = self._resolve_api_key(model_config)
        provider = model_config.provider_type
        base_url = model_config.api_base_url

        return await self._dispatch(
            provider_key=provider.value if isinstance(provider, ModelProvider) else provider,
            api_key=api_key,
            base_url=base_url,
            model=model_name,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
        )

    async def _dispatch(
        self,
        *,
        provider_key: str | None,
        api_key: str | None,
        base_url: str | None,
        model: str,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Resolve a provider key via the registry and dispatch to the right caller.

        All 12 provider keys are routed through this single function.  Adding a
        new provider means adding one ``DispatchSpec`` entry in
        ``PROVIDER_REGISTRY`` (and for native providers, one ``_call_*`` method
        that knows the vendor's request/response shape).
        """
        spec = PROVIDER_REGISTRY.get(provider_key or "")
        if spec is None:
            logger.error(
                "ModelBindingLayer._dispatch: unsupported provider '%s' (known: %s)",
                provider_key,
                ", ".join(sorted(PROVIDER_REGISTRY.keys())),
            )
            raise ModelBindingError(f"Unsupported provider: {provider_key}")

        # OpenAI-compatible family: all nine providers (the 3 incumbent
        # + 6 new) share the same /chat/completions shape.
        if spec.family is DispatchFamily.OPENAI_COMPAT:
            if spec.url_style == "azure_openai_deployment":
                if not base_url:
                    raise ModelBindingError(
                        "azure_openai provider requires api_base_url"
                    )
                endpoint = (
                    f"{base_url.rstrip('/')}/openai/deployments/{model}"
                    f"/chat/completions?api-version=2024-02-01"
                )
            else:
                effective_base = base_url or spec.default_api_base_url
                if not effective_base:
                    raise ModelBindingError(
                        f"Provider '{provider_key}' requires api_base_url"
                    )
                endpoint = f"{effective_base.rstrip('/')}/chat/completions"

            return await self._call_openai_compat(
                api_key=api_key,
                model=model,
                endpoint=endpoint,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
            )

        # Native-API family: per-vendor request/response shape.
        if spec.url_style == "anthropic_messages":
            return await self._call_anthropic(
                api_key=api_key,
                model=model,
                messages=messages,
                max_tokens=max_tokens,
            )
        if spec.url_style == "gemini_generate_content":
            effective_base = base_url or spec.default_api_base_url
            return await self._call_gemini(
                api_key=api_key,
                model=model,
                base_url=effective_base,
                messages=messages,
                max_tokens=max_tokens,
            )
        if spec.url_style == "cohere_chat":
            return await self._call_cohere(
                api_key=api_key,
                model=model,
                messages=messages,
                max_tokens=max_tokens,
            )

        # Should never happen — registry and dispatch are out of sync.
        raise ModelBindingError(
            f"Provider '{provider_key}' has unrecognised url_style '{spec.url_style}'"
        )

    def _resolve_api_key(self, model_config: ModelConfig) -> str | None:
        """Decrypt the API key from stored credentials (returns None if not set)."""
        if not model_config.encrypted_api_key:
            return None
        vault = get_vault()
        try:
            creds_json = vault.decrypt(model_config.encrypted_api_key)
            creds: dict[str, Any] = json.loads(creds_json)
            return creds.get("api_key") or None
        except Exception as exc:
            logger.warning("Failed to decrypt credentials for ModelConfig %s: %s", model_config.id, exc)
            return None

    async def _call_openai_compat(
        self,
        api_key: str | None,
        model: str,
        endpoint: str,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Send a request to an OpenAI-compatible Chat Completions endpoint.

        Reused by all 9 OpenAI-compatible providers (openai, litellm_proxy,
        azure_openai, mistral, groq, together, fireworks, perplexity, deepseek).
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(timeout=120.0, verify=get_ssl_context()) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
            if response.status_code >= 400:
                self._log_4xx("openai_compat", model, response)
            response.raise_for_status()
            return response.json()

    async def _call_anthropic(
        self,
        api_key: str | None,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> dict[str, Any]:
        """Send a request to the Anthropic Messages API."""
        system_msg = ""
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                user_messages.append(msg)

        payload: dict[str, Any] = {
            "model": model,
            "messages": user_messages,
            "max_tokens": max_tokens,
        }
        if system_msg:
            payload["system"] = system_msg

        headers: dict[str, str] = {
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        if api_key:
            headers["x-api-key"] = api_key

        async with httpx.AsyncClient(timeout=120.0, verify=get_ssl_context()) as client:
            response = await client.post(ANTHROPIC_DEFAULT_ENDPOINT, json=payload, headers=headers)
            if response.status_code >= 400:
                self._log_4xx("anthropic", model, response)
            response.raise_for_status()
            return response.json()

    async def _call_gemini(
        self,
        api_key: str | None,
        model: str,
        base_url: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> dict[str, Any]:
        """Send a request to the Google Gemini native generateContent endpoint.

        Translates Parthenon's open-ended ``messages`` list into Gemini's
        ``contents`` shape and reads the response back into a dict.  The
        response envelope is recognised by ``extract_text`` / ``extract_tool_calls``
        / ``extract_usage`` (which return ``""`` / ``[]`` / ``None`` on fields
        Gemini does not expose).
        """
        contents: list[dict[str, Any]] = []
        system_parts: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role")
            text = msg.get("content", "")
            if role == "system":
                system_parts.append({"text": text})
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": text}]})
            else:  # user / tool / default
                contents.append({"role": "user", "parts": [{"text": text}]})

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}

        endpoint = f"{base_url.rstrip('/')}/models/{model}:generateContent"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["x-goog-api-key"] = api_key

        async with httpx.AsyncClient(timeout=120.0, verify=get_ssl_context()) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
            if response.status_code >= 400:
                self._log_4xx("gemini", model, response)
            response.raise_for_status()
            return response.json()

    async def _call_cohere(
        self,
        api_key: str | None,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> dict[str, Any]:
        """Send a request to the Cohere native /v1/chat endpoint.

        Translates Parthenon's open-ended ``messages`` list into Cohere's
        ``chat_history`` shape and reads the response back into a dict.
        """
        chat_history: list[dict[str, str]] = []
        preamble: str | None = None
        for msg in messages:
            role = msg.get("role")
            text = msg.get("content", "")
            if role == "system":
                preamble = text
            elif role == "assistant":
                chat_history.append({"role": "CHATBOT", "message": text})
            else:  # user / default
                chat_history.append({"role": "USER", "message": text})

        # The final user message is the implicit ``message`` field; everything
        # earlier is part of ``chat_history``.
        if chat_history and chat_history[-1]["role"] == "USER":
            message = chat_history.pop(-1)["message"]
        else:
            message = ""

        payload: dict[str, Any] = {
            "model": model,
            "message": message,
            "chat_history": chat_history,
            "max_tokens": max_tokens,
        }
        if preamble:
            payload["preamble"] = preamble

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(timeout=120.0, verify=get_ssl_context()) as client:
            response = await client.post(COHERE_DEFAULT_ENDPOINT, json=payload, headers=headers)
            if response.status_code >= 400:
                self._log_4xx("cohere", model, response)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _log_4xx(provider: str, model: str, response: httpx.Response) -> None:
        """Structured log line for any non-2xx response.

        The provider key is always the first token in the message so operators
        can route on it (``grep gemini`` vs ``grep openai``).
        """
        try:
            error_body = response.json()
            error_msg = (
                error_body.get("error", {}).get("message")
                if isinstance(error_body, dict)
                else None
            )
            if not error_msg:
                error_msg = response.text[:500]
        except Exception:
            error_msg = response.text[:500]
        logger.error(
            "%s API error %d (model=%s): %s",
            provider,
            response.status_code,
            model,
            error_msg,
        )

    @staticmethod
    def extract_text(response: dict[str, Any], provider: ModelProvider | str) -> str:
        """Extract the assistant's text response from a model response dict.

        Recognises the response envelope for all 12 supported providers.  An
        unrecognised envelope or an absent text field returns ``""``.
        """
        provider_str = provider.value if isinstance(provider, ModelProvider) else provider

        if provider_str in (
            "openai",
            "litellm_proxy",
            "azure_openai",
            "mistral",
            "groq",
            "together",
            "fireworks",
            "perplexity",
            "deepseek",
        ):
            choices = response.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")

        if provider_str == "anthropic":
            content = response.get("content", [])
            for block in content:
                if block.get("type") == "text":
                    return block.get("text", "")

        if provider_str == "gemini":
            candidates = response.get("candidates", [])
            for cand in candidates:
                parts = cand.get("content", {}).get("parts", [])
                for part in parts:
                    text = part.get("text")
                    if isinstance(text, str):
                        return text

        if provider_str == "cohere":
            return response.get("text", "")

        return ""

    @staticmethod
    def extract_tool_calls(
        response: dict[str, Any], provider: ModelProvider | str
    ) -> list[dict[str, Any]]:
        """Extract tool call requests from a model response dict.

        Cohere and Gemini native envelopes do not currently expose normalised
        tool-call structures; the call returns ``[]`` for those providers.  If
        a vendor adds tool calling later, extend this function to recognise
        the new envelope — the public surface (a list of dicts with the
        OpenAI ``{"id", "type", "function": {"name", "arguments"}}`` shape)
        stays the same.
        """
        provider_str = provider.value if isinstance(provider, ModelProvider) else provider

        if provider_str in (
            "openai",
            "litellm_proxy",
            "azure_openai",
            "mistral",
            "groq",
            "together",
            "fireworks",
            "perplexity",
            "deepseek",
        ):
            choices = response.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                return msg.get("tool_calls", [])

        # Cohere / Gemini: no normalised tool-call envelope yet.
        return []

    @staticmethod
    def extract_usage(
        response: dict[str, Any], provider: ModelProvider | str
    ) -> dict[str, Any] | None:
        """Extract normalised token usage from provider response when available.

        Returns ``None`` (rather than raising) when the provider does not
        report usage — the agent runtime treats ``None`` as "usage unavailable"
        and continues the loop.
        """
        provider_str = provider.value if isinstance(provider, ModelProvider) else provider

        # OpenAI-compat family: ``usage.prompt_tokens / completion_tokens / total_tokens``
        if provider_str in (
            "openai",
            "litellm_proxy",
            "azure_openai",
            "mistral",
            "groq",
            "together",
            "fireworks",
            "perplexity",
            "deepseek",
        ):
            usage = response.get("usage")
            if not isinstance(usage, dict):
                return None
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            total_tokens = usage.get("total_tokens")
            if (
                not isinstance(prompt_tokens, int)
                and not isinstance(completion_tokens, int)
                and not isinstance(total_tokens, int)
            ):
                return None
            if not isinstance(total_tokens, int):
                prompt = prompt_tokens if isinstance(prompt_tokens, int) else 0
                completion = completion_tokens if isinstance(completion_tokens, int) else 0
                total_tokens = prompt + completion
            return {
                "prompt_tokens": max(0, int(prompt_tokens or 0)),
                "completion_tokens": max(0, int(completion_tokens or 0)),
                "total_tokens": max(0, int(total_tokens or 0)),
            }

        if provider_str == "anthropic":
            usage = response.get("usage")
            if not isinstance(usage, dict):
                return None
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            if not isinstance(input_tokens, int) and not isinstance(output_tokens, int):
                return None
            prompt = max(0, int(input_tokens or 0))
            completion = max(0, int(output_tokens or 0))
            return {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
            }

        if provider_str == "gemini":
            # Gemini's ``usageMetadata`` envelope.  Optional; some responses
            # do not include it (e.g. when blocked by safety).
            metadata = response.get("usageMetadata")
            if not isinstance(metadata, dict):
                return None
            prompt_tokens = metadata.get("promptTokenCount")
            completion_tokens = metadata.get("candidatesTokenCount")
            total_tokens = metadata.get("totalTokenCount")
            if not any(isinstance(x, int) for x in (prompt_tokens, completion_tokens, total_tokens)):
                return None
            if not isinstance(total_tokens, int):
                prompt = prompt_tokens if isinstance(prompt_tokens, int) else 0
                completion = completion_tokens if isinstance(completion_tokens, int) else 0
                total_tokens = prompt + completion
            return {
                "prompt_tokens": max(0, int(prompt_tokens or 0)),
                "completion_tokens": max(0, int(completion_tokens or 0)),
                "total_tokens": max(0, int(total_tokens or 0)),
            }

        if provider_str == "cohere":
            # Cohere's ``meta.tokens`` envelope.  ``input_tokens`` /
            # ``output_tokens`` are reported when ``usage`` is enabled.
            meta = response.get("meta") or {}
            tokens = meta.get("tokens") if isinstance(meta, dict) else None
            if not isinstance(tokens, dict):
                return None
            input_tokens = tokens.get("input_tokens")
            output_tokens = tokens.get("output_tokens")
            if not isinstance(input_tokens, int) and not isinstance(output_tokens, int):
                return None
            prompt = max(0, int(input_tokens or 0))
            completion = max(0, int(output_tokens or 0))
            return {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
            }

        return None
