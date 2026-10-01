"""User Cache Service — upserts PlatformUser and Identity records from OIDC token claims."""
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.identity import Identity, IdentityType
from app.db.models.platform_user import PlatformUser
from app.db.tenant_scoping import execute_unscoped

logger = logging.getLogger(__name__)


class UserCacheService:
    """Upserts PlatformUser and Identity records on every successful JWT validation.

    Both upserts are idempotent: a user who has logged in before will simply
    have ``last_seen_at`` / ``updated_at`` refreshed. New users get both a
    ``PlatformUser`` and an ``Identity`` row created in the same transaction.

    Identity-plane note (FIX-20260929-221449): the by-subject lookups are
    IDENTITY resolution — they run tenant-scope-exempt
    (:func:`app.db.tenant_scoping.execute_unscoped`) so JIT provisioning
    finds and refreshes the existing record even when the session is
    tenant-scoped and the user holds no membership in that tenant (a
    scoped lookup would miss the row and the INSERT would collide with
    the unique ``sub``/``subject`` constraints).
    """

    async def upsert_user(
        self,
        db: AsyncSession,
        sub: str,
        email: str,
        display_name: str,
    ) -> PlatformUser:
        """Upsert PlatformUser by sub; handle email conflict from re-provisioned IdP."""
        result = await execute_unscoped(
            db, select(PlatformUser).where(PlatformUser.sub == sub)
        )
        user = result.scalar_one_or_none()

        if user is None:
            # Check for email conflict — stale user from a previous IdP instance
            existing_by_email = await execute_unscoped(
                db, select(PlatformUser).where(PlatformUser.email == email)
            )
            stale = existing_by_email.scalar_one_or_none()
            if stale is not None:
                logger.warning(
                    "Removing stale PlatformUser sub=%s email=%s — IdP re-provisioned",
                    stale.sub, email,
                )
                await db.delete(stale)
                await db.flush()

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
            if email:
                user.email = email
            if display_name:
                user.display_name = display_name

        await db.flush()
        await db.refresh(user)
        return user

    async def upsert_identity(
        self,
        db: AsyncSession,
        sub: str,
        display_name: str,
        email: str | None = None,
    ) -> Identity:
        """Idempotently create/update the Identity row matching an OIDC subject.

        The ``Identity`` table is the canonical "human actor" record used by
        governance endpoints (e.g. ``request_termination``) to record the
        ``requested_by`` actor. Without an Identity row the operator can
        authenticate but cannot invoke any flow that needs one.

        Existing rows have ``display_name`` / ``email`` / ``is_active``
        refreshed; new rows start with ``is_active=True`` and
        ``identity_type=user``. No role is assigned automatically — role
        assignment is driven by ``/setup/init`` (admin seed) and the
        group-claim mapper.
        """
        result = await execute_unscoped(
            db, select(Identity).where(Identity.subject == sub)
        )
        identity = result.scalar_one_or_none()

        if identity is None:
            identity = Identity(
                subject=sub,
                display_name=display_name or sub,
                email=email,
                identity_type=IdentityType.user,
                is_active=True,
            )
            db.add(identity)
            logger.info("Created new Identity for sub=%s", sub)
        else:
            identity.is_active = True
            if display_name:
                identity.display_name = display_name
            if email:
                identity.email = email

        await db.flush()
        await db.refresh(identity)
        return identity

    async def get_user_by_sub(self, db: AsyncSession, sub: str) -> PlatformUser | None:
        """Return the PlatformUser for the given OIDC subject, or None.

        Identity-plane lookup — tenant-scope-exempt (FIX-20260929-221449).
        """
        result = await execute_unscoped(
            db, select(PlatformUser).where(PlatformUser.sub == sub)
        )
        return result.scalar_one_or_none()
