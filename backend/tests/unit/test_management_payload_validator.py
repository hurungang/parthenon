"""Unit tests for the management payload validator / normalizer.

Covers Phase 2 task 2.1: typed enum coercion (valid values listed in the
error), boolean/integer coercion, slug pattern enforcement, required-field
enforcement, unknown-field rejection, and the structured validation-error
shape (field / problem / remedy).
"""
from __future__ import annotations

import enum
import uuid

import pytest

from app.services.agents.management_payload import (
    ManagementValidationError,
    PayloadValidator,
    ReferenceNotFoundError,
    structured_error,
)


class _Color(str, enum.Enum):
    red = "red"
    green = "green"
    blue = "blue"


# ── Enum coercion ──────────────────────────────────────────────────────────


def test_coerce_enum_accepts_valid_value() -> None:
    validator = PayloadValidator(None, None)  # coercion is session-free
    assert validator.coerce_enum(_Color, "green", "color") is _Color.green


def test_coerce_enum_returns_default_on_missing() -> None:
    validator = PayloadValidator(None, None)
    assert validator.coerce_enum(_Color, None, "color", default=_Color.red) is _Color.red


def test_coerce_enum_error_lists_valid_values() -> None:
    validator = PayloadValidator(None, None)
    with pytest.raises(ManagementValidationError) as excinfo:
        validator.coerce_enum(_Color, "purple", "color")
    err = excinfo.value
    assert err.payload()["error"] == "validation_failed"
    problem = err.payload()["problems"][0]
    assert problem["field"] == "color"
    assert "red, green, blue" in problem["remedy"]


def test_coerce_enum_required_missing_is_structured() -> None:
    validator = PayloadValidator(None, None)
    with pytest.raises(ManagementValidationError) as excinfo:
        validator.coerce_enum(_Color, "", "color", required=True)
    assert excinfo.value.first.field == "color"
    assert "required" in excinfo.value.first.problem


# ── Boolean / int coercion ─────────────────────────────────────────────────


def test_coerce_bool_variants() -> None:
    validator = PayloadValidator(None, None)
    assert validator.coerce_bool("true", "flag") is True
    assert validator.coerce_bool(False, "flag") is False
    assert validator.coerce_bool(None, "flag") is None
    with pytest.raises(ManagementValidationError) as excinfo:
        validator.coerce_bool("maybe", "flag")
    assert excinfo.value.first.field == "flag"


def test_coerce_int_rejects_non_integer() -> None:
    validator = PayloadValidator(None, None)
    assert validator.coerce_int("42", "count") == 42
    with pytest.raises(ManagementValidationError) as excinfo:
        validator.coerce_int("abc", "count")
    assert excinfo.value.first.field == "count"


# ── Required / pattern / unknown fields ────────────────────────────────────


def test_require_structured_error() -> None:
    with pytest.raises(ManagementValidationError) as excinfo:
        PayloadValidator.require("  ", "slug", "Provide a slug.")
    assert excinfo.value.first.field == "slug"
    assert "required" in excinfo.value.first.problem


def test_slug_pattern_rejection_is_actionable() -> None:
    validator = PayloadValidator(None, None)
    with pytest.raises(ManagementValidationError) as excinfo:
        validator.check_slug_pattern("Bad Name!", "name")
    problem = excinfo.value.first
    assert problem.field == "name"
    assert "lowercase" in problem.remedy
    assert validator.check_slug_pattern("my-name-2", "name") == "my-name-2"


def test_reject_unknown_fields_names_offenders_and_allowed_set() -> None:
    allowed = {"name", "description"}
    with pytest.raises(ManagementValidationError) as excinfo:
        PayloadValidator.reject_unknown({"name": "x", "bogus": 1, "wat": 2}, allowed, "create_widget")
    problems = excinfo.value.payload()["problems"]
    assert sorted(p["field"] for p in problems) == ["bogus", "wat"]
    assert "description, name" in problems[0]["remedy"]
    # No unknown → no raise
    PayloadValidator.reject_unknown({"name": "x"}, allowed, "create_widget")


# ── Structured error shape ─────────────────────────────────────────────────


def test_structured_error_payload_shape() -> None:
    err = structured_error("cron_expression", "is required", "Provide a cron expression.")
    payload = err.payload()
    assert payload == {
        "error": "validation_failed",
        "problems": [
            {
                "field": "cron_expression",
                "problem": "is required",
                "remedy": "Provide a cron expression.",
            }
        ],
    }
    assert "cron_expression" in str(err)


def test_multi_problem_error_carries_all_fields() -> None:
    err = ManagementValidationError()
    err.add("a", "is required", "r1")
    err.add("b", "invalid", "r2")
    assert [p["field"] for p in err.payload()["problems"]] == ["a", "b"]
    assert err.first.field == "a"


# ── Reference errors ───────────────────────────────────────────────────────


def test_reference_not_found_error_is_404_shaped_message() -> None:
    exc = ReferenceNotFoundError("agent role not found in this workspace: 'x'.")
    assert "agent role" in exc.message
    assert "not found" in exc.message


# ── Tenant-scoped id-or-name FK resolution (task 5.1) ──────────────────────


@pytest.mark.asyncio
async def test_resolve_fk_by_name_and_by_id(db_session):
    from app.db.models.agents import AgentRole

    tenant_id = uuid.UUID("aa000000-0000-0000-0000-00000000000a")
    row = AgentRole(tenant_id=tenant_id, name="resolver-role")
    db_session.add(row)
    await db_session.commit()

    validator = PayloadValidator(db_session, tenant_id)
    by_name = await validator.resolve_fk(AgentRole, "resolver-role", "role_id", "agent role")
    by_id = await validator.resolve_fk(AgentRole, str(row.id), "role_id", "agent role")
    assert by_name == row.id
    assert by_id == row.id


@pytest.mark.asyncio
async def test_resolve_fk_unknown_value_raises_actionable_404(db_session):
    from app.db.models.agents import AgentRole

    tenant_id = uuid.UUID("aa000000-0000-0000-0000-00000000000a")
    validator = PayloadValidator(db_session, tenant_id)
    with pytest.raises(ReferenceNotFoundError) as exc:
        await validator.resolve_fk(AgentRole, "no-such-role", "role_id", "agent role")
    assert "no-such-role" in exc.value.message
    assert "not found in this workspace" in exc.value.message

    with pytest.raises(ReferenceNotFoundError):
        # Unknown but UUID-shaped value resolves by id — still 404.
        await validator.resolve_fk(
            AgentRole, "99999999-9999-9999-9999-999999999999", "role_id", "agent role"
        )


@pytest.mark.asyncio
async def test_resolve_fk_is_tenant_scoped_cross_tenant_name_is_404(db_session):
    """A name that exists in ANOTHER tenant must not resolve (tenant scoping)."""
    from app.db.models.agents import AgentRole

    tenant_a = uuid.UUID("aa000000-0000-0000-0000-00000000000a")
    tenant_b = uuid.UUID("bb000000-0000-0000-0000-00000000000b")
    db_session.add(AgentRole(tenant_id=tenant_b, name="tenant-b-role"))
    await db_session.commit()

    validator = PayloadValidator(db_session, tenant_a)
    with pytest.raises(ReferenceNotFoundError):
        await validator.resolve_fk(AgentRole, "tenant-b-role", "role_id", "agent role")


@pytest.mark.asyncio
async def test_resolve_fk_list_resolves_before_write_and_rejects_non_list(db_session):
    from app.db.models.agents import AgentRole

    tenant_id = uuid.UUID("aa000000-0000-0000-0000-00000000000a")
    row_a = AgentRole(tenant_id=tenant_id, name="list-role-a")
    row_b = AgentRole(tenant_id=tenant_id, name="list-role-b")
    db_session.add_all([row_a, row_b])
    await db_session.commit()

    validator = PayloadValidator(db_session, tenant_id)
    resolved = await validator.resolve_fk_list(
        AgentRole, [row_a.id, "list-role-b"], "role_ids", "agent role"
    )
    assert resolved == [row_a.id, row_b.id]

    # Non-list payload → structured 400.
    with pytest.raises(ManagementValidationError) as exc:
        await validator.resolve_fk_list(AgentRole, "list-role-a", "role_ids", "agent role")
    assert exc.value.first.field == "role_ids"

    # One unknown value in the list → 404 for the WHOLE resolution
    # (resolve-before-write, no partial output).
    with pytest.raises(ReferenceNotFoundError):
        await validator.resolve_fk_list(
            AgentRole, [row_a.id, "missing-role"], "role_ids", "agent role"
        )
