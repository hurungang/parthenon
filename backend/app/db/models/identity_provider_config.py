"""SQLAlchemy 2 model for IdentityProviderConfig."""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class IdentityProviderConfig(Base):
    """Stores the active identity provider (IdP) configuration."""

    __tablename__ = "identity_provider_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="keycloak_bundled | keycloak_external | azure_entraid"
    )
    oidc_provider_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    client_id: Mapped[str] = mapped_column(String(500), nullable=False)
    client_secret: Mapped[str | None] = mapped_column(
        String(2048), nullable=True, comment="AES-256-GCM encrypted client secret"
    )
    realm_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    audience: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_setup_complete: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=sa.text("false"),
    )
    setup_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    setup_completed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("identities.id", ondelete="SET NULL"),
        nullable=True,
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
            f"provider_type={self.provider_type} "
            f"is_setup_complete={self.is_setup_complete}>"
        )
