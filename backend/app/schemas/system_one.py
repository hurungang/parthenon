"""Pydantic v2 schemas for System One provider configuration.

The API key is write-only: it is accepted on create/update, stored
AES-256 encrypted, and never returned in any response payload.

The base URL is the FULL endpoint URL, used verbatim by the outbound client —
no path segments are appended or stripped. It defaults to the official
TypeSafe endpoint ``https://api.typesafe.ai/v1/systemone`` when omitted on
create. Proxies: enter the proxy's complete URL.
"""
import logging
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, StringConstraints, field_validator
from typing import Annotated

from app.db.models.model_guardrail_configuration import (
    ModelGuardrailEnforcementPosture,
    ModelGuardrailPeriod,
    ModelUsageUnit,
)
from app.db.models.system_one_provider_config import SystemOneProviderType

logger = logging.getLogger(__name__)

#: Preset FULL endpoint URL (create-form default), used verbatim.
SYSTEM_ONE_PRESET_BASE_URL = "https://api.typesafe.ai/v1/systemone"


def _validate_base_url(value: str) -> str:
    """Validate http(s) URL shape. The value is used verbatim — no rewriting."""
    stripped = value.strip()
    if not (stripped.startswith("http://") or stripped.startswith("https://")):
        raise ValueError("base_url must be an http:// or https:// URL")
    return stripped


class SystemOneProviderCreate(BaseModel):
    """Create payload for a System One provider config (API key write-only).

    ``base_url`` is the FULL endpoint URL (editable per tenant); it defaults
    to the preset ``https://api.typesafe.ai/v1/systemone``.
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

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, value: str) -> str:
        return _validate_base_url(value)


class SystemOneProviderTypeRead(BaseModel):
    """One selectable vendor type (value + human label) for the create dialog."""

    value: str
    label: str


class SystemOneProviderUpdate(BaseModel):
    """Update payload; only ``api_key`` replacement is optional-secret.

    ``base_url`` is the FULL endpoint URL, editable per tenant.
    """

    display_name: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = None
    base_url: Annotated[str, StringConstraints(min_length=1, max_length=2048)] | None = None
    default_model: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = None
    api_key: Annotated[str, StringConstraints(min_length=1)] | None = None
    enabled: bool | None = None
    enabled_models: list[str] | None = None

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_base_url(value)


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
    """Multi-provider status used by the skill editor authoring gate."""

    configured: bool
    provider_type: SystemOneProviderType | None = None
    provider_id: Any | None = None
    model: str | None = None
    provider_count: int = 0


class SystemOneTestConnectionResult(BaseModel):
    """Status-only Test-connection result — never carries key material."""

    ok: bool
    message: str
    latency_ms: float | None = None


# ── Decision model catalogue (provider/model hierarchy + toggles) ────────────


class DecisionModelAvailabilityRead(BaseModel):
    """Per-model availability entry within the provider hierarchy."""

    model_config = {"from_attributes": True}

    availability_id: uuid.UUID | None = None
    model_name: str
    effective_is_disabled: bool
    disabled_reason: str | None = None


class DecisionModelHierarchyEntry(BaseModel):
    """One provider with its model catalogue in the hierarchy listing."""

    model_config = {"from_attributes": True}

    provider_id: uuid.UUID
    display_name: str
    provider_type: SystemOneProviderType
    default_model: str
    is_disabled: bool
    models: list[DecisionModelAvailabilityRead] = []


class DecisionModelAvailabilityUpdate(BaseModel):
    """Toggle payload: vendor-level cascade or per-model manual disable."""

    is_disabled: bool


class VendorModelSyncResult(BaseModel):
    """Model ids discovered from the vendor's OpenAI-compatible /models
    endpoint — never carries key material."""

    models: list[str]


class VendorModelImportRequest(BaseModel):
    """Import payload: vendor model ids to seed as availability rows."""

    models: Annotated[list[str], Field(min_length=1)]


class DecisionEnabledModelRead(BaseModel):
    """Flat enabled-models entry feeding the authoring selector."""

    model_config = {"from_attributes": True}

    availability_id: uuid.UUID
    provider_id: uuid.UUID
    provider_type: SystemOneProviderType
    provider_display_name: str
    model_name: str


# ── Decision guardrails (FIX-20261014-003000) ────────────────────────────────
# Reuse the model-usage guardrail stack (same ``model_guardrail_configurations``
# table, ``config_source='decision_provider'``); these schemas mirror the LLM
# guardrail Read/Update shapes from ``schemas/agents.py`` but key via
# ``decision_provider_id`` (``model_id`` is always NULL for decision rows).


class DecisionGuardrailCreate(BaseModel):
    """Create one per-period guardrail for a Decision Model Provider model."""

    model_name: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    period: ModelGuardrailPeriod
    limit_value: int = Field(ge=0)
    unit: ModelUsageUnit = ModelUsageUnit.k
    enforcement_posture: ModelGuardrailEnforcementPosture = (
        ModelGuardrailEnforcementPosture.terminate
    )
    is_active: bool = True
    details: dict[str, Any] | None = None


class DecisionGuardrailUpdate(BaseModel):
    """Partial update of one decision guardrail (period is immutable)."""

    limit_value: int | None = Field(default=None, ge=0)
    unit: ModelUsageUnit | None = None
    enforcement_posture: ModelGuardrailEnforcementPosture | None = None
    is_active: bool | None = None
    details: dict[str, Any] | None = None


class DecisionGuardrailRead(BaseModel):
    """Read shape for one decision-scope guardrail row."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    decision_provider_id: uuid.UUID | None = None
    model_id: uuid.UUID | None = None
    model_name: str
    period: ModelGuardrailPeriod
    limit_value: int
    unit: ModelUsageUnit
    enforcement_posture: ModelGuardrailEnforcementPosture
    is_active: bool
    details: dict[str, Any]
    created_at: datetime
    updated_at: datetime
