"""ModelConfigService — CRUD for ModelConfig with AES-256 credential encryption."""
import json
import uuid
import logging
from typing import Any

import httpx
from sqlalchemy import select

from app.core.credential_vault import get_vault
from app.core.ssl_context import get_ssl_context
from app.db.models.agents import AgentType, ModelConfig, ModelProvider
from app.db.session import AsyncSession

logger = logging.getLogger(__name__)


# ── Fallback curated model lists (used when live API call fails) ────────────
#
# These are used only as a last resort when the provider's live API is
# unreachable or returns an error.  Kept minimal and up-to-date.

# Fallback for Google Gemini — stable GA models only (1.5-series is deprecated).
GEMINI_FALLBACK_MODELS: list[str] = sorted(
    [
        "gemini-2.0-flash",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
    ]
)

# Fallback for Cohere — current Command family.
COHERE_FALLBACK_MODELS: list[str] = sorted(
    [
        "command-r",
        "command-r-plus",
        "command-r7b",
        "command-a-03-2025",
    ]
)

# Fallback for Anthropic — current Claude models.
ANTHROPIC_FALLBACK_MODELS: list[str] = sorted(
    [
        "claude-3-5-haiku-latest",
        "claude-3-5-sonnet-latest",
        "claude-3-7-sonnet-latest",
        "claude-opus-4-5",
        "claude-sonnet-4-5",
    ]
)


class ModelConfigNotFoundError(Exception):
    """Raised when a ModelConfig record is not found."""


class ModelConfigConflictError(Exception):
    """Raised when deletion is blocked by a referencing AgentType."""


class ModelConfigService:
    """CRUD service for ModelConfig.

    Credentials (api_key) are AES-256 encrypted before storage using the
    platform vault (ENCRYPTION_MASTER_KEY).  Raw credentials are never
    persisted or returned.
    """

    async def create_model_config(
        self,
        *,
        display_name: str,
        provider_type: ModelProvider,
        api_base_url: str | None,
        api_key: str | None,
        enabled_models: list[str],
        db: AsyncSession,
    ) -> ModelConfig:
        encrypted_api_key: str | None = None
        if api_key:
            vault = get_vault()
            encrypted_api_key = vault.encrypt(json.dumps({"api_key": api_key}))

        config = ModelConfig(
            display_name=display_name,
            provider_type=provider_type,
            api_base_url=api_base_url,
            encrypted_api_key=encrypted_api_key,
            enabled_models=enabled_models,
        )
        db.add(config)
        await db.flush()
        await db.refresh(config)
        return config

    async def list_model_configs(
        self, db: AsyncSession, limit: int = 1000, offset: int = 0
    ) -> list[ModelConfig]:
        result = await db.execute(
            select(ModelConfig)
            .order_by(ModelConfig.display_name)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_model_config(
        self, config_id: uuid.UUID, db: AsyncSession
    ) -> ModelConfig:
        obj = await db.get(ModelConfig, config_id)
        if not obj:
            raise ModelConfigNotFoundError(f"ModelConfig {config_id} not found")
        return obj

    async def update_model_config(
        self,
        config_id: uuid.UUID,
        *,
        display_name: str | None,
        provider_type: ModelProvider | None,
        api_base_url: str | None,
        api_key: str | None,
        enabled_models: list[str] | None,
        db: AsyncSession,
    ) -> ModelConfig:
        obj = await self.get_model_config(config_id, db)

        if display_name is not None:
            obj.display_name = display_name
        if provider_type is not None:
            obj.provider_type = provider_type
        if api_base_url is not None:
            obj.api_base_url = api_base_url
        if api_key is not None:
            vault = get_vault()
            obj.encrypted_api_key = vault.encrypt(json.dumps({"api_key": api_key}))
        if enabled_models is not None:
            obj.enabled_models = enabled_models

        await db.flush()
        await db.refresh(obj)
        return obj

    async def delete_model_config(
        self, config_id: uuid.UUID, db: AsyncSession
    ) -> None:
        obj = await self.get_model_config(config_id, db)

        # Guard: refuse deletion if any AgentType uses a model from this config's enabled_models
        if obj.enabled_models:
            ref = await db.execute(
                select(AgentType).where(AgentType.model_id.in_(obj.enabled_models)).limit(1)
            )
            if ref.scalar_one_or_none() is not None:
                raise ModelConfigConflictError(
                    f"ModelConfig {config_id} has models in use by one or more AgentTypes and cannot be deleted"
                )

        await db.delete(obj)

    async def fetch_available_models(
        self, config_id: uuid.UUID, db: AsyncSession
    ) -> list[str]:
        """Return the enabled_models allowlist for the config.

        If enabled_models is non-empty, returns that list directly (no live API call).
        If empty, queries the live provider API to retrieve all available model names.
        """
        obj = await self.get_model_config(config_id, db)
        if obj.enabled_models:
            return list(obj.enabled_models)
        # Fallback: query live from provider
        return await self.list_models_for_config(config_id, db)

    async def list_models_for_config(
        self, config_id: uuid.UUID, db: AsyncSession
    ) -> list[str]:
        """Query the configured provider for its available model names.

        Returns a static list for providers that don't support programmatic
        model listing, and queries the live API when possible.

        Network or credential failures degrade to ``[]`` and log an error.
        """
        obj = await self.get_model_config(config_id, db)
        provider = obj.provider_type

        # Decrypt API key if stored
        api_key: str | None = None
        if obj.encrypted_api_key:
            vault = get_vault()
            try:
                creds: dict[str, Any] = json.loads(vault.decrypt(obj.encrypted_api_key))
                api_key = creds.get("api_key")
            except Exception as exc:
                logger.warning("Failed to decrypt credentials for ModelConfig %s: %s", config_id, exc)

        base_url = obj.api_base_url
        provider_value = provider.value if isinstance(provider, ModelProvider) else str(provider)

        try:
            if provider == ModelProvider.openai:
                models = await self._list_openai_models(api_key, base_url)
            elif provider == ModelProvider.anthropic:
                models = await self._list_anthropic_models(api_key, base_url)
            elif provider == ModelProvider.azure_openai:
                models = await self._list_azure_models(api_key, base_url)
            elif provider == ModelProvider.litellm_proxy:
                models = await self._list_litellm_models(api_key, base_url)
            elif provider == ModelProvider.gemini:
                models = await self._list_gemini_models(api_key, base_url)
            elif provider == ModelProvider.cohere:
                models = await self._list_cohere_models(api_key, base_url)  # type: ignore[assignment]
            elif provider_value in {
                "mistral",
                "groq",
                "together",
                "fireworks",
                "perplexity",
                "deepseek",
            }:
                # Six OpenAI-compatible providers share the same /models endpoint shape.
                # Fall back to each provider's default base URL when none is configured.
                compat_defaults: dict[str, str] = {
                    "mistral": "https://api.mistral.ai/v1",
                    "groq": "https://api.groq.com/openai/v1",
                    "together": "https://api.together.xyz/v1",
                    "fireworks": "https://api.fireworks.ai/inference/v1",
                    "perplexity": "https://api.perplexity.ai",
                    "deepseek": "https://api.deepseek.com/v1",
                }
                effective_url = base_url or compat_defaults.get(provider_value, "")
                models = await self._list_openai_compat_models(api_key, effective_url)
            else:
                models = []
        except Exception as exc:
            logger.error("Failed to list models for provider %s: %s", provider, exc)
            models = []

        return sorted(models)

    async def _list_openai_models(
        self, api_key: str | None, base_url: str | None
    ) -> list[str]:
        """Fetch model list from OpenAI-compatible endpoint.

        Implementation note: delegates to the shared ``_list_openai_compat_models``
        helper; the dedicated name is kept for the public API surface and for
        the existing unit-test patch points.
        """
        return await self._list_openai_compat_models(
            api_key=api_key,
            base_url=base_url or "https://api.openai.com/v1",
        )

    async def _list_litellm_models(
        self, api_key: str | None, base_url: str | None
    ) -> list[str]:
        """Fetch model list from a LiteLLM proxy /models endpoint.

        Like ``_list_openai_models``, delegates to the shared
        ``_list_openai_compat_models`` helper.
        """
        return await self._list_openai_compat_models(api_key=api_key, base_url=base_url)

    async def _list_openai_compat_models(
        self, api_key: str | None, base_url: str | None
    ) -> list[str]:
        """Fetch model list from any OpenAI-compatible ``/models`` endpoint.

        Used by all 9 OpenAI-compatible providers (the 3 incumbent
        ``openai`` / ``litellm_proxy`` / ``azure_openai`` and the 6 new
        ``mistral`` / ``groq`` / ``together`` / ``fireworks`` / ``perplexity`` /
        ``deepseek``).

        Returns ``[]`` if ``base_url`` is missing for a provider that does not
        have a hard-coded default — the caller handles the empty result and
        returns a 200 with the list, per the existing failure-degradation
        contract.
        """
        if not base_url:
            return []
        url = f"{base_url.rstrip('/')}/models"
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(timeout=10.0, verify=get_ssl_context()) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return [m["id"] for m in data.get("data", []) if isinstance(m.get("id"), str)]

    async def _list_anthropic_models(
        self, api_key: str | None, base_url: str | None
    ) -> list[str]:
        """Fetch model list from the Anthropic models API.

        Anthropic exposes GET /v1/models (added 2024) which returns a paginated
        list in the same ``{data: [{id, ...}]}`` shape as OpenAI.  Falls back
        to ANTHROPIC_FALLBACK_MODELS when the API is unreachable or no key is
        configured.
        """
        effective_base = (base_url or "https://api.anthropic.com/v1").rstrip("/")
        url = f"{effective_base}/models"
        headers: dict[str, str] = {"anthropic-version": "2023-06-01"}
        if api_key:
            headers["x-api-key"] = api_key
        else:
            return list(ANTHROPIC_FALLBACK_MODELS)

        try:
            async with httpx.AsyncClient(timeout=10.0, verify=get_ssl_context()) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                ids = [m["id"] for m in data.get("data", []) if isinstance(m.get("id"), str)]
                return ids if ids else list(ANTHROPIC_FALLBACK_MODELS)
        except Exception as exc:
            logger.warning("Anthropic models API unavailable, using fallback list: %s", exc)
            return list(ANTHROPIC_FALLBACK_MODELS)

    async def _list_azure_models(
        self, api_key: str | None, base_url: str | None
    ) -> list[str]:
        """Return static list of common Azure OpenAI deployment names.

        Azure OpenAI uses user-defined deployment names that don't map to a
        discoverable API, so a representative static list is the best option.
        """
        return ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4", "gpt-35-turbo"]

    async def _list_gemini_models(
        self, api_key: str | None, base_url: str | None
    ) -> list[str]:
        """Fetch model list from the Google Generative Language API.

        Calls GET /v1beta/models?key={api_key} and filters to models that
        support the ``generateContent`` method (i.e. chat/completion models).
        Falls back to GEMINI_FALLBACK_MODELS when the API is unreachable or
        no key is configured.
        """
        if not api_key:
            return list(GEMINI_FALLBACK_MODELS)

        effective_base = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        url = f"{effective_base}/models"

        try:
            async with httpx.AsyncClient(timeout=10.0, verify=get_ssl_context()) as client:
                resp = await client.get(url, params={"key": api_key})
                resp.raise_for_status()
                data = resp.json()
                ids = [
                    # Strip "models/" prefix that Gemini API returns
                    m["name"].removeprefix("models/")
                    for m in data.get("models", [])
                    if "generateContent" in m.get("supportedGenerationMethods", [])
                    and isinstance(m.get("name"), str)
                ]
                return ids if ids else list(GEMINI_FALLBACK_MODELS)
        except Exception as exc:
            logger.warning("Gemini models API unavailable, using fallback list: %s", exc)
            return list(GEMINI_FALLBACK_MODELS)

    async def _list_cohere_models(
        self, api_key: str | None, base_url: str | None
    ) -> list[str]:
        """Fetch model list from the Cohere models API.

        Calls GET /v2/models and filters to models that have a ``chat`` or
        ``generate`` endpoint.  Falls back to COHERE_FALLBACK_MODELS when the
        API is unreachable or no key is configured.
        """
        if not api_key:
            return list(COHERE_FALLBACK_MODELS)

        effective_base = (base_url or "https://api.cohere.com/v2").rstrip("/")
        url = f"{effective_base}/models"
        headers: dict[str, str] = {"Authorization": f"Bearer {api_key}"}

        try:
            async with httpx.AsyncClient(timeout=10.0, verify=get_ssl_context()) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                ids = [
                    m["name"]
                    for m in data.get("models", [])
                    if isinstance(m.get("name"), str)
                    and any(ep in m.get("endpoints", []) for ep in ("chat", "generate"))
                ]
                return ids if ids else list(COHERE_FALLBACK_MODELS)
        except Exception as exc:
            logger.warning("Cohere models API unavailable, using fallback list: %s", exc)
            return list(COHERE_FALLBACK_MODELS)
