"""Pydantic v2 schemas for Agent Data Type CRUD operations."""
import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, field_validator, model_validator


class DataTypeFieldType(str, Enum):
    """Supported field types for data type definitions."""

    string = "string"
    number = "number"
    boolean = "boolean"
    date = "date"
    enum = "enum"


class DataTypeFieldCreate(BaseModel):
    """A single typed field definition within a data type schema."""

    name: str
    description: str = ""
    type: DataTypeFieldType
    enum_values: list[str] | None = None
    required: bool = True
    default: Any = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field name must not be empty")
        return v.strip()

    @model_validator(mode="after")
    def validate_enum_values(self) -> "DataTypeFieldCreate":
        if self.type == DataTypeFieldType.enum and not self.enum_values:
            raise ValueError(
                "enum_values is required when field type is 'enum'"
            )
        return self


class DataTypeFieldResponse(BaseModel):
    """A single typed field definition in API responses."""

    model_config = {"from_attributes": True}

    name: str
    description: str = ""
    type: DataTypeFieldType
    enum_values: list[str] | None = None
    required: bool = True
    default: Any = None


class DataTypeCreate(BaseModel):
    """Request body for creating a new data type."""

    name: str
    slug: str
    description: str | None = None
    fields: list[DataTypeFieldCreate]

    @model_validator(mode="after")
    def validate_fields(self) -> "DataTypeCreate":
        if not self.fields:
            raise ValueError("At least one field is required")

        # Check for duplicate field names
        field_names = [f.name for f in self.fields]
        if len(field_names) != len(set(field_names)):
            seen: set[str] = set()
            duplicates = {n for n in field_names if n in seen or seen.add(n)}
            raise ValueError(
                f"Duplicate field names not allowed: {', '.join(sorted(duplicates))}"
            )

        return self


class DataTypeUpdate(BaseModel):
    """Request body for updating an existing data type. All fields optional."""

    name: str | None = None
    slug: str | None = None
    description: str | None = None
    fields: list[DataTypeFieldCreate] | None = None

    @model_validator(mode="after")
    def validate_fields_if_present(self) -> "DataTypeUpdate":
        if self.fields is not None:
            if not self.fields:
                raise ValueError("At least one field is required")

            field_names = [f.name for f in self.fields]
            if len(field_names) != len(set(field_names)):
                seen: set[str] = set()
                duplicates = {n for n in field_names if n in seen or seen.add(n)}
                raise ValueError(
                    f"Duplicate field names not allowed: {', '.join(sorted(duplicates))}"
                )

        return self


class DataTypeResponse(BaseModel):
    """Response body for a single data type."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    fields: list[DataTypeFieldResponse]
    created_at: datetime
    updated_at: datetime


class DataTypeUsageInfo(BaseModel):
    """Usage information for a data type, returned when ?usage=true."""

    model_config = {"from_attributes": True}

    referencing_agent_types: list[dict[str, Any]] = []


class DataTypeListResponse(BaseModel):
    """Paginated list response for data types."""

    items: list[DataTypeResponse]
    total: int
    page: int
    page_size: int
