"""Pydantic v2 schemas for MCP Hub."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated

from app.db.models.mcp_hub import McpServerStatus, McpSessionAuthType


class McpServerCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    slug: Annotated[str, StringConstraints(min_length=1, max_length=100, pattern=r"^[a-z0-9\-]+$")]
    description: str | None = None
    base_url: Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class McpServerUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    base_url: str | None = None
    oauth_config: dict[str, Any] | None = None
    status: McpServerStatus | None = None


class McpServerRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    base_url: str
    oauth_config: dict[str, Any] | None
    status: McpServerStatus
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class McpSessionCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    description: str | None = None
    auth_type: McpSessionAuthType = McpSessionAuthType.api_key
    # Plaintext credentials — will be encrypted before storage
    credentials: dict[str, Any] | None = None
    identity_subject: str | None = None
    identity_binding: dict[str, Any] | None = None
    credential_config: dict[str, Any] | None = None


class McpSessionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    auth_type: McpSessionAuthType | None = None
    credentials: dict[str, Any] | None = None
    identity_subject: str | None = None
    is_active: bool | None = None
    identity_binding: dict[str, Any] | None = None
    credential_config: dict[str, Any] | None = None


class McpSessionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    server_id: uuid.UUID
    name: str
    description: str | None
    auth_type: McpSessionAuthType
    identity_subject: str | None
    is_active: bool
    identity_binding: dict[str, Any] | None
    credential_config: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    # Connection test result (only present during creation/update)
    connection_test: dict[str, Any] | None = None
    # Note: encrypted_credentials is intentionally excluded


class McpToolRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    server_id: uuid.UUID
    server_slug: str | None = None
    server_name: str | None = None
    name: str
    original_name: str
    description: str | None
    input_schema: dict[str, Any] | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def __get_validators__(cls):  # noqa: D105
        yield cls.model_validate

    @classmethod
    def from_orm_with_server(cls, tool: Any) -> "McpToolRead":
        obj = cls.model_validate(tool)
        if hasattr(tool, "server") and tool.server is not None:
            obj.server_slug = tool.server.slug
            obj.server_name = tool.server.name
        return obj


class ToolPermissionCreate(BaseModel):
    role_id: uuid.UUID


class ToolPermissionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    tool_id: uuid.UUID
    role_id: uuid.UUID
    created_at: datetime


class SyncResult(BaseModel):
    server_id: uuid.UUID
    tools_added: int
    tools_updated: int
    tools_deactivated: int
    total_active: int
