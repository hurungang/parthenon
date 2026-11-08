"""Management-tool payload validation / normalization for Control Center.

Shared by every ``cc____create_*`` / ``cc____update_*`` handler in
``backend/app/api/v1/internal/management_tools.py``.  The validator owns:

- **Typed field coercion** — enum coercion (invalid values return the list of
  valid values), boolean/int coercion, and slug/name pattern checks.
- **Tenant-scoped id-or-name FK resolution** — a raw value that parses as a
  UUID is resolved by id; anything else by name.  Every lookup is scoped to
  the calling tenant; an unknown value raises a 404-shaped structured error
  with an actionable message (resolve-before-write, no partial writes).
- **Required-field enforcement** — field-specific actionable messages.
- **Unknown-field rejection** — payloads carrying fields outside the
  family's allowed set are rejected with a structured problem naming the
  unknown field (the assistant can self-correct).
- **Structured validation-error construction** — every failure carries
  ``{"error": "validation_failed", "problems": [{field, problem, remedy}]}``
  instead of a bare 400 string.

Handlers write only through Control Center services / the SQLAlchemy session
(top-priority rule: only CC touches the database).  This module never touches
sensitive material (identity tokens, API keys, decrypted credentials) beyond
accepting a plaintext ``api_key`` for encryption at the storage boundary.
"""
from __future__ import annotations

import enum
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


# ── Structured error construction ──────────────────────────────────────────


@dataclass
class Problem:
    """One field-level validation problem with a remedy hint."""

    field: str
    problem: str
    remedy: str

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "problem": self.problem, "remedy": self.remedy}


@dataclass
class ManagementValidationError(Exception):
    """Structured validation failure (rendered as a 400 with a dict detail).

    ``problems`` carries one entry per invalid field so the assistant can
    self-correct autonomously (field + problem + remedy hint).
    """

    problems: list[Problem] = field(default_factory=list)

    def add(self, field_name: str, problem: str, remedy: str) -> None:
        self.problems.append(Problem(field=field_name, problem=problem, remedy=remedy))

    @property
    def first(self) -> Problem:
        return self.problems[0]

    def payload(self) -> dict[str, Any]:
        """Structured error payload (error code + per-field problems)."""
        return {
            "error": "validation_failed",
            "problems": [p.as_dict() for p in self.problems],
        }

    def __str__(self) -> str:  # pragma: no cover — readable fallback rendering
        head = self.first
        return f"{head.field}: {head.problem}. {head.remedy}"


def structured_error(field_name: str, problem: str, remedy: str) -> ManagementValidationError:
    """Shorthand single-problem structured validation error."""
    return ManagementValidationError([Problem(field=field_name, problem=problem, remedy=remedy)])


# ── Validator / normalizer ─────────────────────────────────────────────────


class PayloadValidator:
    """Typed payload validation + normalization for one management-tool call.

    Instantiated per handler invocation with the tenant-scoped database
    session; raises :class:`ManagementValidationError` (400-shaped) on any
    validation failure.  Unknown-reference resolution raises a dedicated
    404-shaped :class:`ReferenceNotFoundError`.
    """


class ReferenceNotFoundError(Exception):
    """A referenced resource (id-or-name) does not exist within the tenant.

    Rendered as a 404 with an actionable message — resolve-before-write
    means this always aborts before any row is written.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$|^[a-z0-9]$")


def parse_uuid(raw: Any) -> uuid.UUID | None:
    """Parse a raw value as a UUID (None when it is not UUID-shaped)."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or not _UUID_RE.match(text):
        return None
    try:
        return uuid.UUID(text)
    except (ValueError, TypeError):
        return None


def is_uuid_shaped(raw: Any) -> bool:
    return parse_uuid(raw) is not None


class PayloadValidatorFull:
    """Concrete validator — field coercion + tenant-scoped FK resolution.

    Named ``PayloadValidatorFull`` to keep the historical import surface
    stable; handlers alias it as ``PayloadValidator``.
    """

    def __init__(self, db: AsyncSession, tenant_id: Any) -> None:
        self.db = db
        self.tenant_id = tenant_id

    # ── Coercion ───────────────────────────────────────────────────────

    def coerce_enum(
        self,
        enum_cls: type[enum.Enum],
        raw: Any,
        field_name: str,
        *,
        default: enum.Enum | None = None,
        required: bool = False,
        remedy_hint: str = "",
    ) -> Any:
        """Coerce a raw string to an enum member.

        Invalid values raise a structured problem listing the VALID values so
        the assistant can self-correct without a second lookup.
        """
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            if default is not None:
                return default
            if required:
                raise structured_error(
                    field_name,
                    "is required",
                    f"Provide one of: {', '.join(m.value for m in enum_cls)}.",
                )
            return None
        if isinstance(raw, enum_cls):
            return raw
        try:
            return enum_cls(str(raw).strip())
        except (ValueError, TypeError) as exc:
            valid = ", ".join(m.value for m in enum_cls)
            raise structured_error(
                field_name,
                f"invalid value '{raw}'",
                f"Valid values are: {valid}.{(' ' + remedy_hint) if remedy_hint else ''}",
            ) from exc

    def coerce_bool(self, raw: Any, field_name: str) -> bool | None:
        """Coerce a raw value to a boolean (None passthrough)."""
        if raw is None:
            return None
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off"):
            return False
        raise structured_error(
            field_name,
            f"invalid boolean '{raw}'",
            "Use true or false.",
        )

    def coerce_int(self, raw: Any, field_name: str) -> int | None:
        """Coerce a raw value to an integer (None passthrough)."""
        if raw is None or raw == "":
            return None
        try:
            return int(raw)
        except (ValueError, TypeError) as exc:
            raise structured_error(
                field_name,
                f"invalid integer '{raw}'",
                "Provide a whole number.",
            ) from exc

    def check_slug_pattern(self, value: str, field_name: str) -> str:
        """Enforce the lowercase-slug name convention with a structured error."""
        if not _SLUG_RE.match(value):
            raise structured_error(
                field_name,
                f"'{value}' is not valid slug format",
                "Use lowercase letters, digits, and hyphens only (e.g. my-name).",
            )
        return value

    # ── Required / unknown fields ──────────────────────────────────────

    @staticmethod
    def require(value: Any, field_name: str, remedy: str) -> str:
        """Enforce a non-empty required string field."""
        text = str(value).strip() if value is not None else ""
        if not text:
            raise structured_error(field_name, "is required", remedy)
        return text

    @staticmethod
    def require_raw(value: Any, field_name: str, remedy: str) -> Any:
        """Enforce presence of a required raw (possibly non-string) field."""
        if value is None or (isinstance(value, str) and not value.strip()):
            raise structured_error(field_name, "is required", remedy)
        return value

    @staticmethod
    def reject_unknown(data: dict[str, Any], allowed: set[str], resource_label: str) -> None:
        """Reject payload keys outside the family's allowed field set."""
        unknown = sorted(k for k in data if k not in allowed)
        if not unknown:
            return
        err = ManagementValidationError()
        for key in unknown:
            err.add(
                key,
                "is not an accepted field",
                f"{resource_label} accepts: {', '.join(sorted(allowed))}. "
                f"Remove '{key}' or use get_management_tool_schema for the exact schema.",
            )
        raise err

    # ── Tenant-scoped id-or-name FK resolution ─────────────────────────

    async def resolve_fk(
        self,
        model: Any,
        raw: Any,
        field_name: str,
        kind_label: str,
        *,
        name_field: str = "name",
        required: bool = False,
        discovery_hint: str = "",
    ) -> uuid.UUID | None:
        """Resolve one id-or-name value to a tenant-scoped UUID.

        UUID-shaped values resolve by id; everything else by name.  Unknown
        references raise :class:`ReferenceNotFoundError` (404-shaped) with an
        actionable message.  Resolution never writes.
        """
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            if required:
                raise structured_error(
                    field_name,
                    "is required",
                    f"Provide the {kind_label} id or exact name.{(' ' + discovery_hint) if discovery_hint else ''}",
                )
            return None
        raw_str = str(raw).strip()
        obj_id = parse_uuid(raw_str)
        stmt = select(model).where(model.tenant_id == self.tenant_id)
        if obj_id is not None:
            stmt = stmt.where(model.id == obj_id)
        else:
            stmt = stmt.where(getattr(model, name_field) == raw_str)
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            hint = f" {discovery_hint}" if discovery_hint else ""
            raise ReferenceNotFoundError(
                f"{kind_label} not found in this workspace: '{raw_str}'. "
                f"Use the exact id or name, or list {kind_label}s first"
                f" (list tool).{hint}"
            )
        return row.id

    async def resolve_fk_list(
        self,
        model: Any,
        values: Any,
        field_name: str,
        kind_label: str,
        *,
        name_field: str = "name",
    ) -> list[uuid.UUID]:
        """Resolve a list of id-or-name values (resolve-before-write).

        The WHOLE list resolves before anything is written, so one unknown
        value aborts the call with no partial write.
        """
        if values is None:
            return []
        if not isinstance(values, list):
            raise structured_error(
                field_name,
                "must be a list of ids or names",
                f"Provide a JSON array of {kind_label} ids or exact names.",
            )
        resolved: list[uuid.UUID] = []
        for raw in values:
            resolved_id = await self.resolve_fk(
                model, raw, field_name, kind_label, name_field=name_field
            )
            if resolved_id is not None:
                resolved.append(resolved_id)
        return resolved


#: Canonical alias used by the management-tools handlers.
PayloadValidator = PayloadValidatorFull
