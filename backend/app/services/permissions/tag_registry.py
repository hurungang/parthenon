"""Tag Registry service — manages TagDefinition and TagValue records."""
import logging
import uuid
from typing import List

from fastapi import HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.tag_definition import TagDefinition, TagScope
from app.db.models.policy_tag_condition import PolicyTagCondition
from app.db.models.tag_value import TagValue

logger = logging.getLogger(__name__)


class TagRegistry:
    """Manages tag definitions and validates tag key/value assignments."""

    async def list_definitions(
        self,
        db: AsyncSession,
        scope: str | None = None,
        resource_type: str | None = None,
    ) -> List[TagDefinition]:
        """Return tag definitions, optionally filtered by scope or resource_type."""
        stmt = (
            select(TagDefinition)
            .options(selectinload(TagDefinition.tag_values))
            .order_by(TagDefinition.key)
        )
        if scope is not None:
            stmt = stmt.where(TagDefinition.scope == scope)
        if resource_type is not None:
            stmt = stmt.where(TagDefinition.resource_type == resource_type)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create_definition(
        self,
        db: AsyncSession,
        key: str,
        scope: TagScope,
        resource_type: str | None = None,
        description: str | None = None,
        allowed_values: List[str] | None = None,
    ) -> TagDefinition:
        """Create a TagDefinition + TagValue records.

        Raises HTTPException 409 if key+scope already exists.
        """
        # Check uniqueness
        existing = await db.execute(
            select(TagDefinition).where(
                TagDefinition.key == key,
                TagDefinition.scope == scope,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Tag definition with key '{key}' and scope '{scope}' already exists.",
            )

        tag_def = TagDefinition(
            key=key,
            scope=scope,
            resource_type=resource_type,
            description=description,
        )
        db.add(tag_def)
        await db.flush()

        for value in (allowed_values or []):
            db.add(TagValue(tag_definition_id=tag_def.id, value=value))

        await db.flush()
        await db.refresh(tag_def, attribute_names=['tag_values'])
        return tag_def

    async def update_definition(
        self,
        db: AsyncSession,
        tag_id: uuid.UUID,
        description: str | None = None,
        add_values: List[str] | None = None,
        remove_values: List[str] | None = None,
    ) -> TagDefinition:
        """Update description and/or allowed values.

        Raises HTTPException 404 if not found.
        """
        tag_def = await db.get(TagDefinition, tag_id)
        if tag_def is None:
            raise HTTPException(status_code=404, detail="Tag definition not found.")

        if description is not None:
            tag_def.description = description

        for value in (add_values or []):
            # Only add if not already present
            exists = await db.execute(
                select(TagValue).where(
                    TagValue.tag_definition_id == tag_id,
                    TagValue.value == value,
                )
            )
            if exists.scalar_one_or_none() is None:
                db.add(TagValue(tag_definition_id=tag_id, value=value))

        if remove_values:
            await db.execute(
                delete(TagValue).where(
                    TagValue.tag_definition_id == tag_id,
                    TagValue.value.in_(remove_values),
                )
            )

        await db.flush()
        await db.refresh(tag_def, attribute_names=['tag_values'])
        
        return tag_def

    async def delete_definition(self, db: AsyncSession, tag_id: uuid.UUID) -> None:
        """Delete a TagDefinition (cascades to TagValues).

        Raises HTTPException 404 if not found.
        Raises HTTPException 409 if any PolicyTagCondition references this tag_key.
        """
        tag_def = await db.get(TagDefinition, tag_id)
        if tag_def is None:
            raise HTTPException(status_code=404, detail="Tag definition not found.")

        # Check if any policy uses this tag key
        refs = await db.execute(
            select(PolicyTagCondition).where(PolicyTagCondition.tag_key == tag_def.key).limit(1)
        )
        if refs.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Tag key '{tag_def.key}' is referenced by one or more policy conditions.",
            )

        await db.delete(tag_def)
        await db.flush()

    async def validate_tag_value(
        self,
        db: AsyncSession,
        tag_key: str,
        tag_value: str,
    ) -> None:
        """Validate a tag value against the allowed values for the given key.

        Raises HTTPException 422 if the value is not in the allowed set.
        """
        tag_def_result = await db.execute(
            select(TagDefinition).where(TagDefinition.key == tag_key)
        )
        tag_def = tag_def_result.scalar_one_or_none()
        if tag_def is None:
            raise HTTPException(
                status_code=422,
                detail={"tag_key": tag_key, "error": "Tag key not found."},
            )

        allowed = await db.execute(
            select(TagValue).where(TagValue.tag_definition_id == tag_def.id)
        )
        allowed_values = [tv.value for tv in allowed.scalars().all()]
        if allowed_values and tag_value not in allowed_values:
            raise HTTPException(
                status_code=422,
                detail={
                    "tag_key": tag_key,
                    "tag_value": tag_value,
                    "allowed_values": allowed_values,
                    "error": "Tag value is not in the allowed values list.",
                },
            )
