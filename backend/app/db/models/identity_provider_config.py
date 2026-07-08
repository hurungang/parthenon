"""SQLAlchemy 2 model for IdentityProviderConfig."""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class IdentityProviderConfig(Base):
    """Stores an OIDC identity provider configuration for user or agent auth.

    Each scope (user / agent) has at most one enabled config.
    Supports any OIDC-compliant provider via ``oidc_generic``, plus first-class
    support for Keycloak and Azure EntraID.
    """

    __tablename__ = "identity_provider_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
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
