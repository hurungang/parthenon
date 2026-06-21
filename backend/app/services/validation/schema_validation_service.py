"""SchemaValidationService — validates a payload against a data type schema.

Supports five field types:
- string: any value (coerced to string)
- number: must be numeric (int, float, or string that can be parsed)
- boolean: must be bool or string "true"/"false"
- date: must be a parseable date string
- enum: value must be in the allowed list
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.schemas.agent_outputs import FieldError, ValidationResult

logger = logging.getLogger(__name__)

# Allowed field type constants (matching DataTypeFieldType values)
FIELD_TYPE_STRING = "string"
FIELD_TYPE_NUMBER = "number"
FIELD_TYPE_BOOLEAN = "boolean"
FIELD_TYPE_DATE = "date"
FIELD_TYPE_ENUM = "enum"

VALID_FIELD_TYPES = {
    FIELD_TYPE_STRING,
    FIELD_TYPE_NUMBER,
    FIELD_TYPE_BOOLEAN,
    FIELD_TYPE_DATE,
    FIELD_TYPE_ENUM,
}


class SchemaValidationService:
    """Validates payload dictionaries against data type schema field definitions."""

    def validate(
        self,
        payload: dict[str, Any],
        fields: list[dict[str, Any]],
    ) -> ValidationResult:
        """Validate a payload against a list of data type field definitions.

        Args:
            payload: The field_values dict from the agent output.
            fields: List of field definitions from AgentDataType.fields.
                Each field must have at least ``name`` and ``type`` keys.

        Returns:
            ValidationResult with valid flag and list of field-level errors.
        """
        errors: list[FieldError] = []

        for field_def in fields:
            field_name = field_def.get("name", "")
            field_type = field_def.get("type", "")
            required = field_def.get("required", True)

            if not field_name:
                continue

            if field_type not in VALID_FIELD_TYPES:
                errors.append(
                    FieldError(
                        field=field_name,
                        message=f"Unknown field type '{field_type}'",
                    )
                )
                continue

            value = payload.get(field_name)

            # Check required fields
            if value is None:
                if required:
                    errors.append(
                        FieldError(
                            field=field_name,
                            message=f"Required field '{field_name}' is missing",
                        )
                    )
                continue

            # Validate type
            type_error = self._validate_field_type(field_name, value, field_def)
            if type_error:
                errors.append(type_error)

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def _validate_field_type(
        self,
        field_name: str,
        value: Any,
        field_def: dict[str, Any],
    ) -> FieldError | None:
        """Validate a single field value against its type definition.

        Returns a FieldError if validation fails, None if valid.
        """
        field_type = field_def.get("type", "")

        if field_type == FIELD_TYPE_STRING:
            # Any value is acceptable for string type (coerced at display time)
            return None

        elif field_type == FIELD_TYPE_NUMBER:
            return self._validate_number(field_name, value)

        elif field_type == FIELD_TYPE_BOOLEAN:
            return self._validate_boolean(field_name, value)

        elif field_type == FIELD_TYPE_DATE:
            return self._validate_date(field_name, value)

        elif field_type == FIELD_TYPE_ENUM:
            return self._validate_enum(field_name, value, field_def)

        return None

    def _validate_number(
        self, field_name: str, value: Any
    ) -> FieldError | None:
        """Validate that a value is numeric."""
        if isinstance(value, (int, float)):
            return None
        if isinstance(value, str):
            try:
                float(value)
                return None
            except (ValueError, TypeError):
                pass
        return FieldError(
            field=field_name,
            message=f"Value for '{field_name}' must be a number, got {type(value).__name__}",
        )

    def _validate_boolean(
        self, field_name: str, value: Any
    ) -> FieldError | None:
        """Validate that a value is boolean."""
        if isinstance(value, bool):
            return None
        if isinstance(value, str) and value.lower() in ("true", "false", "1", "0"):
            return None
        if isinstance(value, int) and value in (0, 1):
            return None
        return FieldError(
            field=field_name,
            message=f"Value for '{field_name}' must be a boolean, got {type(value).__name__}",
        )

    def _validate_date(
        self, field_name: str, value: Any
    ) -> FieldError | None:
        """Validate that a value is a parseable date."""
        if isinstance(value, str):
            # Try common date formats
            for fmt in (
                "%Y-%m-%d",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S.%f%z",
                "%d/%m/%Y",
                "%m/%d/%Y",
                "%Y-%m-%d %H:%M:%S",
            ):
                try:
                    datetime.strptime(value, fmt)
                    return None
                except ValueError:
                    continue
            return FieldError(
                field=field_name,
                message=f"Value for '{field_name}' is not a valid date string",
            )
        # Also accept datetime objects
        if isinstance(value, datetime):
            return None
        return FieldError(
            field=field_name,
            message=f"Value for '{field_name}' must be a date, got {type(value).__name__}",
        )

    def _validate_enum(
        self, field_name: str, value: Any, field_def: dict[str, Any]
    ) -> FieldError | None:
        """Validate that a value is in the allowed enum values list."""
        enum_values = field_def.get("enum_values") or []
        str_value = str(value) if not isinstance(value, str) else value
        if str_value not in enum_values:
            return FieldError(
                field=field_name,
                message=(
                    f"Value '{value}' for '{field_name}' is not valid. "
                    f"Allowed values: {', '.join(sorted(enum_values))}"
                ),
            )
        return None
