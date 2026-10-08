"""Pydantic v2 schemas for System One provider configuration.

The API key is write-only: it is accepted on create/update, stored
AES-256 encrypted, and never returned in any response payload.

The base URL is preset to ``https://api.typesafe.ai/v1`` (non-editable for
this release): the frontend prefills it read-only and the backend defaults
to it when omitted on create.
"""
from typing import Any

from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated

from app.db.models.system_one_provider_config import SystemOneProviderType

#: Preset provider base URL (non-editable for this release).
SYSTEM_ONE_PRESET_BASE_URL = "https://api.typesafe.ai/v1"


class SystemOneProviderCreate(BaseModel):
    """Create payload for a System One provider config (API key write-only).

    ``base_url`` defaults to the preset; clients send it read-only.
    """

    provider_type: SystemOneProviderType = SystemOneProviderType.typesafe
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    base_url: Annotated[str, StringConstraints(min_length=1, max_length=2048)] = (
        SYSTEM_ONE_PRESET_BASE_URL
    )
    default_model: Annotated[str, StringConstraints(min_length=1, max_length=200)] = (
        "jev-latest"
    )
    api_key: Annotated[str, StringConstraints(min_length=1)]
    enabled: bool = True
    enabled_models: list[str] | None = None


class SystemOneProviderUpdate(BaseModel):
    """Update payload; only ``api_key`` replacement is optional-secret.

    The base URL is preset and NOT editable.
    """

    display_name: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = None
    default_model: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = None
    api_key: Annotated[str, StringConstraints(min_length=1)] | None = None
    enabled: bool | None = None
    enabled_models: list[str] | None = None


class SystemOneProviderRead(BaseModel):
    """Provider config response — contains NO API key material."""

    model_config = {"from_attributes": True}

    id: Any
    provider_type: SystemOneProviderType
    display_name: str
    base_url: str
    default_model: str
    enabled: bool
    enabled_models: list[str] | None = None
    has_api_key: bool = True


class SystemOneStatus(BaseModel):
    """Configured-model status used by the skill editor authoring gate."""

    configured: bool
    provider_type: SystemOneProviderType | None = None
    provider_id: Any | None = None
    model: str | None = None


class SystemOneTestConnectionResult(BaseModel):
    """Status-only Test-connection result — never carries key material."""

    ok: bool
    message: str
    latency_ms: float | None = None
