"""SQLAlchemy model for Group."""
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Text, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base

class Group(Base):
    """A user group. Tenant ownership is mandatory (migration b8c9d0e1f2a3
    enforces NOT NULL at the DB level); names are unique per tenant only —
    the NULL-tenant global variant was retired."""

    __tablename__ = "groups"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_groups_tenant_name"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True)
    idp_claim_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    owner = relationship("PlatformUser", back_populates="groups_owned")
    group_roles = relationship("GroupRole", back_populates="group", cascade="all, delete-orphan")
    user_groups = relationship("UserGroup", back_populates="group", cascade="all, delete-orphan")
    access_requests = relationship("AccessRequest", back_populates="group", cascade="all, delete-orphan")
