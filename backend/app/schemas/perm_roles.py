"""Pydantic v2 schemas for permission-management Roles and Policy Statements."""
import uuid
from datetime import datetime
from enum import Enum
from typing import List

from pydantic import BaseModel, Field, StringConstraints, computed_field, model_validator
from typing import Annotated

from app.core.resource_types import ResourceTypeManifest, is_valid_wildcard


class PolicyEffect(str, Enum):
    allow = "allow"
    deny = "deny"


# ── Policy sub-schemas ─────────────────────────────────────────────────────────

class PolicyActionCreate(BaseModel):
    action: Annotated[str, StringConstraints(min_length=1, max_length=100)]


class PolicyActionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    action: str


class PolicyResourceCreate(BaseModel):
    resource_type: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    resource_id: str | None = Field(default=None, max_length=100)


class PolicyResourceRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    resource_type: str
    resource_id: str | None


class PolicyTagConditionCreate(BaseModel):
    tag_key: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    tag_value: Annotated[str, StringConstraints(min_length=1, max_length=100)]


class PolicyTagConditionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    tag_key: str
    tag_value: str


class PolicyStatementCreate(BaseModel):
    effect: PolicyEffect = PolicyEffect.allow
    module: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    actions: List[PolicyActionCreate] = Field(default_factory=list)
    resources: List[PolicyResourceCreate] = Field(default_factory=list)
    tag_conditions: List[PolicyTagConditionCreate] = Field(default_factory=list)


class PolicyStatementRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    effect: PolicyEffect
    module: str
    created_at: datetime
    actions: List[PolicyActionRead] = Field(default_factory=list)
    resources: List[PolicyResourceRead] = Field(default_factory=list)
    tag_conditions: List[PolicyTagConditionRead] = Field(default_factory=list)


# ── Role schemas ───────────────────────────────────────────────────────────────

class PermRoleCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    description: str | None = None


class PermRoleUpdate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = None
    description: str | None = None


class PermRoleRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    is_active: bool
    is_system: bool = False
    created_at: datetime
    updated_at: datetime
    policy_count: int = 0
    user_assignment_count: int = 0
    group_assignment_count: int = 0

    @computed_field  # type: ignore[misc]
    @property
    def role_type(self) -> str:
        """Return 'system' for system roles, 'user_defined' otherwise."""
        return "system" if self.is_system else "user_defined"


class PermRoleDetailRead(PermRoleRead):
    """Role with full nested policy statements."""
    
    model_config = {"from_attributes": True}

    policy_statements: List[PolicyStatementRead] = Field(default_factory=list)


class ResourceTypeRead(BaseModel):
    """Read schema for a resource type manifest entry (used by /policy/resource-types)."""

    resource_type: str
    actions: List[str]
    module_group: str = ""


class BatchPolicySaveRequest(BaseModel):
    """Schema for batch-replacing all policy statements for a role."""

    policies: List[PolicyStatementCreate] = Field(
        default_factory=list,
        description="Complete list of policy statements for the role. Empty list clears all policies.",
    )

    @model_validator(mode="after")
    def validate_policies(self) -> "BatchPolicySaveRequest":
        for i, policy in enumerate(self.policies):
            if not policy.actions:
                raise ValueError(f"Policy at index {i}: 'actions' must not be empty")
            if policy.module not in ("*", "*::*") and not is_valid_wildcard(policy.module):
                if policy.module not in ResourceTypeManifest:
                    raise ValueError(
                        f"Policy at index {i}: unknown module '{policy.module}'. "
                        f"Must be a valid namespaced resource type or wildcard pattern."
                    )
        return self
