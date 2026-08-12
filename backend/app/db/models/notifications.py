"""SQLAlchemy models for Notifications: NotificationChannel, ChannelProperty,
RecipientGroup, GroupChannelMapping, NotificationLog, NotificationEvent."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ChannelType(str, enum.Enum):
    """Type of notification channel - each type is specific and guaranteed to work."""

    SMTP = "SMTP"
    SENDGRID = "SENDGRID"
    RESEND = "RESEND"
    TEAMS_WEBHOOK = "TEAMS_WEBHOOK"
    SLACK_WEBHOOK = "SLACK_WEBHOOK"


class DeliveryStatus(str, enum.Enum):
    """Delivery outcome of a notification."""

    pending = "pending"
    delivered = "delivered"
    failed = "failed"


class SourceType(str, enum.Enum):
    """Source that triggered a notification."""

    SOP = "SOP"
    AGENT = "AGENT"
    MANUAL = "MANUAL"
    INTERVENE_REQUEST_CREATED = "intervene_request_created"
    INTERVENE_REQUEST_RESPONDED = "intervene_request_responded"


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
    properties: Mapped[list["ChannelProperty"]] = relationship(
        "ChannelProperty", back_populates="channel", cascade="all, delete-orphan"
    )
    group_mappings: Mapped[list["GroupChannelMapping"]] = relationship(
        "GroupChannelMapping", back_populates="channel", cascade="all, delete-orphan"
    )
    logs: Mapped[list["NotificationLog"]] = relationship(
        "NotificationLog",
        back_populates="channel",
        passive_deletes=True,
    )
    events: Mapped[list["NotificationEvent"]] = relationship(
        "NotificationEvent", back_populates="channel", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<NotificationChannel id={self.id} name={self.name} type={self.channel_type}>"


class ChannelProperty(Base):
    """Individual configuration key-value for a NotificationChannel. Secrets are encrypted."""

    __tablename__ = "channel_properties"
    __table_args__ = (UniqueConstraint("channel_id", "key", name="uq_channel_property_key"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    is_secret: Mapped[bool] = mapped_column(Boolean, nullable=False)
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
    channel: Mapped["NotificationChannel"] = relationship(
        "NotificationChannel", back_populates="properties"
    )

    def __repr__(self) -> str:
        return f"<ChannelProperty id={self.id} channel_id={self.channel_id} key={self.key}>"


class RecipientGroup(Base):
    """A named, addressable audience that maps to one or more notification channels."""

    __tablename__ = "recipient_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    channel_mappings: Mapped[list["GroupChannelMapping"]] = relationship(
        "GroupChannelMapping", back_populates="group", cascade="all, delete-orphan"
    )
    logs: Mapped[list["NotificationLog"]] = relationship(
        "NotificationLog", back_populates="group"
    )

    def __repr__(self) -> str:
        return f"<RecipientGroup id={self.id} slug={self.slug}>"


class GroupChannelMapping(Base):
    """Association between a RecipientGroup and a NotificationChannel with recipient properties.
    
    The recipient_properties JSON stores channel-specific recipient data:
    - For email channels (SMTP, SENDGRID, RESEND): {"recipients": ["user1@example.com", "user2@example.com"]}
    - For webhook channels (TEAMS_WEBHOOK, SLACK_WEBHOOK): {"channel_id": "C1234567", "user_ids": ["U123", "U456"]}
    """

    __tablename__ = "group_channel_mappings"
    __table_args__ = (UniqueConstraint("group_id", "channel_id", name="uq_group_channel"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recipient_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_properties: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="Channel-specific recipient data (e.g., email addresses, webhook IDs)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    group: Mapped["RecipientGroup"] = relationship(
        "RecipientGroup", back_populates="channel_mappings"
    )
    channel: Mapped["NotificationChannel"] = relationship(
        "NotificationChannel", back_populates="group_mappings"
    )

    def __repr__(self) -> str:
        return f"<GroupChannelMapping id={self.id} group_id={self.group_id} channel_id={self.channel_id}>"


class NotificationLog(Base):
    """Immutable delivery record for each channel attempt."""

    __tablename__ = "notification_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recipient_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, name="source_type_enum"), nullable=False
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
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
    group: Mapped["RecipientGroup | None"] = relationship(
        "RecipientGroup", back_populates="logs"
    )
    channel: Mapped["NotificationChannel"] = relationship(
        "NotificationChannel", back_populates="logs"
    )

    def __repr__(self) -> str:
        return f"<NotificationLog id={self.id} channel_id={self.channel_id} status={self.status}>"


class NotificationEvent(Base):
    """A record of a notification triggered by an agent or workflow.

    Superseded by NotificationLog. Retained for rollback safety during transition.
    """

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
