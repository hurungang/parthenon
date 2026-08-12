"""Pydantic v2 schemas for MCP OAuth flow."""
from pydantic import BaseModel


class OAuthDiscoveryResult(BaseModel):
    """Result of OAuth auto-discovery (endpoints + credentials)."""

    authorization_url: str
    token_url: str
    client_id: str
    client_secret: str | None = None
    scope: str | None = None
    redirect_uri: str
    registration_endpoint: str | None = None


class OAuthInitiateRequest(BaseModel):
    """Optional manual OAuth configuration to use instead of auto-discovery.
    
    Priority:
    1. If metadata_url is provided, fetch OAuth config from that URL
    2. If manual fields (authorization_url, token_url) are provided, use them
    3. Otherwise, attempt auto-discovery from MCP server base_url
    """
    
    metadata_url: str | None = None
    authorization_url: str | None = None
    token_url: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    scope: str | None = None
    session_name: str | None = None
    session_description: str | None = None


class OAuthInitiateResponse(BaseModel):
    authorization_url: str


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str
    session_id: str
    token_url: str
    client_id: str
    client_secret: str
    redirect_uri: str


class OAuthCallbackResponse(BaseModel):
    success: bool
    message: str
