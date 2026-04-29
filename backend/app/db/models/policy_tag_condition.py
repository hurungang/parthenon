"""SQLAlchemy model for PolicyTagCondition."""
import uuid
from sqlalchemy import String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base

class PolicyTagCondition(Base):
    __tablename__ = "policy_tag_conditions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_statement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("policy_statements.id", ondelete="CASCADE"), nullable=False)
    tag_key: Mapped[str] = mapped_column(String(100), nullable=False)
    tag_value: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_statement = relationship("PolicyStatement", back_populates="tag_conditions")
