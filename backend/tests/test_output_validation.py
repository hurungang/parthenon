"""
Backend unit tests for SchemaValidationService.

Tests cover:
  1. Valid string field
  2. Valid number field (int, float, string number)
  3. Valid boolean field (bool, string true/false, 0/1 int)
  4. Valid date field (ISO date, datetime string)
  5. Valid enum field
  6. Missing required field
  7. Invalid number field
  8. Invalid boolean field
  9. Invalid date field
  10. Invalid enum value
  11. Unknown field type
  12. Empty payload (all required missing)
  13. Non-required field missing (no error)
"""
from __future__ import annotations

import pytest

from app.services.validation.schema_validation_service import (
    SchemaValidationService,
)


@pytest.fixture
def service() -> SchemaValidationService:
    """Return a fresh SchemaValidationService instance."""
    return SchemaValidationService()


# ── Field Definitions Helpers ────────────────────────────────────────────────


def _fields(*field_defs: dict) -> list[dict]:
    """Build a list of field definitions."""
    return list(field_defs)


@pytest.fixture
def sample_schema() -> list[dict]:
    """Return a sample data type schema with all 5 field types."""
    return _fields(
        {"name": "title", "type": "string", "required": True},
        {"name": "severity", "type": "enum", "required": True, "enum_values": ["low", "medium", "high"]},
        {"name": "count", "type": "number", "required": False},
        {"name": "is_active", "type": "boolean", "required": True},
        {"name": "event_date", "type": "date", "required": True},
        {"name": "description", "type": "string", "required": False},
    )


# ── Valid Payload Tests ──────────────────────────────────────────────────────


class TestValidPayloads:
    """Tests that valid payloads pass validation."""

    @pytest.mark.asyncio
    async def test_valid_string(self, service: SchemaValidationService):
        """String field accepts any value."""
        result = service.validate(
            {"title": "Incident Report"},
            _fields({"name": "title", "type": "string", "required": True}),
        )
        assert result.valid is True
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_valid_number_int(self, service: SchemaValidationService):
        """Number field accepts int."""
        result = service.validate(
            {"count": 42},
            _fields({"name": "count", "type": "number", "required": True}),
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_valid_number_float(self, service: SchemaValidationService):
        """Number field accepts float."""
        result = service.validate(
            {"count": 3.14},
            _fields({"name": "count", "type": "number", "required": True}),
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_valid_number_string(self, service: SchemaValidationService):
        """Number field accepts numeric string."""
        result = service.validate(
            {"count": "99"},
            _fields({"name": "count", "type": "number", "required": True}),
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_valid_boolean_true(self, service: SchemaValidationService):
        """Boolean field accepts True."""
        result = service.validate(
            {"is_active": True},
            _fields({"name": "is_active", "type": "boolean", "required": True}),
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_valid_boolean_string(self, service: SchemaValidationService):
        """Boolean field accepts 'true' string."""
        result = service.validate(
            {"is_active": "true"},
            _fields({"name": "is_active", "type": "boolean", "required": True}),
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_valid_boolean_int(self, service: SchemaValidationService):
        """Boolean field accepts 0/1 int."""
        result = service.validate(
            {"is_active": 1},
            _fields({"name": "is_active", "type": "boolean", "required": True}),
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_valid_date_iso(self, service: SchemaValidationService):
        """Date field accepts ISO date string."""
        result = service.validate(
            {"event_date": "2024-01-15"},
            _fields({"name": "event_date", "type": "date", "required": True}),
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_valid_date_datetime(self, service: SchemaValidationService):
        """Date field accepts datetime ISO string."""
        result = service.validate(
            {"event_date": "2024-01-15T14:30:00"},
            _fields({"name": "event_date", "type": "date", "required": True}),
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_valid_enum(self, service: SchemaValidationService):
        """Enum field accepts a value from the allowed list."""
        result = service.validate(
            {"severity": "high"},
            _fields({"name": "severity", "type": "enum", "required": True, "enum_values": ["low", "medium", "high"]}),
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_optional_field_missing(self, service: SchemaValidationService):
        """Non-required field missing does not cause error."""
        result = service.validate(
            {"title": "Test"},
            _fields(
                {"name": "title", "type": "string", "required": True},
                {"name": "description", "type": "string", "required": False},
            ),
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_all_fields_valid(self, service: SchemaValidationService, sample_schema):
        """All fields in the sample schema with valid values pass."""
        result = service.validate(
            {
                "title": "Incident Report",
                "severity": "high",
                "count": 5,
                "is_active": True,
                "event_date": "2024-06-15",
                "description": "A detailed description",
            },
            sample_schema,
        )
        assert result.valid is True
        assert len(result.errors) == 0


# ── Invalid Payload Tests ────────────────────────────────────────────────────


class TestInvalidPayloads:
    """Tests that invalid payloads correctly fail validation."""

    @pytest.mark.asyncio
    async def test_missing_required_field(self, service: SchemaValidationService):
        """Missing required field returns field-level error."""
        result = service.validate(
            {},
            _fields({"name": "title", "type": "string", "required": True}),
        )
        assert result.valid is False
        assert len(result.errors) == 1
        assert result.errors[0].field == "title"
        assert "required" in result.errors[0].message.lower()

    @pytest.mark.asyncio
    async def test_invalid_number(self, service: SchemaValidationService):
        """Non-numeric value for number field returns error."""
        result = service.validate(
            {"count": "not-a-number"},
            _fields({"name": "count", "type": "number", "required": True}),
        )
        assert result.valid is False
        assert len(result.errors) == 1
        assert result.errors[0].field == "count"

    @pytest.mark.asyncio
    async def test_invalid_boolean(self, service: SchemaValidationService):
        """Non-boolean value for boolean field returns error."""
        result = service.validate(
            {"is_active": "maybe"},
            _fields({"name": "is_active", "type": "boolean", "required": True}),
        )
        assert result.valid is False
        assert len(result.errors) == 1
        assert result.errors[0].field == "is_active"

    @pytest.mark.asyncio
    async def test_invalid_date(self, service: SchemaValidationService):
        """Unparseable date string returns error."""
        result = service.validate(
            {"event_date": "not-a-date"},
            _fields({"name": "event_date", "type": "date", "required": True}),
        )
        assert result.valid is False
        assert len(result.errors) == 1
        assert result.errors[0].field == "event_date"

    @pytest.mark.asyncio
    async def test_invalid_enum_value(self, service: SchemaValidationService):
        """Value not in enum_values list returns error."""
        result = service.validate(
            {"severity": "critical"},
            _fields({"name": "severity", "type": "enum", "required": True, "enum_values": ["low", "medium", "high"]}),
        )
        assert result.valid is False
        assert len(result.errors) == 1
        assert result.errors[0].field == "severity"
        assert "allowed" in result.errors[0].message.lower()

    @pytest.mark.asyncio
    async def test_multiple_errors(self, service: SchemaValidationService, sample_schema):
        """Multiple validation errors are all reported."""
        result = service.validate(
            {
                "title": "Test",
                "severity": "invalid",
                "is_active": "maybe",
                "event_date": "bad-date",
            },
            sample_schema,
        )
        assert result.valid is False
        # severity (enum), is_active (boolean), event_date (date) should fail
        assert len(result.errors) >= 3
        error_fields = {e.field for e in result.errors}
        assert "severity" in error_fields
        assert "is_active" in error_fields
        assert "event_date" in error_fields

    @pytest.mark.asyncio
    async def test_empty_payload_all_required(self, service: SchemaValidationService, sample_schema):
        """Empty payload with all required fields fails validation."""
        result = service.validate({}, sample_schema)
        assert result.valid is False
        # title, severity, is_active, event_date are required
        assert len(result.errors) >= 4

    @pytest.mark.asyncio
    async def test_unknown_field_type(self, service: SchemaValidationService):
        """Unknown field type produces error."""
        result = service.validate(
            {"test": "value"},
            _fields({"name": "test", "type": "unknown_type", "required": True}),
        )
        assert result.valid is False
        assert len(result.errors) == 1
        assert "unknown" in result.errors[0].message.lower()
