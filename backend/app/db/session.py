"""Async SQLAlchemy session factory."""
import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# In the test environment every async test runs on its own event loop;
# pooled asyncpg connections are loop-bound and a pooled connection from
# a previous test's loop fails with "attached to a different loop".
# NullPool (fresh connection per checkout) keeps the test suite safe;
# production keeps the configured pool.
if settings.environment == "test":
    _ENGINE_KWARGS: dict = {"poolclass": NullPool}
else:
    _ENGINE_KWARGS = {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
    }

engine = create_async_engine(
    settings.computed_database_url,
    pool_pre_ping=True,
    echo=settings.debug,
    **_ENGINE_KWARGS,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Declarative base for all SQLAlchemy models."""

    pass


async def _maybe_apply_request_tenant_scope(
    session: AsyncSession, request: Request | None
) -> None:
    """Bind the request's tenant scope to the session (CC only).

    Two resolution paths, both fail-closed:
    - Request-scoped (browser/API traffic): the tenant context was set by
      ``TenantResolutionMiddleware`` (multi-tenancy on) — apply it.
    - Internal service-to-service paths (``/api/v1/internal/*``): those
      bypass tenant resolution; the tenant arrives as SIGNED headers from
      AR/CH (verify-if-present).  A present-but-invalid set is rejected
      with 401 before any query runs.

    With the switch off neither path applies and behaviour is
    byte-for-byte unchanged.
    """
    if request is None:
        return
    from app.core.tenant_context import (
        get_tenant_context,
        is_tenancy_enabled,
    )
    from app.db.tenant_scoping import apply_tenant_scope, register_tenant_scope_listener

    context = get_tenant_context(request)
    if context.is_set and is_tenancy_enabled(request):
        # Phase 11: a resolved context alone no longer implies scoping —
        # when the switch is OFF the context is the ROOT default and the
        # data plane stays unscoped (legacy rows pre-adoption carry no
        # tenant references).  Quotas stay switch-gated for the same
        # reason (tiers are a SaaS concept — recorded decision).
        register_tenant_scope_listener()
        apply_tenant_scope(session, context.tenant_id, request)
        return

    # Internal path: verify the signed tenant headers (verify-if-present).
    from app.core.tenant_signature import (
        TenantSignatureError,
        verify_request_tenant_context,
    )

    try:
        internal_context = verify_request_tenant_context(request.headers)
    except TenantSignatureError as exc:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=401,
            detail=f"Invalid tenant context headers: {exc}",
        )
    if internal_context is None:
        return  # no tenant headers — single-tenant internal traffic
    register_tenant_scope_listener()
    apply_tenant_scope(session, internal_context.tenant_id, request)


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency providing an async database session.

    When the request carries a resolved tenant context (multi-tenancy
    on), the session is scoped at this single choke point so every ORM
    query is constrained to the request's tenant — no feature can issue
    an unscoped query.  See app.db.tenant_scoping.
    """
    session = AsyncSessionLocal()
    try:
        await _maybe_apply_request_tenant_scope(session, request)
        yield session
        # Cross-tenant probes observed during the request become
        # security-relevant audit events (app.db.tenant_scoping).
        from app.db.tenant_scoping import flush_scope_miss_audits

        await flush_scope_miss_audits(session)
        await session.commit()
    except (asyncio.CancelledError, GeneratorExit):
        await session.rollback()
    except Exception:
        await session.rollback()
        raise
    finally:
        try:
            await session.close()
        except (asyncio.CancelledError, GeneratorExit):
            # anyio cancellation scopes can override asyncio.shield(), so
            # session.close() (which returns the connection to the pool) may
            # get CancelledError when the client disconnects from a streaming
            # response while the middleware's cancellation scope is active.
            logger.debug("Session close interrupted by task cancellation")


DbSession = Annotated[AsyncSession, Depends(get_db)]
