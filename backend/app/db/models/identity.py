"""SQLAlchemy models for Identity, Role, Permission, and RolePermission."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class RoleType(str, enum.Enum):
    """Role type determines which principals can be assigned to it."""

    user = "user"
    agent = "agent"
    both = "both"


class Role(Base):
    """Named set of permissions; assigned to identities."""

    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    role_type: Mapped[RoleType] = mapped_column(
        Enum(RoleType, name="role_type_enum"), nullable=False, default=RoleType.user
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
    permissions: Mapped[list["RolePermission"]] = relationship(
        "RolePermission", back_populates="role", cascade="all, delete-orphan"
    )
    identities: Mapped[list["Identity"]] = relationship("Identity", back_populates="role")

    # Permission-management relationships (added in user-permission-management change)
    policy_statements: Mapped[list["PolicyStatement"]] = relationship(  # type: ignore[name-defined]
        "PolicyStatement", back_populates="role", cascade="all, delete-orphan"
    )
    user_roles: Mapped[list["UserRole"]] = relationship(  # type: ignore[name-defined]
        "UserRole", back_populates="role", cascade="all, delete-orphan"
    )
    group_roles: Mapped[list["GroupRole"]] = relationship(  # type: ignore[name-defined]
        "GroupRole", back_populates="role", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Role id={self.id} name={self.name} type={self.role_type}>"


class Permission(Base):
    """A grantable action on a named resource."""

    __tablename__ = "permissions"
    __table_args__ = (UniqueConstraint("resource", "action", name="uq_permission_resource_action"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    resource: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    role_permissions: Mapped[list["RolePermission"]] = relationship(
        "RolePermission", back_populates="permission", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Permission id={self.id} name={self.name}>"


class RolePermission(Base):
    """Assignment linking a Role to a Permission."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    role: Mapped["Role"] = relationship("Role", back_populates="permissions")
    permission: Mapped["Permission"] = relationship("Permission", back_populates="role_permissions")

    def __repr__(self) -> str:
        return f"<RolePermission role_id={self.role_id} permission_id={self.permission_id}>"


class IdentityType(str, enum.Enum):
    """Whether this identity represents a human user or an AI agent."""

    user = "user"
    agent = "agent"


class Identity(Base):
    """An external principal registered in the platform (user or agent)."""

    __tablename__ = "identities"
    __table_args__ = (
        Index("ix_identities_idp_subject", "idp_subject"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Subject claim from the OIDC provider
    subject: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    identity_type: Mapped[IdentityType] = mapped_column(
        Enum(IdentityType, name="identity_type_enum"),
        nullable=False,
        default=IdentityType.user,
    )
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Subject identifier from the external identity provider (e.g. Keycloak user ID)
    idp_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
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
    role: Mapped["Role | None"] = relationship("Role", back_populates="identities")

    def __repr__(self) -> str:
        return f"<Identity id={self.id} subject={self.subject} type={self.identity_type}>"
