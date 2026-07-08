"""SQLAlchemy 2 model for SuperAdminCredentials (single-row resource)."""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class SuperAdminCredentials(Base):
    """Stores the built-in super admin bootstrap credentials.

    This is a single-row resource — at most one set of credentials exists.
    Credentials are initialised from environment variables on first launch and
    can be updated via the admin UI or env vars. When disabled, the super
    admin login is refused regardless of password correctness.
    """

    __tablename__ = "super_admin_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(
        String(200),
        unique=True,
        nullable=False,
        comment="Immutable super admin username; sourced from SUPER_ADMIN_USERNAME env var",
    )
    hashed_password: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Argon2id or bcrypt hash of the super admin password",
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=sa.text("true"),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of the most recent super admin authentication",
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
            f"<SuperAdminCredentials id={self.id} "
            f"username={self.username} "
            f"is_enabled={self.is_enabled}>"
        )
