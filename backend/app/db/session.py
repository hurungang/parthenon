"""Async SQLAlchemy session factory."""
import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    echo=settings.debug,
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


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency providing an async database session."""
    session = AsyncSessionLocal()
    try:
        yield session
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
