"""Roles schemas — convenience re-export from perm_roles for the roles API router."""

from pydantic import Field

from app.schemas.perm_roles import (  # noqa: F401
    PermRoleCreate as RoleCreate,
)
from app.schemas.perm_roles import (
    PermRoleRead as RoleRead,
)
from app.schemas.perm_roles import (
    PolicyStatementRead,
)


class RoleDetailRead(RoleRead):
    """Role with expanded list of policy statements."""

    policies: list[PolicyStatementRead] = Field(default_factory=list)
