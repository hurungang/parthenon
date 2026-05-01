"""Structured error response models for the Parthenon API."""

from __future__ import annotations

from pydantic import BaseModel


class RequiredPermission(BaseModel):
    """Describes the permission that was required but not held by the caller."""

    resource_type: str
    action: str
    resource_id: str | None = None


class PermissionDeniedDetail(BaseModel):
    """Structured body returned with 403 Permission Denied responses.

    Clients can inspect ``required_permission`` to display a targeted
    "Access Denied" message rather than a generic error string.
    """

    detail: str
    required_permission: RequiredPermission
