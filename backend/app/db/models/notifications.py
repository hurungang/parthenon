"""SQLAlchemy models for Notifications: NotificationChannel, NotificationEvent."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ChannelType(str, enum.Enum):
    """Type of notification channel."""

    email = "email"
    slack = "slack"
    teams = "teams"
    webhook = "webhook"


class DeliveryStatus(str, enum.Enum):
    """Delivery outcome of a notification."""

    pending = "pending"
    delivered = "delivered"
    failed = "failed"


class NotificationChannel(Base):
    """A configured outbound notification destination."""

    __tablename__ = "notification_channels"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    channel_type: Mapped[ChannelType] = mapped_column(
        Enum(ChannelType, name="channel_type_enum"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # AES-encrypted channel-specific configuration (API keys, URLs, etc.)
    encrypted_config: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    events: Mapped[list["NotificationEvent"]] = relationship(
        "NotificationEvent", back_populates="channel", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<NotificationChannel id={self.id} name={self.name} type={self.channel_type}>"


class NotificationEvent(Base):
    """A record of a notification triggered by an agent or workflow."""

    __tablename__ = "notification_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    recipient: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="delivery_status_enum"),
        nullable=False,
        default=DeliveryStatus.pending,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    channel: Mapped["NotificationChannel"] = relationship(
        "NotificationChannel", back_populates="events"
    )

    def __repr__(self) -> str:
        return f"<NotificationEvent id={self.id} channel_id={self.channel_id} status={self.status}>"
