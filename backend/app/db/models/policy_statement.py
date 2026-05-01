"""SQLAlchemy model for PolicyStatement."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class PolicyEffect(str, enum.Enum):
    allow = "allow"
    deny = "deny"


class PolicyStatement(Base):
    __tablename__ = "policy_statements"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    effect: Mapped[PolicyEffect] = mapped_column(
        Enum(PolicyEffect, name="policy_effect_enum"), nullable=False
    )
    module: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    role = relationship("Role", back_populates="policy_statements")
    actions = relationship(
        "PolicyAction", back_populates="policy_statement", cascade="all, delete-orphan"
    )
    resources = relationship(
        "PolicyResource", back_populates="policy_statement", cascade="all, delete-orphan"
    )
    tag_conditions = relationship(
        "PolicyTagCondition", back_populates="policy_statement", cascade="all, delete-orphan"
    )
