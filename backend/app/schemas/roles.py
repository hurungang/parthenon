"""Roles schemas — convenience re-export from perm_roles for the roles API router."""
import uuid
from typing import List

from pydantic import BaseModel, Field

from app.schemas.perm_roles import (  # noqa: F401
    PermRoleCreate as RoleCreate,
    PermRoleRead as RoleRead,
    PermRoleUpdate as RoleUpdate,
    PolicyActionCreate,
    PolicyActionRead,
    PolicyEffect,
    PolicyResourceCreate,
    PolicyResourceRead,
    PolicyStatementCreate,
    PolicyStatementRead,
    PolicyTagConditionCreate,
    PolicyTagConditionRead,
)


class RoleDetailRead(RoleRead):
    """Role with expanded list of policy statements."""

    policies: List[PolicyStatementRead] = Field(default_factory=list)
