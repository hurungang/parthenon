"""Pydantic v2 schemas for third-party agent-client CRUD and internal validation.

A *client* is an access grant bound to one agent type (input-interface only),
distinct from an API key (identity credential).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Admin CRUD Schemas ────────────────────────────────────────────────────────


class AgentClientCreate(BaseModel):
    """Request body for creating a new client."""

    name: str = Field(..., min_length=1, max_length=200)
    agent_type_id: uuid.UUID = Field(..., description="The single agent type this client may invoke")
    key_type: str = Field(..., pattern="^(secret|publishable)$", description="secret (server-side) or publishable (browser-safe)")
    slug: str | None = Field(None, max_length=200, description="URL-safe reference; derived from name if omitted")
    white_label_theme: dict[str, Any] | None = Field(None, description="name/avatar/colors (publishable only)")
    allowed_origins: list[str] | None = Field(None, description="Serving origins (secondary control)")
    rate_limit: int | None = Field(None, ge=1, description="Max requests per rate_limit_window")
    rate_limit_window: str | None = Field(None, pattern="^(per_minute|per_hour|per_day)$")
    expires_at: datetime | None = Field(None, description="Optional expiry; None = never")


class AgentClientCredentialResponse(BaseModel):
    """Response for client creation/credential rotation — clear-text key shown once."""

    id: uuid.UUID
    name: str
    key_type: str
    key_prefix: str
    client_key: str = Field(..., description="Clear-text credential — shown once, never stored")
    agent_type_id: uuid.UUID
    agent_type_name: str
    created_at: datetime


class AgentClientRead(BaseModel):
    """Response for client list items — metadata only, never the credential."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    slug: str
    agent_type_id: uuid.UUID
    agent_type_name: str | None = None
    key_type: str
    key_prefix: str
    status: str
    tenant_slug: str | None = None
    white_label_theme: dict[str, Any] | None = None
    allowed_origins: list[str] | None = None
    rate_limit: int | None = None
    rate_limit_window: str | None = None
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None


class AgentClientRevokeResponse(BaseModel):
    """Response for client revocation/deletion."""

    id: uuid.UUID
    status: str
    message: str = "Client updated successfully"


class AgentClientStatusUpdate(BaseModel):
    """Request body for activating/deactivating a client."""

    status: str = Field(..., pattern="^(active|inactive)$", description="active or inactive")


class AgentClientUpdate(BaseModel):
    """Editable client fields — allowed origins and rate limit only.

    Name, key type, and target agent type are immutable after creation.
    """

    allowed_origins: list[str] | None = Field(
        None, description="Serving origins (wildcards supported, e.g. https://*.acme.com)"
    )
    rate_limit: int | None = Field(None, ge=1)
    rate_limit_window: str | None = Field(None, pattern="^(per_minute|per_hour|per_day)$")


# ── Internal Validation Schemas (CH → CC) ────────────────────────────────────


class ClientValidateRequest(BaseModel):
    """Request from CH to validate a hashed client credential."""

    key_hash: str = Field(..., min_length=1, description="SHA-256 hash of the client credential")


class ClientValidateResponse(BaseModel):
    """Resolved client context — carries NO agent identity token (a client is not an identity)."""

    valid: bool = True
    client_id: uuid.UUID
    client_name: str
    agent_type_id: uuid.UUID
    agent_type_name: str | None = None
    agent_type_input_type: str | None = None
    agent_type_input_schema: dict[str, Any] | None = None
    key_type: str
    white_label_theme: dict[str, Any] | None = None
    allowed_origins: list[str] | None = None
    rate_limit: int | None = None
    rate_limit_window: str | None = None
    tenant_id: uuid.UUID | None = None
    tenant_slug: str | None = None
    tenant_name: str | None = None
    tenant_headers: dict[str, str] | None = Field(
        default=None,
        description="CC-signed tenant headers for CH to forward verbatim on internal calls",
    )
