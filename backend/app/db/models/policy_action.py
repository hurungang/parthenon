"""SQLAlchemy model for PolicyAction."""
import uuid
from sqlalchemy import String, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base

class PolicyAction(Base):
    __tablename__ = "policy_actions"
    __table_args__ = (UniqueConstraint("policy_statement_id", "action", name="uq_policy_statement_action"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_statement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("policy_statements.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_statement = relationship("PolicyStatement", back_populates="actions")
