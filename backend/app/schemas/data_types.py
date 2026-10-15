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


class EnumValueDef(BaseModel):
    """One allowed enum value with an optional human-readable description.

    Backward compatible: a bare ``str`` in ``enum_values`` is still valid and
    is treated as ``description=None``. The values live in the AgentDataType
    ``fields`` JSON column — no DB migration is required for this extension.
    """

    value: str
    description: str | None = None

    @field_validator("value")
    @classmethod
    def value_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Enum value must not be empty")
        return v.strip()


def enum_plain_values(enum_values: list[Any] | None) -> list[str]:
    """Extract the plain allowed values from an enum_values list.

    Accepts the legacy plain-string shape and the extended
    ``{value, description}`` object shape interchangeably.
    """
    if not enum_values:
        return []
    values: list[str] = []
    for entry in enum_values:
        if isinstance(entry, str):
            values.append(entry)
        elif isinstance(entry, dict) and entry.get("value") is not None:
            values.append(str(entry["value"]))
        elif isinstance(entry, EnumValueDef):
            values.append(entry.value)
    return values


def enum_descriptions(enum_values: list[Any] | None) -> dict[str, str | None]:
    """Map allowed value → description (None when absent / legacy string)."""
    if not enum_values:
        return {}
    result: dict[str, str | None] = {}
    for entry in enum_values:
        if isinstance(entry, str):
            result[entry] = None
        elif isinstance(entry, dict) and entry.get("value") is not None:
            result[str(entry["value"])] = entry.get("description")
        elif isinstance(entry, EnumValueDef):
            result[entry.value] = entry.description
    return result


class DataTypeFieldCreate(BaseModel):
    """A single typed field definition within a data type schema."""

    name: str
    description: str = ""
    type: DataTypeFieldType
    enum_values: list[str | EnumValueDef] | None = None
    required: bool = True
    default: Any = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field name must not be empty")
        return v.strip()

    @field_validator("enum_values")
    @classmethod
    def validate_enum_value_entries(
        cls, v: list[str | EnumValueDef] | None
    ) -> list[str | EnumValueDef] | None:
        """Reject empty/duplicate enum values (legacy strings + described
        object entries share one namespace)."""
        if v is None:
            return None
        seen: set[str] = set()
        for entry in v:
            value = entry if isinstance(entry, str) else entry.value
            if not value or not value.strip():
                raise ValueError("Enum values must not be empty")
            if value in seen:
                raise ValueError(f"Duplicate enum value '{value}'")
            seen.add(value)
        return v

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
    enum_values: list[str | EnumValueDef] | None = None
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
