"""Gateway Endpoint Registry — persists and resolves gateway routes per agent type."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class GatewayRoute(Base):
    """Persisted route mapping for an agent type's gateway endpoint."""

    __tablename__ = "gateway_routes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False
    )
    http_base_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<GatewayRoute agent_type_id={self.agent_type_id} path={self.http_base_path}>"


class GatewayEndpointRegistry:
    """Persists and resolves gateway route mappings per agent type."""

    async def register(self, agent_type_id: Any, db: AsyncSession) -> GatewayRoute:
        """Create or return the gateway route for an agent type."""
        existing = await self.resolve(agent_type_id, db)
        if existing:
            return existing

        http_base_path = f"/gateway/{agent_type_id}"
        route = GatewayRoute(
            agent_type_id=agent_type_id,
            http_base_path=http_base_path,
        )
        db.add(route)
        await db.flush()
        await db.refresh(route)
        return route

    async def resolve(self, agent_type_id: Any, db: AsyncSession) -> GatewayRoute | None:
        """Resolve a gateway route by agent type ID."""
        result = await db.execute(
            select(GatewayRoute).where(GatewayRoute.agent_type_id == agent_type_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self, db: AsyncSession) -> list[GatewayRoute]:
        """List all registered gateway routes."""
        result = await db.execute(select(GatewayRoute).order_by(GatewayRoute.created_at.desc()))
        return list(result.scalars().all())
