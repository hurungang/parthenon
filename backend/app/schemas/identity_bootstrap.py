"""Pydantic v2 schemas for the Identity Bootstrap API endpoints."""
from __future__ import annotations

import enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SetupState(str, enum.Enum):
    """Current state of the identity provider setup."""

    NOT_CONFIGURED = "NOT_CONFIGURED"
    CONFIGURED = "CONFIGURED"
    IN_PROGRESS = "IN_PROGRESS"


class ProviderType(str, enum.Enum):
    """Supported identity provider types."""

    KEYCLOAK_BUNDLED = "keycloak_bundled"
    KEYCLOAK_EXTERNAL = "keycloak_external"
    AZURE_ENTRAID = "azure_entraid"


class IdentityStatusResponse(BaseModel):
    """Response schema for GET /setup/identity-status."""

    setup_state: SetupState
    provider_type: Optional[str] = None
    oidc_provider_url: Optional[str] = None


class ProviderSetupRequest(BaseModel):
    """Request schema for POST /setup/identity."""

    provider_type: ProviderType

    # Keycloak-specific fields
    keycloak_url: Optional[str] = Field(default=None, description="Base URL of the Keycloak instance")
    realm_name: Optional[str] = Field(default=None, description="Keycloak realm name")
    client_id: Optional[str] = Field(default=None, description="OIDC client ID")
    admin_user: Optional[str] = Field(default=None, description="Keycloak master-realm admin username")
    admin_password: Optional[str] = Field(default=None, description="Keycloak master-realm admin password")
    initial_admin_password: Optional[str] = Field(
        default=None, description="Password for the initial Parthenon admin user"
    )

    # External OIDC-specific fields
    client_secret: Optional[str] = Field(default=None, description="Pre-existing OIDC client secret")
    oidc_discovery_url: Optional[str] = Field(
        default=None, description="Full /.well-known/openid-configuration URL"
    )

    # Re-configure flag
    force_reconfigure: bool = Field(default=False, description="Allow overwriting an existing configuration")

    @field_validator("keycloak_url", "realm_name", "client_id", mode="before")
    @classmethod
    def strip_whitespace(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return v.strip() or None
        return v


class ProviderSetupResult(BaseModel):
    """Response schema for POST /setup/identity."""

    success: bool
    provider_type: str
    oidc_provider_url: Optional[str] = None
    realm_name: Optional[str] = None
    client_id: Optional[str] = None
    error_code: Optional[str] = None
    detail: Optional[str] = None
