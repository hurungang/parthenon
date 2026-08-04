# Namespaced Resource Types Test Plan

## Scope

Covers the migration from flat resource type identifiers to namespaced `module::submodule` format across 17 resource types in 3 modules (`agent`, `integration`, `system`), the `RolePolicyDialog` with Form/JSON dual-view editing, wildcard support (`agent::*`, `*::*`), the Alembic data migration for existing policy statements and resources, and the permission engine's `::`-delimited module matching.

---

## Coverage Areas

### 1. Namespace Structure & Manifest

**What is tested:**
- Manifest contains exactly 17 entries across 3 modules (12 agent, 2 integration, 3 system)
- Every identifier uses `module::submodule` format with `::` delimiter
- No deeper nesting than two layers
- Backend `RT_*` constants renamed/added to match new identifiers
- `GET /api/v1/policy/resource-types` returns 17 namespaced entries with `resource_type` and `actions` fields
- Flat legacy values absent from endpoint response

**Acceptance criteria:**
- Manifest structure verified: 17 keys, 3 modules
- `::` delimiter parsing: `agent::roles` splits to `("agent", "roles")`
- Module grouping: `agent` (12), `integration` (2), `system` (3)

**Test files:**
- [backend/tests/unit/test_resource_type_manifest.py](../../../../backend/tests/unit/test_resource_type_manifest.py) — Manifest structure: 17 namespaced identifiers, module grouping, legacy constant removal/alias verification, wildcard resolution helpers
- [backend/tests/unit/test_resource_type_parser.py](../../../../backend/tests/unit/test_resource_type_parser.py) — `::` delimiter parsing, flat-value rejection, three-layer rejection, empty-value rejection, edge cases (single colon, extra whitespace)
- [frontend/src/__tests__/ResourceTypeManifestMirror.test.ts](../../../../frontend/src/__tests__/ResourceTypeManifestMirror.test.ts) — Frontend mirror: all 17 identifiers match backend manifest; module groupings; no flat legacy values

---

### 2. Policy Authoring CRUD (API + UI)

**What is tested:**
- CREATE: `POST /api/v1/user-roles/{id}/policies` accepts namespaced module values; rejects flat/legacy values
- READ: Policy table displays namespaced module field values correctly
- UPDATE: `PUT /api/v1/user-roles/{id}/policies/{pid}` with namespaced identifiers
- DELETE: Policy removal with namespaced identifiers
- `AddStatementDialog`: resource type dropdown shows 17 options grouped by module (Agents, Integrations, System)
- `freeSolo` autocomplete: accepts wildcards (`agent::*`, `agent::mana*`, `*::*`, `*`) and predefined manifest values
- `freeSolo` action: accepts `*`, custom action strings, and standard predefined actions

**Acceptance criteria:**
- Full CRUD lifecycle passes with namespaced identifiers
- Flat values (`agent`, `mcp_server`, etc.) rejected with 422
- Invalid types (`agent::nonexistent`) rejected with 422
- Empty, three-layer, and malformed values rejected

**Test files:**
- [backend/tests/api/v1/test_policy_endpoints.py](../../../../backend/tests/api/v1/test_policy_endpoints.py) — Policy CRUD: POST accepts namespaced module, rejects flat/legacy; DELETE with namespaced identifiers
- [backend/tests/api/v1/test_roles_api.py](../../../../backend/tests/api/v1/test_roles_api.py) — Role CRUD with namespaced policy statements; role clone preserves namespaced module values
- [backend/tests/api/v1/test_permissions_api.py](../../../../backend/tests/api/v1/test_permissions_api.py) — Permission evaluation with namespaced identifiers; wildcard policy evaluation
- [frontend/src/__tests__/AddStatementDialog.test.tsx](../../../../frontend/src/__tests__/AddStatementDialog.test.tsx) — freeSolo autocomplete: wildcard `agent::*`, global `*::*`, wildcard `*` action, custom free-text actions

---

### 3. Wildcard Support

**What is tested:**
- `agent::*` matches all 12 agent submodules
- `integration::*` matches both integration submodules
- `system::*` matches all 3 system submodules
- `*::*` matches every resource type in the manifest (17 entries)
- Wildcards resolve to concrete submodules only (not intermediate patterns)
- Permission evaluation correctly expands wildcards to matching concrete submodules

**Acceptance criteria:**
- Modular wildcards grant correct access scopes
- Cross-module wildcards do not bleed into other modules
- `*::*` provides full platform access equivalent to legacy super admin

**Test files:**
- [backend/tests/unit/test_permission_engine.py](../../../../backend/tests/unit/test_permission_engine.py) — Module matching: exact match, `module::*` wildcard, `*::*` wildcard, boundary cases (wrong module, wrong delimiter)

---

### 4. Database Migration

**What is tested:**
- All 15 legacy flat values transformed to correct namespaced equivalents
- Consolidations: 5 values → `system::permissions`; 2 values → `agent::trails`
- No data loss: row counts preserved, correct mapping verified
- Column types unchanged: `policy_statements.module` and `policy_resources.resource_type` remain `varchar(100)`
- Migration is reversible (upgrade/downgrade cycle)
- System administrator role retains equivalent `*::*` access post-migration

**Acceptance criteria:**
- No legacy flat values remain in database after migration
- Consolidation groups produce correct effective permissions
- `alembic downgrade` succeeds without error
- `information_schema` confirms column types unchanged

**Test files:**
- [backend/tests/db/test_namespace_migration.py](../../../../backend/tests/db/test_namespace_migration.py) — Verify `information_schema` column properties; verify no legacy flat values; verify system administrator role exists (requires real PostgreSQL)
- [backend/tests/integration/test_namespace_permission_evaluation.py](../../../../backend/tests/integration/test_namespace_permission_evaluation.py) — Manifest structure validation in integration context; DB connectivity; `information_schema` column type verification

---

### 5. Role Policy Dialog (RolePolicyDialog)

**What is tested:**
- Form view: renders all existing policies pre-populated; add/edit/delete policy rows within dialog session
- JSON Source Code view: toggle from Form serializes current state; toggle from JSON deserializes back to Form
- Bidirectional sync: changes preserved when switching views
- JSON validation: parse errors with line/character references; missing `policies` array; empty `resource_type`; flat values rejected
- Batch save: Form view collects all policies and sends to batch endpoint atomically; JSON view validates then sends
- API errors: 422/500 errors displayed in dialog, unsaved changes preserved
- Unsaved changes guard: Cancel/Escape/backdrop click show confirmation dialog
- Parent table refresh: after successful save, dialog closes and parent table refreshes

**Acceptance criteria:**
- Full dialog lifecycle works with Form and JSON views
- Batch save replaces all policies atomically
- Validation failures block save with inline errors
- Unsaved changes confirmation prevents accidental data loss

**Test files:**
- [backend/tests/api/v1/test_role_policy_batch.py](../../../../backend/tests/api/v1/test_role_policy_batch.py) — Batch save endpoint: atomically replaces policies; rejects invalid/flat/empty resource types; requires auth; wildcard module patterns accepted; handles multiple policies; returns 404 for non-existent role
- [frontend/src/__tests__/RolePolicyDialog.test.tsx](../../../../frontend/src/__tests__/RolePolicyDialog.test.tsx) — Form view rendering, add/delete policy rows, JSON view toggle, batch save, loading spinner, error alerts
- [frontend/src/__tests__/RolePolicyDialog.validation.test.tsx](../../../../frontend/src/__tests__/RolePolicyDialog.validation.test.tsx) — JSON validation: malformed JSON, missing fields, flat resource types, empty actions, success indicator, unsaved changes guard (Cancel/Escape/Discard/Keep Editing), API error display

---

### 6. Dashboard Exemption & Backward Compatibility

**What is tested:**
- Dashboard page (`/`) remains accessible without any permission check
- No `require_permission()` decorator added to dashboard route during refactor
- Existing role clone preserves namespaced identifiers in cloned policies

**Acceptance criteria:**
- Unauthenticated/unauthorized users can reach dashboard
- No regression on existing route accessibility

**Test files:**
- Covered by existing E2E dashboard and role management tests
- [backend/tests/api/v1/test_roles_api.py](../../../../backend/tests/api/v1/test_roles_api.py) — Role clone with namespaced identifiers

---

## E2E Test Coverage

| Test File | Coverage |
|-----------|----------|
| [e2e/tests/namespace-resource-types.spec.ts](../../../../e2e/tests/namespace-resource-types.spec.ts) | Resource types endpoint returns 17 namespaced entries; all 3 modules present; wildcard recognition; auth protection |
| [e2e/tests/namespace-migration-visibility.spec.ts](../../../../e2e/tests/namespace-migration-visibility.spec.ts) | Dashboard accessibility; roles API availability; resource-types endpoint availability; clone endpoint auth check |
| [e2e/tests/namespace-validation-errors.spec.ts](../../../../e2e/tests/namespace-validation-errors.spec.ts) | Submit flat/legacy resource type → endpoint rejects; unknown type → rejects; empty type → rejects; three-layer type → rejects; valid namespaced type → endpoint exists |
| [e2e/tests/role-policy-management.spec.ts](../../../../e2e/tests/role-policy-management.spec.ts) | Role policy CRUD with namespaced resource types; real-backend integration tests |
| [e2e/tests/role-policy-dialog.spec.ts](../../../../e2e/tests/role-policy-dialog.spec.ts) | Resource types endpoint; batch save auth requirement; flat resource type rejection; empty policies acceptance; roles page rendering; module groups; wildcard module values in batch save |

---

## Critical Edge Cases & Risks

| Risk | Mitigation |
|------|------------|
| Consolidation silently elevates privileges (5 types → `system::permissions`) | Integration test verifying a role with only `system::permissions:manage` can access all consolidated endpoints |
| Wildcard parsing errors (`agent::*` incorrectly matches via string prefix) | Unit test verifying wildcard expansion uses exact manifest enumeration, not string matching |
| Migration data loss for consolidation paths (2 types → 1) | Migration integration test with pre-seeded data; verify no rows lost, no duplicates |
| Backward reference breakage (~185 `require_permission()` call sites) | Static analysis to verify no old constant name remains; unit test importing all renamed constants |
| Frontend/backend manifest drift | E2E test verifying dropdown options match backend endpoint response exactly |
| Dashboard accidentally gated by new permission check | Explicit E2E test that user can reach dashboard without specific permissions |
| `TagDefinition.resource_type` inconsistency with flat values | Documented as out of scope; test that existing tag-scoped policies continue to work |
| Alembic downgrade with new types (7 have no legacy equivalent) | Test downgrade migration to confirm it completes without error |
| Dialog bidirectional sync data loss during Form↔JSON toggle | Unit test verifying exact round-trip fidelity for add, edit, and delete operations |
| Batch save atomicity (partial success) | Integration test: batch save with one invalid policy rejects entire operation, leaves existing policies unchanged |

---

## Test Execution Summary

| Layer | Files | Status |
|-------|-------|--------|
| Backend — Unit | `test_resource_type_manifest.py`, `test_resource_type_parser.py`, `test_permission_engine.py` | ✅ COMPLETE (53 tests) |
| Backend — API | `test_policy_endpoints.py`, `test_roles_api.py`, `test_permissions_api.py`, `test_role_policy_batch.py` | ✅ COMPLETE (37 tests) |
| Backend — DB | `test_namespace_migration.py`, `test_namespace_permission_evaluation.py` | ✅ COMPLETE (9 tests) |
| Frontend (Vitest) | `AddStatementDialog.test.tsx`, `ResourceTypeManifestMirror.test.ts`, `RolePolicyDialog.test.tsx`, `RolePolicyDialog.validation.test.tsx` | ✅ COMPLETE (58 tests) |
| E2E (Playwright) | `namespace-resource-types.spec.ts`, `namespace-migration-visibility.spec.ts`, `namespace-validation-errors.spec.ts`, `role-policy-management.spec.ts`, `role-policy-dialog.spec.ts` | ✅ COMPLETE (33 tests) |
