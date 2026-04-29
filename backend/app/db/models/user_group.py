"""SQLAlchemy model for UserGroup (junction)."""
import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base

class UserGroup(Base):
    __tablename__ = "user_groups"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="CASCADE"), primary_key=True)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    join_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    user = relationship("PlatformUser", back_populates="user_groups")
    group = relationship("Group", back_populates="user_groups")
