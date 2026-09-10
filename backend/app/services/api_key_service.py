"""API Key Service — business logic for API key generation, hashing, and validation.

Provides:
- Cryptographically random key generation with ``phn_sk_`` prefix
- SHA-256 hashing for safe storage and lookup
- Hash-based key lookup with status checking
- Identity token decryption for bound agent identities
- Permission set resolution from the bound agent role
- Usage log creation for audit trail
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import string
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.credential_vault import get_vault
from app.db.models.agent_api_key import AgentApiKey, ApiKeyStatus, ApiKeyUsageAction, ApiKeyUsageLog
from app.db.models.agents import AgentIdentity, AgentRole
from app.services.agents.permission_manager import get_shared_permission_manager
from app.services.token_refresh import check_token_expiration, refresh_oauth_token, TokenRefreshError

logger = logging.getLogger(__name__)

_permission_manager = get_shared_permission_manager()

KEY_PREFIX = "phn_sk_"
KEY_RANDOM_CHARS = 32
KEY_ALPHABET = string.ascii_letters + string.digits


def generate_api_key() -> tuple[str, str, str]:
    """Generate a cryptographically random API key.

    Returns:
        Tuple of (raw_key, key_hash, key_prefix).
        - raw_key: Full clear-text key (shown once, never stored).
        - key_hash: SHA-256 hex digest of the raw key (stored in DB).
        - key_prefix: Human-readable prefix for display (``phn_sk_``).
    """
    random_part = "".join(secrets.choice(KEY_ALPHABET) for _ in range(KEY_RANDOM_CHARS))
    raw_key = f"{KEY_PREFIX}{random_part}"
    key_hash = _hash_key(raw_key)
    return raw_key, key_hash, KEY_PREFIX


def _hash_key(raw_key: str) -> str:
    """SHA-256 hash a raw API key for storage and lookup."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def hash_api_key(raw_key: str) -> str:
    """Public wrapper for SHA-256 hashing (used by CH middleware)."""
    return _hash_key(raw_key)


async def validate_api_key_from_hash(
    key_hash: str,
    db: AsyncSession,
) -> AgentApiKey | None:
    """Look up an API key by hash, returning the record if active.

    Args:
        key_hash: SHA-256 hex digest of the raw key.
        db: Active async database session.

    Returns:
        AgentApiKey record if found and active, None otherwise.
    """
    result = await db.execute(
        select(AgentApiKey).where(
            AgentApiKey.key_hash == key_hash,
            AgentApiKey.status == ApiKeyStatus.active,
        )
    )
    return result.scalar_one_or_none()


def is_key_expired(api_key: AgentApiKey, now: datetime | None = None) -> bool:
    """Return ``True`` if the key carries an ``expires_at`` in the past.

    A ``None`` ``expires_at`` means the key never expires.
    """
    if api_key.expires_at is None:
        return False
    current = now or datetime.now(timezone.utc)
    expires = api_key.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires < current


async def create_api_key_usage_log(
    api_key_id: uuid.UUID,
    action: ApiKeyUsageAction,
    db: AsyncSession,
    *,
    tool_name: str | None = None,
    ip_address: str | None = None,
    success: bool = True,
) -> ApiKeyUsageLog:
    """Create an immutable usage log entry for audit trail."""
    log_entry = ApiKeyUsageLog(
        api_key_id=api_key_id,
        action=action,
        tool_name=tool_name,
        ip_address=ip_address,
        success=success,
    )
    db.add(log_entry)
    await db.flush()
    return log_entry


async def update_last_used_at(
    api_key_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """Update the last_used_at timestamp on the API key."""
    await db.execute(
        update(AgentApiKey)
        .where(AgentApiKey.id == api_key_id)
        .values(last_used_at=datetime.now(timezone.utc))
    )


async def resolve_identity_token(
    identity_id: uuid.UUID,
    db: AsyncSession,
) -> str:
    """Resolve and decrypt the identity token for an agent identity.

    Checks token expiration and refreshes if needed. Returns the plaintext
    access token for use by Communication Hub only — never exposed externally.

    Args:
        identity_id: UUID of the agent identity.
        db: Active async database session.

    Returns:
        Decrypted access token string.

    Raises:
        ValueError: If identity not found or token resolution fails.
    """
    identity = await db.get(AgentIdentity, identity_id)
    if not identity:
        raise ValueError(f"Agent identity {identity_id} not found")

    needs_refresh = await check_token_expiration(identity.id, db)
    if needs_refresh:
        logger.info("Token expired for identity %s; triggering refresh", identity.id)
        try:
            await refresh_oauth_token(identity.id, db)
            await db.refresh(identity)
        except TokenRefreshError as exc:
            logger.error("Token refresh failed for identity %s: %s", identity.id, exc)
            raise ValueError(f"Token refresh failed: {exc}")

    if not identity.access_token:
        raise ValueError(f"No access token for identity {identity_id}")

    vault = get_vault()
    try:
        return vault.decrypt(identity.access_token)
    except Exception as exc:
        logger.error("Failed to decrypt access token for identity %s: %s", identity.id, exc)
        raise ValueError(f"Token decryption failed: {exc}")


async def resolve_allowed_tools(
    role_id: uuid.UUID,
    db: AsyncSession,
) -> set[str]:
    """Resolve the complete set of allowed MCP tool identifiers for a role."""
    return await _permission_manager.calculate_allowed_tools(role_id, db)


async def get_role_name(role_id: uuid.UUID, db: AsyncSession) -> str | None:
    """Get the name of an agent role."""
    result = await db.execute(select(AgentRole.name).where(AgentRole.id == role_id))
    return result.scalar_one_or_none()


async def get_identity_name(identity_id: uuid.UUID, db: AsyncSession) -> str | None:
    """Get the name of an agent identity."""
    result = await db.execute(select(AgentIdentity.name).where(AgentIdentity.id == identity_id))
    return result.scalar_one_or_none()


async def check_duplicate_name(
    name: str,
    db: AsyncSession,
) -> bool:
    """Check if an API key with the given name already exists.

    Key names are unique platform-wide; the identity-role pair may have any
    number of keys with distinct names.
    """
    result = await db.execute(
        select(AgentApiKey.id).where(AgentApiKey.name == name)
    )
    return result.scalar_one_or_none() is not None
