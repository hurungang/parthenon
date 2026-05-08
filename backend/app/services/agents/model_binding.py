"""Model Binding Layer — resolves LLM provider config from ModelConfig and sends prompts."""
import json
import logging
from typing import Any

import httpx
from sqlalchemy import select

from app.core.credential_vault import get_vault
from app.db.models.agents import AgentType, ModelConfig, ModelProvider
from app.db.session import AsyncSession

logger = logging.getLogger(__name__)

# Default endpoints per provider
OPENAI_DEFAULT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_DEFAULT_ENDPOINT = "https://api.anthropic.com/v1/messages"


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
        self, model_id: str, db: AsyncSession
    ) -> ModelConfig:
        """Find the ModelConfig whose enabled_models list contains model_id.

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

        if provider in (ModelProvider.openai, ModelProvider.litellm_proxy):
            endpoint = (
                f"{base_url.rstrip('/')}/chat/completions" if base_url else OPENAI_DEFAULT_ENDPOINT
            )
            return await self._call_openai_compat(
                api_key=api_key,
                model=model_name,
                endpoint=endpoint,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
            )
        elif provider == ModelProvider.anthropic:
            return await self._call_anthropic(
                api_key=api_key,
                model=model_name,
                messages=messages,
                max_tokens=max_tokens,
            )
        elif provider == ModelProvider.azure_openai:
            if not base_url:
                raise ModelBindingError("azure_openai provider requires api_base_url")
            endpoint = f"{base_url.rstrip('/')}/openai/deployments/{model_name}/chat/completions?api-version=2024-02-01"
            return await self._call_openai_compat(
                api_key=api_key,
                model=model_name,
                endpoint=endpoint,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
            )
        else:
            raise ModelBindingError(f"Unsupported provider: {provider}")

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
        """Send a request to an OpenAI-compatible Chat Completions endpoint."""
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

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
            if response.status_code >= 400:
                # Capture error details from response body
                try:
                    error_body = response.json()
                    error_msg = error_body.get("error", {}).get("message", response.text)
                    logger.error(
                        "OpenAI API error %d: %s",
                        response.status_code,
                        error_msg,
                    )
                except Exception:
                    logger.error("OpenAI API error %d: %s", response.status_code, response.text[:500])
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

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(ANTHROPIC_DEFAULT_ENDPOINT, json=payload, headers=headers)
            if response.status_code >= 400:
                # Capture error details from response body
                try:
                    error_body = response.json()
                    error_msg = error_body.get("error", {}).get("message", response.text)
                    logger.error(
                        "Anthropic API error %d: %s",
                        response.status_code,
                        error_msg,
                    )
                except Exception:
                    logger.error("Anthropic API error %d: %s", response.status_code, response.text[:500])
            response.raise_for_status()
            return response.json()

    @staticmethod
    def extract_text(response: dict[str, Any], provider: ModelProvider | str) -> str:
        """Extract the assistant's text response from a model response dict."""
        provider_str = provider.value if isinstance(provider, ModelProvider) else provider
        if provider_str in ("openai", "litellm_proxy", "azure_openai"):
            choices = response.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
        elif provider_str == "anthropic":
            content = response.get("content", [])
            for block in content:
                if block.get("type") == "text":
                    return block.get("text", "")
        return ""

    @staticmethod
    def extract_tool_calls(response: dict[str, Any], provider: ModelProvider | str) -> list[dict[str, Any]]:
        """Extract tool call requests from a model response dict."""
        provider_str = provider.value if isinstance(provider, ModelProvider) else provider
        if provider_str in ("openai", "litellm_proxy", "azure_openai"):
            choices = response.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                return msg.get("tool_calls", [])
        return []
