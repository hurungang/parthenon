"""Agent Client Service — credential generation, hashing, resolution, audit.

A client credential is SHA-256 hashed at rest; the clear-text value is shown
once at creation and never retrievable. A client is NOT an identity: resolution
yields the target agent type + config, never an agent identity token.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
import string
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_client import (
    AgentClient,
    AgentClientAction,
    AgentClientKeyType,
    AgentClientStatus,
    AgentClientUsageLog,
)

logger = logging.getLogger(__name__)

KEY_ALPHABET = string.ascii_letters + string.digits
KEY_RANDOM_CHARS = 32

PREFIX_SECRET = "phn_cl_sk_"
PREFIX_PUBLISHABLE = "phn_cl_pk_"


def _prefix_for(key_type: AgentClientKeyType) -> str:
    """Return the readable prefix for a client credential type."""
    return PREFIX_PUBLISHABLE if key_type == AgentClientKeyType.publishable else PREFIX_SECRET


def hash_client_key(raw_key: str) -> str:
    """SHA-256 hash a raw client credential for storage and lookup."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_client_key(key_type: AgentClientKeyType) -> tuple[str, str, str]:
    """Generate a client credential.

    Returns (raw_key, key_hash, key_prefix). The raw key is shown once.
    """
    prefix = _prefix_for(key_type)
    random_part = "".join(secrets.choice(KEY_ALPHABET) for _ in range(KEY_RANDOM_CHARS))
    raw_key = f"{prefix}{random_part}"
    return raw_key, hash_client_key(raw_key), prefix


def slugify(name: str) -> str:
    """Derive a URL-safe slug from a client name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "client"


async def validate_client_from_hash(
    key_hash: str,
    db: AsyncSession,
) -> AgentClient | None:
    """Look up an active client by credential hash, or None."""
    result = await db.execute(
        select(AgentClient).where(
            AgentClient.key_hash == key_hash,
            AgentClient.status == AgentClientStatus.active,
        )
    )
    return result.scalar_one_or_none()


def is_client_expired(client: AgentClient) -> bool:
    """Return True when the client's expiry is in the past."""
    if client.expires_at is None:
        return False
    return client.expires_at <= datetime.now(timezone.utc)


async def create_client_usage_log(
    client_id: uuid.UUID,
    action: AgentClientAction,
    db: AsyncSession,
    success: bool = True,
    ip_address: str | None = None,
) -> None:
    """Append an audit record for a client invocation (never stores the credential)."""
    db.add(
        AgentClientUsageLog(
            client_id=client_id,
            action=action,
            success=success,
            ip_address=ip_address,
        )
    )
    await db.flush()


async def update_last_used_at(client_id: uuid.UUID, db: AsyncSession) -> None:
    """Stamp the client's last_used_at."""
    client = await db.get(AgentClient, client_id)
    if client is not None:
        client.last_used_at = datetime.now(timezone.utc)
        await db.flush()


async def check_duplicate_name(
    name: str,
    db: AsyncSession,
    tenant_id: uuid.UUID | None = None,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    """Return True when a client with this name already exists in the tenant."""
    stmt = select(AgentClient.id).where(AgentClient.name == name)
    if tenant_id is not None:
        stmt = stmt.where(AgentClient.tenant_id == tenant_id)
    if exclude_id is not None:
        stmt = stmt.where(AgentClient.id != exclude_id)
    return (await db.execute(stmt)).first() is not None


async def check_duplicate_slug(
    slug: str,
    db: AsyncSession,
    tenant_id: uuid.UUID | None = None,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    """Return True when a client with this slug already exists in the tenant."""
    stmt = select(AgentClient.id).where(AgentClient.slug == slug)
    if tenant_id is not None:
        stmt = stmt.where(AgentClient.tenant_id == tenant_id)
    if exclude_id is not None:
        stmt = stmt.where(AgentClient.id != exclude_id)
    return (await db.execute(stmt)).first() is not None
