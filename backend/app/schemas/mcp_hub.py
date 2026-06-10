"""Pydantic v2 schemas for MCP Hub."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, StringConstraints, model_validator
from typing import Annotated

from app.db.models.mcp_hub import McpServerStatus, McpSessionAuthType


class McpServerCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=r"^[a-z0-9\-]+$")]
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
    session_count: int = 0
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
    is_default: bool | None = None

    @model_validator(mode="after")
    def validate_passthrough_no_credentials(self) -> "McpSessionCreate":
        """Passthrough sessions must not include credentials."""
        if self.auth_type == McpSessionAuthType.passthrough and self.credentials is not None:
            raise ValueError(
                "Passthrough sessions forward the agent JWT directly — credentials must be omitted."
            )
        return self


class McpSessionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    auth_type: McpSessionAuthType | None = None
    credentials: dict[str, Any] | None = None
    identity_subject: str | None = None
    is_active: bool | None = None
    is_default: bool | None = None
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
    is_default: bool
    identity_binding: dict[str, Any] | None
    credential_config: dict[str, Any] | None
    oauth_expires_at: datetime | None = None
    oauth_refresh_expires_at: datetime | None = None
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
    warnings: list[str] = []


class TestToolRequest(BaseModel):
    """Request to test an MCP tool invocation."""
    
    session_id: uuid.UUID | None = None
    """The MCP session ID to use for authentication. Required for non-passthrough sessions."""
    
    agent_subject: str | None = None
    """Agent identity UUID or username (realm_username) to use for passthrough testing. Required for passthrough sessions. The agent's access token will be retrieved/refreshed and forwarded to the MCP server."""
    
    tool_input: dict[str, Any]
    """The input arguments for the tool."""


class TestToolResponse(BaseModel):
    """Response from testing an MCP tool."""
    
    success: bool
    """Whether the tool invocation succeeded."""
    
    result: dict[str, Any] | None = None
    """The tool result if successful."""
    
    error: str | None = None
    """Error message if failed."""
    
    raw_response: dict[str, Any] | None = None
    """The complete raw response from the MCP server."""
