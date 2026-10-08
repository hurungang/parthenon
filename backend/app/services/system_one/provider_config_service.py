"""Provider config service — CRUD over SystemOneProviderConfig.

The API key is AES-256 encrypted on write via the CredentialVault and
decrypted ONLY inside the execution path (``get_active_provider``).
No method returns plaintext key material to API-layer callers.

Tenant containment: every lookup, mutation, and execution-time resolution is
scoped to the caller's tenant — tenant A's provider config (and its API key)
is never visible or usable from tenant B. ``tenant_id=None`` denotes the
single-tenant/root deployment, where provider rows are stored unscoped.
"""
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.credential_vault import get_vault
from app.db.models.system_one_provider_config import (
    SystemOneProviderConfig,
    SystemOneProviderType,
)
from app.schemas.system_one import (
    SystemOneProviderCreate,
    SystemOneProviderRead,
    SystemOneProviderUpdate,
    SystemOneStatus,
    SystemOneTestConnectionResult,
)

logger = logging.getLogger(__name__)


class SystemOneProviderError(Exception):
    """Raised when provider config operations fail."""


def _tenant_filter(tenant_id: uuid.UUID | None):
    """Exact tenant match, including the unscoped (None) single-tenant case."""
    if tenant_id is None:
        return SystemOneProviderConfig.tenant_id.is_(None)
    return SystemOneProviderConfig.tenant_id == tenant_id


class SystemOneProviderConfigService:
    """CRUD + encrypted key handling for System One provider configs."""

    async def create(
        self,
        db: AsyncSession,
        payload: SystemOneProviderCreate,
        tenant_id: uuid.UUID | None = None,
    ) -> SystemOneProviderConfig:
        config = SystemOneProviderConfig(
            tenant_id=tenant_id,
            provider_type=payload.provider_type,
            display_name=payload.display_name,
            base_url=payload.base_url,
            default_model=payload.default_model,
            encrypted_api_key=get_vault().encrypt(payload.api_key),
            enabled=payload.enabled,
            enabled_models=payload.enabled_models,
        )
        db.add(config)
        await db.flush()
        await db.refresh(config)
        logger.info(
            "Created System One provider config %s (%s, tenant %s)",
            config.id,
            config.provider_type,
            tenant_id,
        )
        return config

    async def update(
        self,
        db: AsyncSession,
        provider_id: uuid.UUID,
        payload: SystemOneProviderUpdate,
        tenant_id: uuid.UUID | None = None,
    ) -> SystemOneProviderConfig:
        config = await self.get(db, provider_id, tenant_id)
        if not config:
            raise SystemOneProviderError(f"Provider config {provider_id} not found")
        data = payload.model_dump(exclude_unset=True)
        new_key = data.pop("api_key", None)
        for field, value in data.items():
            setattr(config, field, value)
        if new_key is not None:
            config.encrypted_api_key = get_vault().encrypt(new_key)
        await db.flush()
        await db.refresh(config)
        return config

    async def delete(
        self,
        db: AsyncSession,
        provider_id: uuid.UUID,
        tenant_id: uuid.UUID | None = None,
    ) -> None:
        config = await self.get(db, provider_id, tenant_id)
        if not config:
            raise SystemOneProviderError(f"Provider config {provider_id} not found")
        await db.delete(config)

    async def get(
        self,
        db: AsyncSession,
        provider_id: uuid.UUID,
        tenant_id: uuid.UUID | None = None,
    ) -> SystemOneProviderConfig | None:
        result = await db.execute(
            select(SystemOneProviderConfig).where(
                SystemOneProviderConfig.id == provider_id,
                _tenant_filter(tenant_id),
            )
        )
        return result.scalars().first()

    async def list_all(
        self, db: AsyncSession, tenant_id: uuid.UUID | None = None
    ) -> list[SystemOneProviderConfig]:
        result = await db.execute(
            select(SystemOneProviderConfig)
            .where(_tenant_filter(tenant_id))
            .order_by(SystemOneProviderConfig.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_enabled(
        self, db: AsyncSession, tenant_id: uuid.UUID | None = None
    ) -> list[SystemOneProviderConfig]:
        result = await db.execute(
            select(SystemOneProviderConfig)
            .where(SystemOneProviderConfig.enabled.is_(True), _tenant_filter(tenant_id))
            .order_by(SystemOneProviderConfig.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_active_provider(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID | None = None,
        model: str | None = None,
    ) -> tuple[SystemOneProviderConfig, str]:
        """Resolve the active enabled provider WITHIN the tenant and DECRYPT
        its API key.

        This is the only decryption entry point — callers must be inside the
        execution path (Control Center decision engine) and must never log or
        serialize the returned plaintext key. Tenant containment: a provider
        configured in another tenant is never resolvable here.
        """
        query = (
            select(SystemOneProviderConfig)
            .where(SystemOneProviderConfig.enabled.is_(True), _tenant_filter(tenant_id))
            .order_by(SystemOneProviderConfig.created_at.desc())
        )
        if model:
            query = query.where(SystemOneProviderConfig.default_model == model)
        result = await db.execute(query)
        config = result.scalars().first()
        if not config:
            raise SystemOneProviderError(
                "No enabled System One provider is configured"
            )
        plaintext_key = get_vault().decrypt(config.encrypted_api_key)
        return config, plaintext_key

    async def get_status(
        self, db: AsyncSession, tenant_id: uuid.UUID | None = None
    ) -> SystemOneStatus:
        """Configured-model status for the decision tool authoring gate.

        Tenant-scoped: reports only the caller's tenant configuration.
        Returns provider/model identifiers only — never key material.
        """
        providers = await self.list_enabled(db, tenant_id)
        if not providers:
            return SystemOneStatus(configured=False)
        provider = providers[0]
        return SystemOneStatus(
            configured=True,
            provider_type=provider.provider_type,
            provider_id=provider.id,
            model=provider.default_model,
        )

    def to_read(self, config: SystemOneProviderConfig) -> SystemOneProviderRead:
        """Convert to a response DTO — guaranteed key-free."""
        return SystemOneProviderRead(
            id=config.id,
            provider_type=config.provider_type,
            display_name=config.display_name,
            base_url=config.base_url,
            default_model=config.default_model,
            enabled=config.enabled,
            enabled_models=config.enabled_models,
            has_api_key=bool(config.encrypted_api_key),
        )

    async def test_connection(
        self,
        db: AsyncSession,
        provider_id: uuid.UUID,
        tenant_id: uuid.UUID | None = None,
    ) -> SystemOneTestConnectionResult:
        """Lightweight validation probe against the provider base URL.

        Dispatches a trivial state/question via the existing TypeSafe client
        with the stored (call-time decrypted) key. Returns a status-only
        result — the key is never logged or returned.
        """
        import time

        from app.services.system_one.client import (
            SystemOneClientError,
            TypeSafeJevClient,
        )

        config = await self.get(db, provider_id, tenant_id)
        if not config:
            raise SystemOneProviderError(
                f"Provider config {provider_id} not found"
            )
        if not config.encrypted_api_key:
            return SystemOneTestConnectionResult(
                ok=False, message="No API key is stored for this provider"
            )

        _, api_key = await self.get_active_provider_by_config(config)
        model = config.default_model or "jev-latest"
        started = time.perf_counter()
        try:
            await TypeSafeJevClient().evaluate(
                base_url=config.base_url,
                api_key=api_key,
                model=model,
                state={"__probe": True},
                questions={
                    "connection_test": {
                        "type": "noul",
                        "instructions": (
                            "Connectivity validation probe; answer 0.5."
                        ),
                    }
                },
                timeout_seconds=15.0,
            )
        except SystemOneClientError as exc:
            return SystemOneTestConnectionResult(ok=False, message=str(exc)[:500])
        latency_ms = (time.perf_counter() - started) * 1000.0
        return SystemOneTestConnectionResult(
            ok=True,
            message="Connection succeeded",
            latency_ms=round(latency_ms, 1),
        )

    async def get_active_provider_by_config(
        self, config: SystemOneProviderConfig
    ) -> tuple[SystemOneProviderConfig, str]:
        """Decrypt the stored key for an already-resolved config (call time only)."""
        plaintext_key = get_vault().decrypt(config.encrypted_api_key)
        return config, plaintext_key
