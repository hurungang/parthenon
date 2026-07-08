"""SQLAlchemy 2 model for IdentityProviderConfigAudit."""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class IdentityProviderConfigAudit(Base):
    """Immutable audit log of administrative changes to identity provider configs.

    Records every create, update, test, and delete operation with a snapshot
    of previous values for security review and rollback reference.
    """

    __tablename__ = "identity_provider_config_audits"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("identity_provider_configs.id", ondelete="CASCADE"),
        nullable=False,
    )
    changed_by: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Identity of the admin who made the change (super admin username or OIDC subject)",
    )
    change_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="created | updated | tested | deleted",
    )
    changed_fields: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        comment="Array of field names that were modified",
    )
    previous_values: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Snapshot of config values before the change, for rollback reference",
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<IdentityProviderConfigAudit id={self.id} "
            f"config_id={self.config_id} "
            f"change_type={self.change_type}>"
        )
