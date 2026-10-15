"""Pydantic v2 schemas for System Config API — OIDC provider configs and super admin."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.services.tenancy.default_tenant_roles import DEFAULT_TENANT_ROLE_PRESETS


def _validate_default_tenant_role(value: Optional[str]) -> Optional[str]:
    """Accept only the seeded preset role keys (or None)."""
    if value is None:
        return None
    if value not in DEFAULT_TENANT_ROLE_PRESETS:
        raise ValueError(
            f"Invalid default_tenant_role '{value}'. Must be one of: "
            f"{sorted(DEFAULT_TENANT_ROLE_PRESETS)} or null."
        )
    return value


# ── Identity Provider Config ────────────────────────────────────────────────


class IdentityProviderConfigCreate(BaseModel):
    """Schema for creating a new identity provider config."""

    provider_scope: str = Field(..., description="user | agent")
    provider_type: str = Field(..., description="oidc_generic | keycloak | azure_entraid")
    display_name: str = Field(..., description="Human-readable label")
    issuer_url: str = Field(..., description="OIDC issuer URL")
    client_id: str = Field(..., description="OIDC client ID (confidential API client)")
    client_secret: Optional[str] = Field(None, description="OIDC client secret")
    public_client_id: Optional[str] = Field(
        None,
        description=(
            "UI/public OIDC client ID used by the frontend browser sign-in "
            "(authorize + PKCE, no secret). Required for the 'user' scope; "
            "ignored for the 'agent' scope."
        ),
    )
    scopes: str = Field("openid profile email", description="Space-delimited OIDC scopes")
    claim_mappings: Optional[dict] = Field(None, description="OIDC claim to platform field mappings")
    is_enabled: bool = Field(True, description="Whether the provider is active")
    default_tenant_role: Optional[str] = Field(
        None,
        description=(
            "JIT default tenant role granted on a user's FIRST OIDC sign-in "
            "(one of the seeded preset keys), or null to reject users "
            "without a membership."
        ),
    )

    @field_validator("default_tenant_role")
    @classmethod
    def _check_default_role_create(cls, v: Optional[str]) -> Optional[str]:
        return _validate_default_tenant_role(v)


class IdentityProviderConfigUpdate(BaseModel):
    """Schema for updating an existing identity provider config."""

    provider_type: Optional[str] = Field(None, description="oidc_generic | keycloak | azure_entraid")
    display_name: Optional[str] = Field(None, description="Human-readable label")
    issuer_url: Optional[str] = Field(None, description="OIDC issuer URL")
    client_id: Optional[str] = Field(None, description="OIDC client ID (confidential API client)")
    client_secret: Optional[str] = Field(None, description="OIDC client secret")
    public_client_id: Optional[str] = Field(
        None,
        description=(
            "UI/public OIDC client ID used by the frontend browser sign-in "
            "(authorize + PKCE, no secret). Required (non-empty) for the "
            "'user' scope; ignored for the 'agent' scope."
        ),
    )
    scopes: Optional[str] = Field(None, description="Space-delimited OIDC scopes")
    claim_mappings: Optional[dict] = Field(None, description="OIDC claim to platform field mappings")
    is_enabled: Optional[bool] = Field(None, description="Whether the provider is active")
    default_tenant_role: Optional[str] = Field(
        None,
        description=(
            "JIT default tenant role granted on a user's FIRST OIDC sign-in "
            "(one of the seeded preset keys); omitted = unchanged."
        ),
    )

    @field_validator("default_tenant_role")
    @classmethod
    def _check_default_role_update(cls, v: Optional[str]) -> Optional[str]:
        return _validate_default_tenant_role(v)


class IdentityProviderConfigToggle(BaseModel):
    """Schema for toggling a provider's is_enabled flag."""

    is_enabled: bool = Field(..., description="New enabled state")


class IdentityProviderConfigResponse(BaseModel):
    """Response schema for a single identity provider config."""

    id: str
    provider_scope: str
    provider_type: str
    display_name: str
    issuer_url: str
    client_id: str
    encrypted_client_secret: Optional[str] = None  # masked in list, raw in detail
    public_client_id: Optional[str] = None
    scopes: str
    claim_mappings: Optional[dict] = None
    is_enabled: bool
    default_tenant_role: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IdentityProviderConfigListResponse(BaseModel):
    """Response schema for listing identity provider configs (secrets masked)."""

    items: list[IdentityProviderConfigResponse]
    total: int


# ── OIDC Test ───────────────────────────────────────────────────────────────


class OIDCTestRequest(BaseModel):
    """Schema for testing OIDC connectivity without persisting."""

    issuer_url: str = Field(..., description="OIDC issuer URL to test")
    client_id: Optional[str] = Field(None, description="OIDC client ID (optional for connectivity test)")
    client_secret: Optional[str] = Field(None, description="OIDC client secret (optional)")
    redirect_uri: Optional[str] = Field(None, description="Redirect URI for test login (defaults to request base URL)")


class OIDCTestStep(BaseModel):
    """A single diagnostic step in an OIDC test result."""

    step: str
    status: str  # passed | failed | skipped
    detail: str


class OIDCTestResponse(BaseModel):
    """Response schema for OIDC connectivity test."""

    success: bool
    steps: list[OIDCTestStep]
    discovery_doc: Optional[dict] = None
    client_id_status: Optional[dict] = Field(
        None,
        description=(
            "Client validation result: {client_id, status, detail} with "
            "status one of missing | invalid | ok | warning; null when "
            "discovery failed before the client probe ran."
        ),
    )


# ── Super Admin ─────────────────────────────────────────────────────────────


class SuperAdminStatusResponse(BaseModel):
    """Public status of the super admin account (no secrets)."""

    is_enabled: bool
    username: Optional[str] = None
    last_login_at: Optional[str] = None
    env_controlled: bool = False


class SuperAdminToggleRequest(BaseModel):
    """Schema for enabling/disabling the super admin."""

    is_enabled: bool = Field(..., description="New enabled state")


class SuperAdminPasswordUpdateRequest(BaseModel):
    """Schema for updating the super admin password."""

    current_password: str = Field(..., min_length=1, description="Current password")
    new_password: str = Field(..., min_length=8, description="New password (min 8 chars)")


# ── Auth ────────────────────────────────────────────────────────────────────


class SuperAdminLoginRequest(BaseModel):
    """Schema for super admin credential login."""

    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class SuperAdminLoginResponse(BaseModel):
    """Response schema for successful super admin login."""

    access_token: str = Field(..., description="Short-lived internal JWT")
    token_type: str = "Bearer"
    username: str
    is_super_admin: bool = True
