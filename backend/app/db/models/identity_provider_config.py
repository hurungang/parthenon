"""SQLAlchemy 2 model for IdentityProviderConfig."""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.services.tenancy.default_tenant_roles import DefaultTenantRole


class IdentityProviderConfig(Base):
    """Stores an OIDC identity provider configuration for user or agent auth.

    Each scope (user / agent) has at most one enabled config.
    Supports any OIDC-compliant provider via ``oidc_generic``, plus first-class
    support for Keycloak and Azure EntraID.
    """

    __tablename__ = "identity_provider_configs"
    __table_args__ = (
        sa.Index("ix_identity_provider_configs_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Per-tenant OIDC binding: each tenant registers its own provider; sign-in
    # credentials are tenant-bound (NULL while multi-tenancy is disabled).
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider_scope: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="user | agent"
    )
    provider_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="oidc_generic | keycloak | azure_entraid"
    )
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    issuer_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    client_id: Mapped[str] = mapped_column(String(500), nullable=False)
    ui_client_id: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="Public OIDC client ID for frontend PKCE login (no secret). Only used for user scope."
    )
    encrypted_client_secret: Mapped[str | None] = mapped_column(
        String(2048), nullable=True, comment="AES-256-GCM encrypted client secret"
    )
    scopes: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="openid profile email",
        server_default=sa.text("'openid profile email'"),
    )
    claim_mappings: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="OIDC claim to platform field mappings (e.g. {'sub': 'subject'})"
    )
    # JIT default tenant role (FIX-20260930-075014): when set, a user's
    # FIRST OIDC sign-in to a tenant (via a provider slot resolvable for
    # that tenant) is admitted with this seeded preset role — active
    # membership + role grant.  NULL → no JIT (sign-in without membership
    # is rejected with the no_access_to_workspace 403).  Non-native enum:
    # stored as VARCHAR + CHECK, one of the four preset keys.
    default_tenant_role: Mapped[str | None] = mapped_column(
        Enum(
            DefaultTenantRole,
            name="default_tenant_role_enum",
            native_enum=False,
            length=50,
        ),
        nullable=True,
        comment="JIT tenant role preset key for first OIDC sign-in (nullable)",
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=sa.text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<IdentityProviderConfig id={self.id} "
            f"provider_scope={self.provider_scope} "
            f"provider_type={self.provider_type} "
            f"is_enabled={self.is_enabled}>"
        )
