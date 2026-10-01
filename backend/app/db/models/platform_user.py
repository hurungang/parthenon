"""SQLAlchemy model for PlatformUser."""
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base

class PlatformUser(Base):
    __tablename__ = "platform_users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sub: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Platform-issued password credential (Phase 10 self-serve accounts) —
    # stored HASHED only (bcrypt, same scheme as the super admin).  NULL
    # for OIDC-federated users, who authenticate exclusively via their
    # identity provider and are unaffected by password sign-in.
    password_credential: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    user_roles = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")
    user_groups = relationship("UserGroup", back_populates="user", cascade="all, delete-orphan")
    groups_owned = relationship("Group", back_populates="owner", cascade="all, delete-orphan")
    access_requests = relationship("AccessRequest", back_populates="user", cascade="all, delete-orphan", foreign_keys="[AccessRequest.user_id]")
    access_request_batches = relationship("AccessRequestBatch", back_populates="user", cascade="all, delete-orphan")
    # Tenant presence is expressed via memberships — PlatformUser stays tenant-agnostic
    tenant_memberships = relationship("TenantUserMembership", back_populates="user", cascade="all, delete-orphan")
