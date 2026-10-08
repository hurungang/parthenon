"""SQLAlchemy model for TagDefinition."""

import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Enum, DateTime, Text, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base

class TagScope(str, enum.Enum):
    global_scope = "global"
    resource_type = "resource_type"

class TagDefinition(Base):
    """A tag key definition. Tenant ownership is mandatory (migration
    b8c9d0e1f2a3 enforces NOT NULL at the DB level); tag keys are unique
    per tenant only — the NULL-tenant global variant was retired."""

    __tablename__ = "tag_definitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_tag_definitions_tenant_key"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[TagScope] = mapped_column(Enum(TagScope, name="tag_scope_enum"), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    tag_values = relationship("TagValue", back_populates="tag_definition", cascade="all, delete-orphan")
    
    @property
    def allowed_values(self):
        """Alias for tag_values to match Pydantic schema."""
        return self.tag_values
