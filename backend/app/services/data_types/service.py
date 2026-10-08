"""DataTypeService — CRUD operations for AgentDataType."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.agent_data_type import AgentDataType
from app.db.models.agents import AgentType

logger = logging.getLogger(__name__)


class DataTypeNotFoundError(Exception):
    """Raised when a data type is not found."""


class DataTypeConflictError(Exception):
    """Raised when deletion is blocked by referencing agent types."""

    def __init__(self, message: str, referencing_types: list[dict[str, Any]]) -> None:
        self.referencing_types = referencing_types
        super().__init__(message)


class DataTypeDuplicateError(Exception):
    """Raised when creating a data type with a duplicate name or slug."""


class DataTypeService:
    """Service layer for AgentDataType CRUD operations."""

    async def create(
        self,
        db: AsyncSession,
        name: str,
        slug: str,
        description: str | None,
        fields: list[dict[str, Any]],
        tenant_id: uuid.UUID | None = None,
    ) -> AgentDataType:
        """Create a new data type.

        Raises:
            DataTypeDuplicateError: If a data type with the same name or slug already exists.
        """
        # Check for existing name or slug (scoped to the tenant; tenant-less
        # rows keep the platform-wide scope via the partial global index)
        existing = await db.execute(
            select(AgentDataType).where(
                or_(AgentDataType.name == name, AgentDataType.slug == slug),
                AgentDataType.tenant_id == tenant_id,
            )
        )
        existing_dt = existing.scalar_one_or_none()
        if existing_dt:
            if existing_dt.name == name:
                raise DataTypeDuplicateError(
                    f"A data type with name '{name}' already exists"
                )
            raise DataTypeDuplicateError(
                f"A data type with slug '{slug}' already exists"
            )

        data_type = AgentDataType(
            tenant_id=tenant_id,
            name=name,
            slug=slug,
            description=description,
            fields=fields,
        )
        db.add(data_type)
        await db.flush()
        await db.refresh(data_type)
        logger.info("Created data type %s (name=%s)", data_type.id, name)
        return data_type

    async def get(
        self, db: AsyncSession, id: uuid.UUID
    ) -> AgentDataType | None:
        """Get a data type by ID."""
        return await db.get(AgentDataType, id)

    async def update(
        self,
        db: AsyncSession,
        id: uuid.UUID,
        name: str | None = None,
        slug: str | None = None,
        description: str | None = None,
        fields: list[dict[str, Any]] | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> AgentDataType:
        """Update an existing data type.

        Raises:
            DataTypeNotFoundError: If the data type does not exist.
            DataTypeDuplicateError: If the new name or slug conflicts with another data type.
        """
        data_type = await db.get(AgentDataType, id)
        if not data_type:
            raise DataTypeNotFoundError(f"Data type {id} not found")

        # Check name/slug uniqueness if changing (tenant-scoped)
        if name is not None and name != data_type.name:
            existing = await db.execute(
                select(AgentDataType).where(
                    AgentDataType.name == name,
                    AgentDataType.tenant_id == tenant_id,
                    AgentDataType.id != id,
                )
            )
            if existing.scalar_one_or_none():
                raise DataTypeDuplicateError(
                    f"A data type with name '{name}' already exists"
                )
            data_type.name = name

        if slug is not None and slug != data_type.slug:
            existing = await db.execute(
                select(AgentDataType).where(
                    AgentDataType.slug == slug,
                    AgentDataType.tenant_id == tenant_id,
                    AgentDataType.id != id,
                )
            )
            if existing.scalar_one_or_none():
                raise DataTypeDuplicateError(
                    f"A data type with slug '{slug}' already exists"
                )
            data_type.slug = slug

        if description is not None:
            data_type.description = description
        if fields is not None:
            data_type.fields = fields

        await db.flush()
        await db.refresh(data_type)
        logger.info("Updated data type %s (name=%s)", id, data_type.name)
        return data_type

    async def delete(
        self, db: AsyncSession, id: uuid.UUID
    ) -> None:
        """Delete a data type.

        Raises:
            DataTypeNotFoundError: If the data type does not exist.
            DataTypeConflictError: If the data type is referenced by agent types.
        """
        data_type = await db.get(AgentDataType, id)
        if not data_type:
            raise DataTypeNotFoundError(f"Data type {id} not found")

        # Check if referenced by any agent types
        referencing_types = await self._get_referencing_agent_types(db, id)
        if referencing_types:
            raise DataTypeConflictError(
                f"Cannot delete data type '{data_type.name}': "
                f"referenced by {len(referencing_types)} agent type(s)",
                referencing_types=referencing_types,
            )

        # Check if referenced by any decision tools (input/output contract)
        decision_refs = await self._get_referencing_decision_tools(db, id)
        if decision_refs:
            raise DataTypeConflictError(
                f"Cannot delete data type '{data_type.name}': "
                f"referenced by {len(decision_refs)} decision tool(s)",
                referencing_types=decision_refs,
            )

        await db.delete(data_type)
        await db.flush()
        logger.info("Deleted data type %s (name=%s)", id, data_type.name)

    async def list(  # noqa: A003
        self,
        db: AsyncSession,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        usage: bool = False,
    ) -> tuple[list[AgentDataType], int]:
        """List data types with pagination and optional search.

        Args:
            db: Database session.
            page: Page number (1-indexed).
            page_size: Items per page.
            search: Optional search string to filter by name or slug.
            usage: If True, eager-load referencing agent types.

        Returns:
            Tuple of (items, total_count).
        """
        query = select(AgentDataType)

        if search:
            query = query.where(
                or_(
                    AgentDataType.name.ilike(f"%{search}%"),
                    AgentDataType.slug.ilike(f"%{search}%"),
                    AgentDataType.description.ilike(f"%{search}%"),
                )
            )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await db.execute(count_query)
        total = count_result.scalar_one()

        # Eager-load relationships for usage info
        if usage:
            query = query.options(
                selectinload(AgentDataType.agent_types).load_only(
                    AgentType.id, AgentType.name
                )
            )

        # Apply ordering and pagination
        query = (
            query.order_by(AgentDataType.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        result = await db.execute(query)
        items = list(result.scalars().all())

        return items, total

    async def get_by_slug(
        self, db: AsyncSession, slug: str, tenant_id: uuid.UUID | None = None
    ) -> AgentDataType | None:
        """Get a data type by its slug (tenant-scoped when a tenant is active)."""
        result = await db.execute(
            select(AgentDataType).where(
                AgentDataType.slug == slug,
                AgentDataType.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def count_usage(
        self, db: AsyncSession, id: uuid.UUID
    ) -> int:
        """Count how many agent types reference a given data type."""
        result = await db.execute(
            select(func.count())
            .select_from(AgentType)
            .where(AgentType.output_data_type_id == id)
        )
        return result.scalar_one()

    async def _get_referencing_agent_types(
        self, db: AsyncSession, id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Get agent types that reference this data type."""
        result = await db.execute(
            select(AgentType.id, AgentType.name).where(
                AgentType.output_data_type_id == id
            )
        )
        return [
            {"id": str(row[0]), "name": row[1]}
            for row in result.fetchall()
        ]

    async def _get_referencing_decision_tools(
        self, db: AsyncSession, id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Get decision tools whose input/output contract references this type.

        Deletion protection: a data type referenced by any decision tool
        cannot be removed (mirrors the agent-type reference rule).
        """
        from app.db.models.decision_tools import DecisionTool

        result = await db.execute(
            select(DecisionTool.id, DecisionTool.name).where(
                (DecisionTool.input_data_type_id == id)
                | (DecisionTool.output_data_type_id == id)
            )
        )
        return [
            {"id": str(row[0]), "name": row[1]}
            for row in result.fetchall()
        ]
