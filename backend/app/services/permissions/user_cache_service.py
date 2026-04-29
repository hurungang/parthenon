"""User Cache Service — upserts PlatformUser records from OIDC token claims."""
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.platform_user import PlatformUser

logger = logging.getLogger(__name__)


class UserCacheService:
    """Upserts PlatformUser records on every successful JWT validation."""

    async def upsert_user(
        self,
        db: AsyncSession,
        sub: str,
        email: str,
        display_name: str,
    ) -> PlatformUser:
        """Insert PlatformUser on first encounter; update last_seen_at on subsequent encounters.

        Sets first_seen_at and last_seen_at on creation.
        Updates only last_seen_at on subsequent calls.
        """
        result = await db.execute(
            select(PlatformUser).where(PlatformUser.sub == sub)
        )
        user = result.scalar_one_or_none()

        if user is None:
            now = datetime.utcnow()
            user = PlatformUser(
                sub=sub,
                email=email,
                display_name=display_name,
                first_seen_at=now,
                last_seen_at=now,
            )
            db.add(user)
            logger.info("Created new PlatformUser for sub=%s", sub)
        else:
            user.last_seen_at = datetime.utcnow()
            # Update email/display_name if they've changed in the IdP
            if email:
                user.email = email
            if display_name:
                user.display_name = display_name

        await db.flush()
        await db.refresh(user)
        return user

    async def get_user_by_sub(self, db: AsyncSession, sub: str) -> PlatformUser | None:
        """Return the PlatformUser for the given OIDC subject, or None."""
        result = await db.execute(
            select(PlatformUser).where(PlatformUser.sub == sub)
        )
        return result.scalar_one_or_none()
