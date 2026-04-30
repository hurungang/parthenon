"""Permission Engine — evaluates IAM-style policy statements for authorization."""
import logging
import uuid
from dataclasses import dataclass
from typing import List

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.resource_types import ResourceTypeManifest
from app.db.models.policy_statement import PolicyStatement, PolicyEffect
from app.db.models.policy_action import PolicyAction
from app.db.models.policy_resource import PolicyResource
from app.db.models.policy_tag_condition import PolicyTagCondition
from app.db.models.user_role import UserRole
from app.db.models.user_group import UserGroup
from app.db.models.group_role import GroupRole

logger = logging.getLogger(__name__)


@dataclass
class AuthorizationResult:
    """Result of a permission engine authorization check."""

    allowed: bool
    reason: str


class PermissionEngine:
    """Evaluates authorization requests against a user's effective policy set.

    Deny-by-default: allowed only when at least one matching allow policy exists.
    """

    async def authorize(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        module: str,
        action: str,
        resource_id: str,
        resource_tags: dict[str, str],
    ) -> AuthorizationResult:
        """Evaluate whether user_id may perform action on resource_id in module.

        Steps:
        1. Validate resource_type and action against the manifest
        2. Collect all role_ids: direct UserRole + group-inherited GroupRole
        3. Load PolicyStatements for those roles filtered by module
        4. For each allow statement, check action, resource, and tag conditions
        5. Return allow if any statement matches; deny otherwise
        """
        # Manifest validation — fail fast for unknown resource types or actions
        # Wildcard module '*' bypasses this check (used internally by system admin policy)
        if module != "*":
            if module not in ResourceTypeManifest:
                return AuthorizationResult(
                    allowed=False,
                    reason=f"Unknown resource type '{module}'.",
                )
            if action != "*" and action not in ResourceTypeManifest[module]["actions"]:
                return AuthorizationResult(
                    allowed=False,
                    reason=f"Action '{action}' is not valid for resource type '{module}'.",
                )

        role_ids = await self._get_effective_role_ids(db, user_id)
        if not role_ids:
            return AuthorizationResult(allowed=False, reason="User has no assigned roles.")

        # Fetch all policy statements for those roles matching this module OR wildcard '*'
        stmts_result = await db.execute(
            select(PolicyStatement).where(
                PolicyStatement.role_id.in_(role_ids),
                or_(PolicyStatement.module == module, PolicyStatement.module == "*"),
                PolicyStatement.effect == PolicyEffect.allow,
            )
        )
        statements = stmts_result.scalars().all()

        if not statements:
            return AuthorizationResult(
                allowed=False,
                reason=f"No allow policy for module '{module}'.",
            )

        for stmt in statements:
            # Load related data
            actions_result = await db.execute(
                select(PolicyAction).where(PolicyAction.policy_statement_id == stmt.id)
            )
            stmt_actions = [a.action for a in actions_result.scalars().all()]

            resources_result = await db.execute(
                select(PolicyResource).where(PolicyResource.policy_statement_id == stmt.id)
            )
            stmt_resources = resources_result.scalars().all()

            conditions_result = await db.execute(
                select(PolicyTagCondition).where(
                    PolicyTagCondition.policy_statement_id == stmt.id
                )
            )
            stmt_conditions = conditions_result.scalars().all()

            # Check action match
            if action not in stmt_actions and "*" not in stmt_actions:
                continue

            # Check resource match (any resource in the statement must match)
            resource_matched = False
            for res in stmt_resources:
                pattern = res.resource_id or "*"
                if self._match_resource_id(pattern, resource_id):
                    resource_matched = True
                    break
            # If no resources defined, allow all resources in this module
            if stmt_resources and not resource_matched:
                continue

            # Check all tag conditions satisfied
            tags_satisfied = True
            for cond in stmt_conditions:
                if resource_tags.get(cond.tag_key) != cond.tag_value:
                    tags_satisfied = False
                    break
            if not tags_satisfied:
                continue

            return AuthorizationResult(
                allowed=True,
                reason=f"Allowed by policy statement {stmt.id}.",
            )

        return AuthorizationResult(
            allowed=False,
            reason=f"No matching allow policy for action '{action}' on '{resource_id}'.",
        )

    def _match_resource_id(self, pattern: str, resource_id: str) -> bool:
        """Match a resource_id pattern against an actual resource_id.

        Wildcard support: if pattern ends with '*', match as prefix.
        E.g. 'support_*' matches 'support_001' and 'support_team'.
        Exact match otherwise.
        """
        if pattern == "*":
            return True
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return resource_id.startswith(prefix)
        return pattern == resource_id

    async def _get_effective_role_ids(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> List[uuid.UUID]:
        """Collect all role IDs for a user: direct + group-inherited."""
        # Direct roles
        direct_result = await db.execute(
            select(UserRole.role_id).where(UserRole.user_id == user_id)
        )
        role_ids = list(direct_result.scalars().all())

        # Group-inherited roles
        group_result = await db.execute(
            select(UserGroup.group_id).where(UserGroup.user_id == user_id)
        )
        group_ids = list(group_result.scalars().all())

        if group_ids:
            group_role_result = await db.execute(
                select(GroupRole.role_id).where(GroupRole.group_id.in_(group_ids))
            )
            role_ids.extend(group_role_result.scalars().all())

        return list(set(role_ids))


def get_permission_engine() -> PermissionEngine:
    """FastAPI dependency that provides a PermissionEngine instance.

    Usage in endpoints::

        @router.delete("/{id}")
        async def delete_agent(
            id: UUID,
            engine: PermissionEngine = Depends(get_permission_engine),
            current_user: PlatformUser = Depends(get_current_platform_user),
            db: AsyncSession = Depends(get_db),
        ):
            result = await engine.authorize(db, current_user.id, "agents", "delete", str(id), {})
            if not result.allowed:
                raise HTTPException(status_code=403, detail=result.reason)
    """
    return PermissionEngine()
