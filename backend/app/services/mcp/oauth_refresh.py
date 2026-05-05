"""OAuth Token Refresh Service for MCP Sessions."""
import asyncio
import json
import logging
import ssl
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

try:
    import truststore
    _ssl_context: ssl.SSLContext | None = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
except ImportError:
    _ssl_context = None

from app.db.models.mcp_hub import McpSession
from app.core.credential_vault import get_vault

logger = logging.getLogger(__name__)


class OAuthRefreshService:
    """
    Service for refreshing OAuth access tokens using refresh tokens.
    
    Implements both proactive (before expiry) and reactive (after 401/403) refresh patterns.
    """

    def __init__(self):
        # Locks to prevent concurrent refreshes for the same session
        self._refresh_locks: dict[UUID, asyncio.Lock] = {}

    def _get_lock(self, session_id: UUID) -> asyncio.Lock:
        """Get or create a lock for a specific session."""
        if session_id not in self._refresh_locks:
            self._refresh_locks[session_id] = asyncio.Lock()
        return self._refresh_locks[session_id]

    async def refresh_access_token(
        self,
        session: McpSession,
        db: AsyncSession,
    ) -> bool:
        """
        Refresh the OAuth access token for a session.

        Args:
            session: MCP session with OAuth credentials
            db: Database session

        Returns:
            True if refresh succeeded, False otherwise
        """
        # Concurrency protection - only one refresh per session at a time
        lock = self._get_lock(session.id)
        async with lock:
            logger.info("Refreshing OAuth token for session %s", session.id)

            # Decrypt current credentials to get refresh_token
            if not session.encrypted_credentials:
                logger.error("Session %s has no encrypted credentials", session.id)
                return False

            try:
                vault = get_vault()
                creds_json = vault.decrypt(session.encrypted_credentials)
                creds = json.loads(creds_json)
            except Exception as exc:
                logger.error("Failed to decrypt credentials for session %s: %s", session.id, exc)
                return False

            refresh_token = creds.get("refresh_token")
            if not refresh_token:
                logger.error("Session %s has no refresh_token", session.id)
                return False

            # Get OAuth metadata (token_url, client_id, client_secret)
            if not session.oauth_metadata:
                logger.error("Session %s has no oauth_metadata", session.id)
                return False

            token_url = session.oauth_metadata.get("token_url")
            client_id = session.oauth_metadata.get("client_id")
            client_secret = session.oauth_metadata.get("client_secret")

            if not token_url or not client_id:
                logger.error("Session %s missing token_url or client_id in oauth_metadata", session.id)
                return False

            # Check if refresh token is expired
            if session.oauth_refresh_expires_at:
                now = datetime.now(tz=timezone.utc)
                if now >= session.oauth_refresh_expires_at:
                    logger.error("Refresh token expired for session %s", session.id)
                    session.is_active = False
                    await db.flush()
                    return False

            # Call token endpoint to refresh
            token_data: dict[str, str] = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
            }
            if client_secret:
                token_data["client_secret"] = client_secret

            try:
                async with httpx.AsyncClient(timeout=30.0, verify=_ssl_context or True) as client:
                    response = await client.post(
                        token_url,
                        data=token_data,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    
                    if not (200 <= response.status_code < 300):
                        logger.error(
                            "Token refresh failed for session %s: HTTP %s - %s",
                            session.id,
                            response.status_code,
                            response.text,
                        )
                        # If refresh fails with 400/401, mark session inactive
                        if response.status_code in (400, 401):
                            session.is_active = False
                            await db.flush()
                        return False

                    new_tokens: dict[str, Any] = response.json()
            except Exception as exc:
                logger.error("Token refresh request failed for session %s: %s", session.id, exc)
                return False

            # Update credentials with new tokens
            new_access_token = new_tokens.get("access_token")
            if not new_access_token:
                logger.error("Token refresh response missing access_token for session %s", session.id)
                return False

            # Check if refresh token was rotated (some providers rotate on each refresh)
            new_refresh_token = new_tokens.get("refresh_token") or refresh_token

            # Build updated credentials
            updated_creds = {
                "access_token": new_access_token,
                "refresh_token": new_refresh_token,
                "expires_in": new_tokens.get("expires_in"),
            }

            # Encrypt and update session
            try:
                updated_creds_json = json.dumps(updated_creds)
                updated_encrypted = vault.encrypt(updated_creds_json)
                session.encrypted_credentials = updated_encrypted

                # Update expiry timestamps
                now = datetime.now(tz=timezone.utc)
                expires_in = new_tokens.get("expires_in")
                if expires_in:
                    try:
                        session.oauth_expires_at = now + timedelta(seconds=int(expires_in))
                    except (ValueError, TypeError):
                        logger.warning("Invalid expires_in in refresh response: %s", expires_in)

                refresh_expires_in = new_tokens.get("refresh_expires_in")
                if refresh_expires_in:
                    try:
                        session.oauth_refresh_expires_at = now + timedelta(seconds=int(refresh_expires_in))
                    except (ValueError, TypeError):
                        logger.warning("Invalid refresh_expires_in in refresh response: %s", refresh_expires_in)

                await db.flush()
                logger.info("Successfully refreshed OAuth token for session %s", session.id)
                return True

            except Exception as exc:
                logger.error("Failed to update session credentials after refresh: %s", exc)
                return False

    async def check_and_refresh_if_needed(
        self,
        session: McpSession,
        db: AsyncSession,
        buffer_minutes: int = 5,
    ) -> bool:
        """
        Check if token is about to expire and refresh proactively if needed.

        Args:
            session: MCP session to check
            db: Database session
            buffer_minutes: Refresh if token expires within this many minutes (default: 5)

        Returns:
            True if no refresh was needed or refresh succeeded, False if refresh failed
        """
        # Only check OAuth sessions with expiry info
        if not session.oauth_expires_at:
            return True  # No expiry info, assume valid

        now = datetime.now(tz=timezone.utc)
        expiry_threshold = now + timedelta(minutes=buffer_minutes)

        # Check if token is expired or about to expire
        if session.oauth_expires_at <= expiry_threshold:
            logger.info(
                "OAuth token for session %s expires at %s (threshold: %s), refreshing...",
                session.id,
                session.oauth_expires_at,
                expiry_threshold,
            )
            return await self.refresh_access_token(session, db)

        # Token is still valid
        return True
