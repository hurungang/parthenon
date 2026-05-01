"""SQLAlchemy 2 model for IdentityProviderSetupState (single-row sentinel)."""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class IdentityProviderSetupState(Base):
    """Single-row sentinel that tracks whether identity provider setup is complete.

    At most one row should exist in this table at any time.
    The row is created by the Bootstrap Service on first use.
    """

    __tablename__ = "identity_provider_setup_state"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    is_setup_complete: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=sa.text("false"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("identities.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<IdentityProviderSetupState id={self.id} is_setup_complete={self.is_setup_complete}>"
        )
