"""Group Claim Mapper — maps JWT group claims to UserGroup memberships."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.group import Group
from app.db.models.user_group import UserGroup

logger = logging.getLogger(__name__)


class GroupClaimMapper:
    """Maps JWT group claims to UserGroup memberships idempotently."""

    async def map_claims(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        jwt_claims: list[str],
    ) -> list[uuid.UUID]:
        """Map JWT group claims to UserGroup records.

        Queries Group records whose idp_claim_value appears in jwt_claims.
        Creates new UserGroup records for groups the user is not yet a member of.
        Returns the list of newly assigned group IDs (not existing ones).
        """
        if not jwt_claims:
            return []

        # Find groups whose idp_claim_value matches any JWT claim
        result = await db.execute(select(Group).where(Group.idp_claim_value.in_(jwt_claims)))
        matched_groups = result.scalars().all()
        if not matched_groups:
            return []

        # Get existing group memberships for this user
        existing_result = await db.execute(
            select(UserGroup.group_id).where(UserGroup.user_id == user_id)
        )
        existing_group_ids = set(existing_result.scalars().all())

        newly_assigned: list[uuid.UUID] = []
        for group in matched_groups:
            if group.id not in existing_group_ids:
                membership = UserGroup(
                    user_id=user_id,
                    group_id=group.id,
                    join_reason="Auto-assigned via IdP claim mapping",
                )
                db.add(membership)
                newly_assigned.append(group.id)
                logger.info(
                    "Auto-assigned user %s to group %s via IdP claim '%s'",
                    user_id,
                    group.id,
                    group.idp_claim_value,
                )

        if newly_assigned:
            await db.flush()

        return newly_assigned
