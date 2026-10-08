"""SQLAlchemy model for AgentDataType."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class AgentDataType(Base):
    """Central registry of reusable output schemas for agent types.

    Each type defines a named collection of typed fields that one or more agent
    types can reference as their output contract. Tenant ownership is mandatory
    (no NULL "platform-shared types"); name and slug are unique per tenant only
    — the NULL-tenant global uniqueness variants were retired. NOT NULL on
    ``tenant_id`` is enforced at the database level by migration
    ``b8c9d0e1f2a3``; the ORM column stays nullable for legacy paths.
    """

    __tablename__ = "agent_data_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_agent_data_types_tenant_name"),
        UniqueConstraint("tenant_id", "slug", name="uq_agent_data_types_tenant_slug"),
        Index("ix_agent_data_types_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    fields: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    agent_types: Mapped[list["AgentType"]] = relationship(
        "AgentType", back_populates="output_data_type"
    )

    def __repr__(self) -> str:
        return f"<AgentDataType id={self.id} name={self.name}>"
