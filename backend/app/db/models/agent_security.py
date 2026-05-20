"""SQLAlchemy models for Agent Runtime Security Segregation.

New entities:
- AgentInstanceCertificate: X.509 certs issued to agent instances
- CertificateRevocationEntry: CRL for fast revocation lookups
- TokenRefreshLog: audit log for automatic token refresh attempts
- CertificateValidationLog: audit log for every certificate validation
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.db.models.agents import AgentIdentity, AgentType


# ── Enums ─────────────────────────────────────────────────────────────────────


class AgentCertificateStatus(str, enum.Enum):
    """Lifecycle status of an agent instance certificate."""

    active = "active"
    expired = "expired"
    revoked = "revoked"


class TokenRefreshOutcome(str, enum.Enum):
    """Outcome of an automatic OAuth token refresh attempt."""

    success = "success"
    failure = "failure"
    rate_limited = "rate_limited"


class CertificateValidationOutcome(str, enum.Enum):
    """Outcome of a certificate validation check."""

    valid = "valid"
    expired = "expired"
    revoked = "revoked"
    invalid_signature = "invalid_signature"


# ── Agent Instance Certificate ────────────────────────────────────────────────


class AgentInstanceCertificate(Base):
    """X.509 certificate issued to an agent instance for mTLS authentication.

    Certificates are valid for 24 hours; agents must renew at 80% lifetime (~19 h).
    Revoked certificates are retained (never deleted) for audit trail.
    """

    __tablename__ = "agent_instance_certificates"
    __table_args__ = (
        Index("ix_agent_instance_certs_serial_number", "serial_number"),
        Index("ix_agent_instance_certs_agent_type_id", "agent_type_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    instance_id: Mapped[str] = mapped_column(String(500), nullable=False)
    certificate_pem: Mapped[str] = mapped_column(Text, nullable=False)
    serial_number: Mapped[str] = mapped_column(String(200), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[AgentCertificateStatus] = mapped_column(
        Enum(AgentCertificateStatus, name="agent_certificate_status_enum"),
        nullable=False,
        default=AgentCertificateStatus.active,
    )
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
    agent_type: Mapped[AgentType] = relationship("AgentType")

    def __repr__(self) -> str:
        return (
            f"<AgentInstanceCertificate id={self.id} "
            f"serial={self.serial_number} status={self.status}>"
        )


# ── Certificate Revocation List Entry ─────────────────────────────────────────


class CertificateRevocationEntry(Base):
    """CRL entry for fast certificate revocation lookups during validation.

    Entries are immutable once created (never updated or deleted).
    Serial numbers are unique within the CRL.
    """

    __tablename__ = "certificate_revocation_entries"
    __table_args__ = (
        UniqueConstraint("serial_number", name="uq_crl_serial_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    serial_number: Mapped[str] = mapped_column(String(200), nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_by: Mapped[str] = mapped_column(String(500), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<CertificateRevocationEntry serial={self.serial_number}>"


# ── Token Refresh Audit Log ───────────────────────────────────────────────────


class TokenRefreshLog(Base):
    """Audit log for automatic OAuth token refresh attempts.

    Logged immediately after every refresh attempt (success or failure).
    Retries use exponential backoff: 1 s, 5 s, 15 s; max 3 attempts.
    """

    __tablename__ = "token_refresh_logs"
    __table_args__ = (
        Index("ix_token_refresh_logs_agent_identity_id", "agent_identity_id"),
        Index("ix_token_refresh_logs_attempted_at", "attempted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_identities.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    outcome: Mapped[TokenRefreshOutcome] = mapped_column(
        Enum(TokenRefreshOutcome, name="token_refresh_outcome_enum"),
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    agent_identity: Mapped[AgentIdentity] = relationship("AgentIdentity")

    def __repr__(self) -> str:
        return (
            f"<TokenRefreshLog id={self.id} "
            f"identity_id={self.agent_identity_id} outcome={self.outcome}>"
        )


# ── Certificate Validation Audit Log ─────────────────────────────────────────


class CertificateValidationLog(Base):
    """Audit log for every certificate validation by Control Center / Communication Hub.

    High-volume table (one entry per agent metadata request and per tool call).
    Indexed on serial_number and validated_at for audit queries.
    """

    __tablename__ = "certificate_validation_logs"
    __table_args__ = (
        Index("ix_cert_validation_logs_serial_number", "certificate_serial_number"),
        Index("ix_cert_validation_logs_validated_at", "validated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    certificate_serial_number: Mapped[str] = mapped_column(String(200), nullable=False)
    certificate_cn: Mapped[str] = mapped_column(String(500), nullable=False)
    validated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    outcome: Mapped[CertificateValidationOutcome] = mapped_column(
        Enum(CertificateValidationOutcome, name="cert_validation_outcome_enum"),
        nullable=False,
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    validated_by_service: Mapped[str] = mapped_column(String(200), nullable=False)
    requested_operation: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<CertificateValidationLog id={self.id} "
            f"serial={self.certificate_serial_number} outcome={self.outcome}>"
        )
