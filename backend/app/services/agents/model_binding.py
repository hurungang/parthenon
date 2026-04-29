"""Model Binding Layer — resolves LLM provider config and sends prompts."""
import json
import logging
from typing import Any

import httpx

from app.core.credential_vault import get_vault
from app.db.models.agents import AgentType

logger = logging.getLogger(__name__)

# Supported LLM providers
PROVIDER_ENDPOINTS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "azure_openai": "{base_url}/openai/deployments/{model}/chat/completions?api-version=2024-02-01",
}


class ModelBindingError(Exception):
    """Raised when model binding or inference fails."""


class ModelBindingLayer:
    """
    Resolves LLM provider credentials and model config per agent type,
    sends prompts, and returns model responses.
    """

    async def complete(
        self,
        agent_type: AgentType,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """
        Send a chat completion request to the configured LLM provider.

        Args:
            agent_type: The AgentType with LLM config and encrypted credentials.
            messages: List of chat messages (role + content).
            tools: Optional list of tool definitions for function calling.
            max_tokens: Maximum tokens in the response.

        Returns:
            Raw model response dict.
        """
        provider = agent_type.llm_provider.lower()
        if provider not in PROVIDER_ENDPOINTS:
            raise ModelBindingError(f"Unsupported LLM provider: {provider}")

        # Decrypt credentials
        api_key = self._resolve_api_key(agent_type)

        if provider == "openai":
            return await self._call_openai(
                api_key=api_key,
                model=agent_type.llm_model,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
            )
        elif provider == "anthropic":
            return await self._call_anthropic(
                api_key=api_key,
                model=agent_type.llm_model,
                messages=messages,
                max_tokens=max_tokens,
            )
        else:
            raise ModelBindingError(f"Provider '{provider}' not yet implemented")

    def _resolve_api_key(self, agent_type: AgentType) -> str:
        """Decrypt the LLM API key from stored credentials."""
        if not agent_type.encrypted_llm_credentials:
            raise ModelBindingError(
                f"No LLM credentials configured for agent type '{agent_type.name}'"
            )
        vault = get_vault()
        creds_json = vault.decrypt(agent_type.encrypted_llm_credentials)
        creds: dict[str, Any] = json.loads(creds_json)
        api_key = creds.get("api_key", "")
        if not api_key:
            raise ModelBindingError(
                f"No 'api_key' found in credentials for agent type '{agent_type.name}'"
            )
        return api_key

    async def _call_openai(
        self,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Send a request to the OpenAI Chat Completions API."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                PROVIDER_ENDPOINTS["openai"],
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

    async def _call_anthropic(
        self,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> dict[str, Any]:
        """Send a request to the Anthropic Messages API."""
        # Separate system message from the rest
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

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                PROVIDER_ENDPOINTS["anthropic"],
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

    @staticmethod
    def extract_text(response: dict[str, Any], provider: str) -> str:
        """Extract the assistant's text response from a model response dict."""
        if provider == "openai":
            choices = response.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
        elif provider == "anthropic":
            content = response.get("content", [])
            for block in content:
                if block.get("type") == "text":
                    return block.get("text", "")
        return ""

    @staticmethod
    def extract_tool_calls(response: dict[str, Any], provider: str) -> list[dict[str, Any]]:
        """Extract tool call requests from a model response dict."""
        if provider == "openai":
            choices = response.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                return msg.get("tool_calls", [])
        return []
