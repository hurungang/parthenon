"""SQLAlchemy model for TagDefinition."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class TagScope(str, enum.Enum):
    global_scope = "global"
    resource_type = "resource_type"


class TagDefinition(Base):
    __tablename__ = "tag_definitions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    scope: Mapped[TagScope] = mapped_column(Enum(TagScope, name="tag_scope_enum"), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    tag_values = relationship(
        "TagValue", back_populates="tag_definition", cascade="all, delete-orphan"
    )

    @property
    def allowed_values(self):
        """Alias for tag_values to match Pydantic schema."""
        return self.tag_values
