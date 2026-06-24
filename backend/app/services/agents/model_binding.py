"""Model Binding Layer — resolves LLM provider config from ModelConfig and dispatches via LangChain."""
import json
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.core.credential_vault import get_vault
from app.db.models.agents import AgentType, ModelConfig, ModelProvider

if TYPE_CHECKING:
    from app.agent_runtime.data_client import ControlCenterDataClient

logger = logging.getLogger(__name__)


def _convert_to_lc_messages(messages: list[dict[str, Any]]) -> list[Any]:
    """Convert dict-format messages to LangChain BaseMessage objects.

    LangChain's ainvoke() also accepts raw dicts, so this is a convenience
    wrapper used internally by ModelBindingLayer.complete() and
    complete_from_context().
    """
    try:
        from langchain_core.messages import convert_to_messages
        return convert_to_messages(messages)  # type: ignore[arg-type]
    except Exception:
        # Fallback: pass dicts through — LangChain handles them natively
        return messages  # type: ignore[return-value]




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
        callbacks: list[Any] | None = None,
        output_json_schema: dict[str, Any] | None = None,
    ) -> Any:
        """Send a chat completion using context dicts from the CC data API.

        Used by Agent Runtime where there are no ORM objects.  Returns a
        LangChain AIMessage (or a raw dict when the provider raises and the
        caller has already provided a fallback mock — see extract_* methods).

        Args:
            model_id: The model identifier string (e.g. "gpt-4o").
            model_config_dict: Dict from ``data_client.get_model_config()``.
                Keys: provider_type, api_base_url, api_key (decrypted).
            messages: Chat messages.
            tools: Optional tool definitions.
            max_tokens: Maximum tokens in the response.
            callbacks: Optional LangChain callbacks (e.g. GuardrailCallback,
                ExecutionLoggingCallback).
            output_json_schema: Optional JSON Schema for structured output via
                LangChain's .with_structured_output(). When set, structured
                output replaces the plain text response.
        """
        from app.services.agents.langchain_model_factory import LangChainModelFactory

        factory = LangChainModelFactory()
        llm = factory.get_model_from_config_dict(
            model_id=model_id,
            model_config_dict=model_config_dict,
            max_tokens=max_tokens,
            output_json_schema=output_json_schema,
        )

        if tools:
            llm = llm.bind_tools(tools)  # type: ignore[assignment]

        lc_messages = _convert_to_lc_messages(messages)
        invoke_config: dict[str, Any] = {}
        if callbacks:
            invoke_config["callbacks"] = callbacks

        return await llm.ainvoke(lc_messages, config=invoke_config or None)

    async def complete(
        self,
        agent_type: AgentType,
        model_config: ModelConfig | None,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        response_format: dict[str, Any] | None = None,
        callbacks: list[Any] | None = None,
    ) -> Any:
        """
        Send a chat completion request to the configured LLM provider via LangChain.

        Args:
            agent_type: The AgentType that defines the model_id.
            model_config: The ModelConfig with provider type and encrypted credentials.
            messages: List of chat messages (role + content).
            tools: Optional tool definitions for function calling.
            max_tokens: Maximum tokens in the response.
            response_format: Optional JSON Schema for structured output
                (wired via LangChain .with_structured_output()).
            callbacks: Optional LangChain callbacks.

        Returns:
            LangChain AIMessage (or structured-output dict when response_format set).
        """
        from app.services.agents.langchain_model_factory import LangChainModelFactory

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
        provider_key = provider.value if isinstance(provider, ModelProvider) else str(provider)
        base_url = model_config.api_base_url

        factory = LangChainModelFactory()
        llm = factory.get_model(
            provider_key=provider_key,
            model_id=model_name,
            api_key=api_key,
            base_url=base_url,
            max_tokens=max_tokens,
            output_json_schema=response_format,
        )

        if tools:
            llm = llm.bind_tools(tools)  # type: ignore[assignment]

        lc_messages = _convert_to_lc_messages(messages)
        invoke_config: dict[str, Any] = {}
        if callbacks:
            invoke_config["callbacks"] = callbacks

        return await llm.ainvoke(lc_messages, config=invoke_config or None)


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

    @staticmethod
    def extract_text(response, provider) -> str:
        """Extract the assistant\'s text response from a model response.

        Accepts either a LangChain AIMessage (from the LangChain dispatch path)
        or a raw provider response dict (for backward compat with mocked tests).
        Returns \"\" when the response is empty or unrecognised.
        """
        # LangChain AIMessage path (new)
        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        return block.get("text", "")
                    if isinstance(block, str):
                        return block
            return ""

        # Raw dict path (backward compat / test mocks)
        if not isinstance(response, dict):
            return ""

        provider_str = provider.value if isinstance(provider, ModelProvider) else provider

        if provider_str in (
            "openai", "litellm_proxy", "azure_openai", "mistral", "groq",
            "together", "fireworks", "perplexity", "deepseek",
        ):
            choices = response.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")

        if provider_str == "anthropic":
            content = response.get("content", [])
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
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
        response: Any, provider: ModelProvider | str
    ) -> list[dict[str, Any]]:
        """Extract tool call requests from a model response.

        Accepts either a LangChain AIMessage (new dispatch path) or a raw
        provider response dict (backward compat).  Always returns a list of
        dicts in the OpenAI ``{"id", "type", "function": {"name", "arguments"}}``
        shape so the caller does not need to branch on response type.
        """
        # ── LangChain AIMessage path (new) ─────────────────────────────────
        if hasattr(response, "tool_calls") and response.tool_calls:
            result: list[dict[str, Any]] = []
            for tc in response.tool_calls:
                if not isinstance(tc, dict):
                    continue
                result.append({
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("name", ""),
                        "arguments": json.dumps(tc.get("args", {})),
                    },
                })
            return result
        # Fallback: raw additional_kwargs.tool_calls (some LangChain providers)
        if hasattr(response, "additional_kwargs"):
            raw = response.additional_kwargs.get("tool_calls") or []
            if raw:
                return raw

        # ── Raw dict path (backward compat / test mocks) ──────────────────────
        if not isinstance(response, dict):
            return []

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
        response: Any, provider: ModelProvider | str
    ) -> dict[str, Any] | None:
        """Extract normalised token usage from provider response when available.

        Accepts either a LangChain AIMessage (new dispatch path) or a raw
        provider response dict (backward compat).  Returns ``None`` when usage
        info is unavailable — the agent runtime treats ``None`` as "usage
        unavailable" and continues the loop.
        """
        # ── LangChain AIMessage path (new) ─────────────────────────────────
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            meta = response.usage_metadata
            if isinstance(meta, dict):
                input_tok = meta.get("input_tokens", 0)
                output_tok = meta.get("output_tokens", 0)
                total_tok = meta.get("total_tokens") or (input_tok + output_tok)
                return {
                    "prompt_tokens": max(0, int(input_tok or 0)),
                    "completion_tokens": max(0, int(output_tok or 0)),
                    "total_tokens": max(0, int(total_tok or 0)),
                }

        # ── Raw dict path (backward compat / test mocks) ──────────────────────
        if not isinstance(response, dict):
            return None

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
