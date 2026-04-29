"""SQLAlchemy model for TagValue."""
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base

class TagValue(Base):
    __tablename__ = "tag_values"
    __table_args__ = (UniqueConstraint("tag_definition_id", "value", name="uq_tagdef_value"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tag_definition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tag_definitions.id", ondelete="CASCADE"), nullable=False)
    value: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    tag_definition = relationship("TagDefinition", back_populates="tag_values")
