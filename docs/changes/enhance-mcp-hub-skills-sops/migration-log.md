# Database Migration Log: Agent Role Identity Assignments

## Migration Details

**Migration ID:** `7a9f2e3b4c5d`  
**Migration Name:** `replace_allowed_identity_types_with_agent_role_identities`  
**Revision Date:** 2026-05-08  
**Applied:** 2026-05-08 11:47 UTC  

## Changes

### 1. Created `agent_role_identities` Join Table

**Purpose:** Implement many-to-many relationship between agent roles and agent identities, replacing the previous type-based constraint system.

**Schema:**
```sql
CREATE TABLE agent_role_identities (
    role_id UUID NOT NULL,
    identity_id UUID NOT NULL,
    assigned_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    assigned_by UUID,
    PRIMARY KEY (role_id, identity_id),
    FOREIGN KEY (role_id) REFERENCES agent_roles(id) ON DELETE CASCADE,
    FOREIGN KEY (identity_id) REFERENCES agent_identities(id) ON DELETE CASCADE,
    CONSTRAINT uq_agent_role_identity UNIQUE (role_id, identity_id)
);

CREATE INDEX ix_agent_role_identities_role_id ON agent_role_identities(role_id);
CREATE INDEX ix_agent_role_identities_identity_id ON agent_role_identities(identity_id);
```

**Note:** `assigned_by` column does not have a foreign key constraint to `users` table as that table may not exist in all environments. This is a valid UUID field that can be used for audit purposes when a users table is present.

### 2. Dropped `allowed_identity_types` Column

**Purpose:** Remove deprecated JSON array column that previously constrained which identity types could assume a role.

**Schema Change:**
```sql
ALTER TABLE agent_roles DROP COLUMN allowed_identity_types;
```

## Migration Path

**Previous:** `53f351b9acd8` (add_allowed_identity_types_to_agent_role)  
**Current:** `7a9f2e3b4c5d` (replace_allowed_identity_types_with_agent_role_identities)

## Verification Results

### Backend Unit Tests
- **File:** `tests/unit/test_agent_role_service.py`
- **Result:** ✅ 20/20 tests passed
- **Coverage:**
  - Role CRUD operations
  - Identity assignment (create, list, check, remove)
  - Duplicate handling
  - Not found scenarios
  - Permission cache invalidation

### E2E Tests
- **File:** `tests/agent-management.spec.ts`
- **Result:** ✅ 6/6 tests passed
- **Coverage:**
  - Agent role creation and editing
  - Identity management UI
  - Full workflow validation

## Rollback Procedure

If rollback is needed:

```powershell
cd backend
alembic downgrade 53f351b9acd8
```

This will:
1. Drop `agent_role_identities` table
2. Re-add `allowed_identity_types` JSON column to `agent_roles` table

**Warning:** Rolling back will lose all identity-to-role assignments stored in `agent_role_identities` table.

## Related Changes

### Backend Services
- [backend/app/services/agents/role_service.py](../../backend/app/services/agents/role_service.py) - Added identity assignment methods
- [backend/app/api/v1/agents.py](../../backend/app/api/v1/agents.py) - Added identity assignment endpoints

### Frontend Components
- [frontend/src/pages/agents/AgentRoleDialog.tsx](../../frontend/src/pages/agents/AgentRoleDialog.tsx) - Updated to show assigned identities
- [frontend/src/pages/agents/AssignIdentitiesToRoleDialog.tsx](../../frontend/src/pages/agents/AssignIdentitiesToRoleDialog.tsx) - NEW: Assign identities to role
- [frontend/src/pages/agents/AssignRolesToIdentityDialog.tsx](../../frontend/src/pages/agents/AssignRolesToIdentityDialog.tsx) - NEW: Assign roles to identity

### Documentation
- [docs/master/architecture/spec-change.md](../master/architecture/spec-change.md) - Architecture specification
- [docs/master/data-model/data-model.md](../master/data-model/data-model.md) - Data model updates
- [docs/master/product/prd.md](../master/product/prd.md) - Product requirements

## Post-Migration Notes

1. ✅ All backend services restarted successfully
2. ✅ Schema changes verified in database
3. ✅ All tests passing (backend unit + E2E)
4. ✅ No data migration required (fresh implementation)

## Approval

**Product Owner:** ✅ Approved (2026-05-08)  
**Architect:** ✅ Approved (schema design)  
**Developer:** ✅ Implemented and tested  
**Tester:** ✅ All tests passing  

---

**Migration Status:** ✅ COMPLETE
