"""ModelConfigService — CRUD for ModelConfig with AES-256 credential encryption."""
import json
import uuid
import logging
from typing import Any

from sqlalchemy import select

from app.core.credential_vault import get_vault
from app.core.ssl_context import get_ssl_context
from app.db.models.agents import AgentType, ModelConfig, ModelProvider
from app.db.session import AsyncSession

logger = logging.getLogger(__name__)


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

    async def list_model_configs(self, db: AsyncSession) -> list[ModelConfig]:
        result = await db.execute(
            select(ModelConfig).order_by(ModelConfig.display_name)
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
        """
        import httpx

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

        try:
            if provider == ModelProvider.openai:
                models = await self._list_openai_models(api_key, base_url)
            elif provider == ModelProvider.anthropic:
                # Anthropic doesn't have a public models endpoint — return well-known models
                models = [
                    "claude-opus-4-5",
                    "claude-sonnet-4-5",
                    "claude-haiku-4-5",
                    "claude-3-5-sonnet-latest",
                    "claude-3-5-haiku-latest",
                ]
            elif provider == ModelProvider.azure_openai:
                models = await self._list_azure_models(api_key, base_url)
            elif provider == ModelProvider.litellm_proxy:
                models = await self._list_litellm_models(api_key, base_url)
            else:
                models = []
        except Exception as exc:
            logger.error("Failed to list models for provider %s: %s", provider, exc)
            models = []

        return sorted(models)

    async def _list_openai_models(
        self, api_key: str | None, base_url: str | None
    ) -> list[str]:
        """Fetch model list from OpenAI-compatible endpoint."""
        import httpx

        url = f"{base_url.rstrip('/')}/models" if base_url else "https://api.openai.com/v1/models"
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(timeout=10.0, verify=get_ssl_context()) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return [m["id"] for m in data.get("data", []) if isinstance(m.get("id"), str)]

    async def _list_azure_models(
        self, api_key: str | None, base_url: str | None
    ) -> list[str]:
        """Return static list of common Azure OpenAI deployment names."""
        return ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4", "gpt-35-turbo"]

    async def _list_litellm_models(
        self, api_key: str | None, base_url: str | None
    ) -> list[str]:
        """Fetch model list from a LiteLLM proxy /models endpoint."""
        import httpx

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
