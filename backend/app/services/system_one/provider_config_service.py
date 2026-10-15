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


class SystemOneProviderDuplicateError(SystemOneProviderError):
    """Raised when a provider display name already exists for the vendor
    type within the tenant (per-vendor display-name uniqueness)."""

    def __init__(self, provider_type: SystemOneProviderType, display_name: str) -> None:
        self.provider_type = provider_type
        self.display_name = display_name
        super().__init__(
            f"A provider named '{display_name}' already exists for vendor "
            f"type '{provider_type.value}' in this tenant"
        )


class SystemOneProviderInUseError(SystemOneProviderError):
    """Raised when deleting a provider that is still referenced by decision
    tools (via their selected decision model availability rows)."""

    def __init__(self, provider_display_name: str, blocking_tools: list[str]) -> None:
        self.blocking_tools = blocking_tools
        super().__init__(
            f"Provider '{provider_display_name}' cannot be deleted while "
            "decision tools reference its models: "
            + ", ".join(blocking_tools)
        )


class SystemOneProviderValidationError(SystemOneProviderError):
    """Raised when default_model / enabled_models combinations are invalid
    (``default_model`` must be one of the catalogued/enabled models)."""


def _tenant_filter(tenant_id: uuid.UUID | None):
    """Exact tenant match, including the unscoped (None) single-tenant case."""
    if tenant_id is None:
        return SystemOneProviderConfig.tenant_id.is_(None)
    return SystemOneProviderConfig.tenant_id == tenant_id


class SystemOneProviderConfigService:
    """CRUD + encrypted key handling for System One provider configs."""

    async def _ensure_display_name_available(
        self,
        db: AsyncSession,
        provider_type: SystemOneProviderType,
        display_name: str,
        tenant_id: uuid.UUID | None,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        """Reject duplicate display names per vendor type within one tenant."""
        query = select(SystemOneProviderConfig.id).where(
            SystemOneProviderConfig.provider_type == provider_type,
            SystemOneProviderConfig.display_name == display_name,
            _tenant_filter(tenant_id),
        )
        if exclude_id is not None:
            query = query.where(SystemOneProviderConfig.id != exclude_id)
        result = await db.execute(query)
        if result.scalars().first() is not None:
            raise SystemOneProviderDuplicateError(provider_type, display_name)

    async def create(
        self,
        db: AsyncSession,
        payload: SystemOneProviderCreate,
        tenant_id: uuid.UUID | None = None,
    ) -> SystemOneProviderConfig:
        await self._ensure_display_name_available(
            db, payload.provider_type, payload.display_name, tenant_id
        )
        # default_model must be one of the provider's catalogued models.
        enabled_models = [m for m in (payload.enabled_models or []) if m]
        if enabled_models and payload.default_model not in enabled_models:
            raise SystemOneProviderValidationError(
                f"default_model '{payload.default_model}' must be one of the "
                f"enabled models: {', '.join(enabled_models)}"
            )
        # Seed the catalogue at creation: the enabled-models list is the
        # authoritative catalogue; when omitted it is seeded with the
        # default model (an empty enable-list no longer silently means
        # "one mystery model").
        if not enabled_models:
            enabled_models = [payload.default_model]
        config = SystemOneProviderConfig(
            tenant_id=tenant_id,
            provider_type=payload.provider_type,
            display_name=payload.display_name,
            base_url=payload.base_url,
            default_model=payload.default_model,
            encrypted_api_key=get_vault().encrypt(payload.api_key),
            enabled=payload.enabled,
            enabled_models=enabled_models,
        )
        db.add(config)
        await db.flush()
        await db.refresh(config)
        await self._seed_availability_rows(db, config, enabled_models)
        logger.info(
            "Created System One provider config %s (%s, tenant %s)",
            config.id,
            config.provider_type,
            tenant_id,
        )
        return config

    async def _seed_availability_rows(
        self,
        db: AsyncSession,
        config: SystemOneProviderConfig,
        model_names: list[str],
    ) -> None:
        """Seed per-model availability rows (enabled by default) for the
        given catalogue names — rows are the authoritative catalogue going
        forward (seeded at creation/sync/import)."""
        from app.db.models.decision_model_availability import (
            DecisionModelAvailability,
            DecisionModelAvailabilityDisabledReason,
        )

        for model_name in dict.fromkeys(model_names):
            existing = await self._get_availability_row(db, config.id, model_name)
            if existing is not None:
                continue
            db.add(
                DecisionModelAvailability(
                    tenant_id=config.tenant_id,
                    model_name=model_name,
                    decision_model_provider_id=config.id,
                    is_disabled=False,
                    disabled_reason=(
                        DecisionModelAvailabilityDisabledReason.manual
                    ),
                )
            )
        await db.flush()

    async def _get_availability_row(
        self,
        db: AsyncSession,
        provider_id: uuid.UUID,
        model_name: str,
    ):
        from sqlalchemy import select as _select

        from app.db.models.decision_model_availability import (
            DecisionModelAvailability,
        )

        result = await db.execute(
            _select(DecisionModelAvailability).where(
                DecisionModelAvailability.decision_model_provider_id == provider_id,
                DecisionModelAvailability.model_name == model_name,
            )
        )
        return result.scalars().first()

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
        new_type = data.get("provider_type", config.provider_type)
        new_name = data.get("display_name", config.display_name)
        if (
            new_type != config.provider_type
            or new_name != config.display_name
        ):
            await self._ensure_display_name_available(
                db, new_type, new_name, tenant_id, exclude_id=config.id
            )
        # default_model validation on write: it must belong to the provider's
        # catalogue (the effective enabled-models list). Existing rows are
        # never re-validated on read (backward compat).
        new_default = data.get("default_model", config.default_model)
        new_enabled = data.get("enabled_models")
        effective_enabled = (
            [m for m in (new_enabled or []) if m]
            if new_enabled is not None
            else [m for m in (config.enabled_models or []) if m]
        )
        if effective_enabled and new_default not in effective_enabled:
            raise SystemOneProviderValidationError(
                f"default_model '{new_default}' must be one of the enabled "
                f"models: {', '.join(effective_enabled)}"
            )
        for field, value in data.items():
            setattr(config, field, value)
        if new_key is not None:
            config.encrypted_api_key = get_vault().encrypt(new_key)
        await db.flush()
        await db.refresh(config)
        if new_enabled is not None:
            await self._seed_availability_rows(
                db, config, [m for m in (new_enabled or []) if m]
            )
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
        blocking_tools = await self.list_blocking_decision_tools(
            db, config, tenant_id
        )
        if blocking_tools:
            raise SystemOneProviderInUseError(config.display_name, blocking_tools)
        await db.delete(config)

    async def list_blocking_decision_tools(
        self,
        db: AsyncSession,
        config: SystemOneProviderConfig,
        tenant_id: uuid.UUID | None = None,
    ) -> list[str]:
        """Names of decision tools that still reference one of this
        provider's model availability rows (delete-blocking references)."""
        from app.db.models.decision_tools import DecisionTool
        from app.db.models.decision_model_availability import (
            DecisionModelAvailability,
        )

        result = await db.execute(
            select(DecisionTool.name)
            .join(
                DecisionModelAvailability,
                DecisionTool.decision_model_availability_id
                == DecisionModelAvailability.id,
            )
            .where(
                DecisionModelAvailability.decision_model_provider_id == config.id,
            )
        )
        return [name for name in result.scalars().all()]

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
        """Backward-compat wrapper over the multi-provider lookup.

        Resolves the most recently created enabled provider WITHIN the
        tenant and DECRYPTS its API key. New code should resolve the
        tool's selected model via the decision model catalogue service
        instead (``DecisionModelCatalogueService.resolve_selection``).

        This is a decryption entry point — callers must be inside the
        execution path (Control Center decision engine) and must never log
        or serialize the returned plaintext key. Tenant containment: a
        provider configured in another tenant is never resolvable here.
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
                "No enabled Decision Model provider is configured"
            )
        plaintext_key = get_vault().decrypt(config.encrypted_api_key)
        return config, plaintext_key

    async def get_status(
        self, db: AsyncSession, tenant_id: uuid.UUID | None = None
    ) -> SystemOneStatus:
        """Multi-provider status for the decision tool authoring gate.

        Tenant-scoped: reports only the caller's tenant configuration.
        Configured when ANY enabled provider exists; reports the most
        recent one. Returns provider/model identifiers only — never key
        material.
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
            provider_count=len(providers),
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
            get_system_one_client,
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
            await get_system_one_client(config.provider_type.value).evaluate(
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

    async def list_vendor_models(
        self,
        db: AsyncSession,
        provider_id: uuid.UUID,
        tenant_id: uuid.UUID | None = None,
    ) -> list[str]:
        """Discover the vendor's model catalogue via its OpenAI-compatible
        ``GET {base_url}/models`` endpoint.

        Reuses the provider's decrypted credential at call time only — the
        returned list carries model ids, never key material. Raises
        ``SystemOneProviderError`` (wrapping ``SystemOneClientError``) with
        an actionable message when the key is missing or the vendor is
        unreachable / not OpenAI-compatible.
        """
        from app.services.system_one.client import (
            SystemOneClientError,
            list_vendor_models,
        )

        config = await self.get(db, provider_id, tenant_id)
        if not config:
            raise SystemOneProviderError(
                f"Provider config {provider_id} not found"
            )
        if not config.encrypted_api_key:
            raise SystemOneProviderError(
                "No API key is stored for this provider — save a key first"
            )
        _, api_key = await self.get_active_provider_by_config(config)
        try:
            return await list_vendor_models(
                base_url=config.base_url, api_key=api_key
            )
        except SystemOneClientError as exc:
            raise SystemOneProviderError(str(exc)) from exc

    async def import_vendor_models(
        self,
        db: AsyncSession,
        provider_id: uuid.UUID,
        model_names: list[str],
        tenant_id: uuid.UUID | None = None,
    ) -> SystemOneProviderConfig:
        """Import vendor model ids as the provider's catalogue.

        Seeds enabled availability rows for each id and merges them into
        ``enabled_models`` (the authoritative catalogue). ``default_model``
        is kept valid: if it is not part of the imported set it is appended
        so the catalogue always contains the default. Write-only validation —
        existing data is never rewritten on read.
        """
        config = await self.get(db, provider_id, tenant_id)
        if not config:
            raise SystemOneProviderError(
                f"Provider config {provider_id} not found"
            )
        cleaned = list(dict.fromkeys(m.strip() for m in model_names if m.strip()))
        if not cleaned:
            raise SystemOneProviderValidationError(
                "No models to import — the vendor returned an empty list"
            )
        current = [m for m in (config.enabled_models or []) if m]
        merged = list(dict.fromkeys(current + cleaned))
        if config.default_model not in merged:
            merged.append(config.default_model)
        config.enabled_models = merged
        await db.flush()
        await self._seed_availability_rows(db, config, merged)
        await db.refresh(config)
        logger.info(
            "Imported %d vendor models into provider %s (tenant %s)",
            len(cleaned),
            config.display_name,
            tenant_id,
        )
        return config
