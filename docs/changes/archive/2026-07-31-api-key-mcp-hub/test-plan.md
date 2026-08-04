# Test Plan — API Key MCP Hub

## Test Strategy

### Overall Approach

This feature touches three layers: **Control Center** (database, API, permission engine), **Communication Hub** (auth middleware, MCP endpoint), and **Frontend** (API key management page). Testing spans all three test layers defined in the project's test pyramid.

| Layer | Framework | Focus |
|-------|-----------|-------|
| **Backend Unit & Integration** | pytest (real PostgreSQL) | API key CRUD endpoints, internal validation API, hash/verify logic, permission resolution chain, `updated_at` backfill, schema verification, audit logging |
| **Frontend Component** | Vitest + React Testing Library | API key list page, create/revoke dialogs, one-time display, status filter, error handling, parent table refresh |
| **E2E** | Playwright | Full admin workflow: create → view → revoke; external agent auth flow; load_skills with `since` parameter; real-backend integration verifying DB schema changes |

### Scope Boundaries

- **Unit Tests**: Pure business logic — key generation, hashing, validation, permission resolution, skill timestamp filtering
- **Integration Tests**: API endpoints against real PostgreSQL — CRUD, auth validation, audit log writes, constraint enforcement
- **E2E Mocked**: Fast UI flows with `page.route()` for admin management; skill discovery flow simulation
- **E2E Real Backend**: One dedicated suite hitting real running services to catch migration issues, auth middleware gaps, and inter-service wiring errors

**Gate**: 100% pass rate across all three layers required. PRD acceptance criteria must each map to at least one test case.

---

## Coverage Areas

### 1. API Key CRUD Management (Control Center Backend)

**Why critical**: API keys are the entry point for external agent access. Every CRUD operation must be correct, secure, and audited. A bug in key creation (storing plaintext), revocation (key not immediately invalidated), or listing (leaking key metadata) creates security incidents.

**What to cover**:
- Key creation with valid identity + role binding
- One-time clear-text key return; hash-only persistence
- Duplicate constraint enforcement: one active key per identity-role pair
- Key revocation (status update, immediate invalidation)
- Key list with filtering by status (active/revoked)
- Automatic table refresh after create and revoke — no manual reload needed
- Audit log entries for create and revoke operations
- `created_by` linkage to the admin who issued the key

### 2. API Key Authentication (Communication Hub)

**Why critical**: This is the new auth path that opens the platform to external agents. Must authenticate correctly without breaking existing mTLS cert auth, must never leak identity tokens to external callers, and must enforce the same permission model as internal agents.

**What to cover**:
- Bearer token and query parameter key extraction
- Internal CC validation call succeeds for valid active keys
- Invalid, revoked, or non-existent keys receive clear auth error responses
- Key validation resolves bound identity, role, and full permission set
- External agent NEVER receives the identity token in any response
- Auth failure logging (invalid key, revoked key, missing key)
- Existing mTLS cert auth path continues unchanged (no regression)

### 3. Permission Resolution (Control Center)

**Why critical**: The entire security model depends on correct permission resolution from the API key path. The resolution chain (key → identity → role → permissions) must produce identical results to the internal agent path for the same role.

**What to cover**:
- Resolution chain: API key → bound identity → bound role → policy evaluation → allowed tools/skills/SOPs
- Identity-token resolution returns the same token used for internal agent proxying
- Permission set is identical to what an internal agent with the same role would receive

### 4. Skill Loading & Version Tracking

**Why critical**: This is a new system tool that external agents depend on for skill discovery and caching. Incorrect `updated_at` timestamps cause agents to miss updates or re-download unnecessarily.

**What to cover**:
- `load_skills` returns all skills permitted by the bound role
- Response includes full tool definitions with input/output schemas
- `updated_at` timestamp present on every skill in the response
- `since` parameter filters to only skills modified after the given timestamp
- Skills with `updated_at` <= `since` are excluded from the response
- Backfill: existing skills without `updated_at` have it set to `created_at`
- Skill update triggers `updated_at` change

### 5. Audit & Security Logging

**Why critical**: Audit trail for all API key operations is necessary for security monitoring and compliance. Failed auth attempts must be visible for attack detection.

**What to cover**:
- `ApiKeyUsageLog` entries created for validate, load_skills, and tool_call actions
- Log entries include api_key_id (not key value), action, tool_name, ip_address, timestamp, success flag
- Failed auth attempts logged with success=false
- Audit log entries are append-only (never modified or deleted)
- Key creation and revocation events recorded in audit log

### 6. Frontend API Key Management Page

**Why critical**: This is the admin-facing UI for the entire API key lifecycle. Errors in the UI (key not displayed, list not refreshing) render the feature unusable.

**What to cover**:
- API key list page with columns: name, bound identity, bound role, created date, last used date, status
- Status filter dropdown (active/revoked/all)
- Create dialog with identity dropdown and role dropdown (pre-populated from existing data)
- Clear-text key displayed once at creation with copy mechanism
- Clear-text key never shown again after dialog close
- Revoke confirmation dialog
- List auto-refreshes after create without manual page reload
- List auto-refreshes after revoke without manual page reload
- Revoked items show "revoked" status chip and cannot be re-activated
- Error handling: 403, 422, and 500 displayed inside dialog (using dialog error pattern)
- No regression: existing agent management, role management, MCP pages unaffected

### 7. Schema & Migration Verification

**Why critical**: `has_db_changes: true`. The `api_keys` table must be created correctly with all constraints, and the `skills.updated_at` backfill must run. Missed migrations cause production failures.

**What to cover**:
- `api_keys` table exists with all columns: id, name, key_hash, key_prefix, agent_identity_id, agent_role_id, status, created_at, last_used_at, created_by
- `api_key_usage_logs` table exists with all columns
- `status` enum on `api_keys` contains `active` and `revoked` values
- One-active-key-per-identity-role constraint enforced
- `key_hash` uses SHA-256; column never stores plaintext
- `skills.updated_at` backfill: no NULL values after migration
- Foreign key constraints: `agent_identity_id` → `agent_identities`, `agent_role_id` → `agent_roles`

### 8. No Regression — Internal Agent Auth Path

**Why critical**: Stated requirement. Existing mTLS certificate-based agent authentication must work identically after this change.

**What to cover**:
- Internal Agent Runtime connects via mTLS cert — accepted as before
- Internal agent discovers skills and invokes tools identically
- No changes to identity token resolution or proxying for internal agents
- Web UI agent management, role management, MCP server management pages unaffected

---

## Critical Scenarios

### API Key Lifecycle — Admin CRUD

**WHEN** a Platform Administrator creates an API key by selecting an agent identity and agent role from dropdowns
**THEN** the key is generated, stored as a hash, the clear-text key is displayed once in the dialog, and the API key list auto-refreshes showing the new entry with status "active"

**WHEN** the Platform Administrator closes the create dialog (or navigates away) after creating a key
**THEN** the clear-text key is never retrievable again; only the key_prefix and metadata are visible in the list

**WHEN** a Platform Administrator views the API key list
**THEN** the list shows columns: name/label, bound agent identity, bound agent role, creation date, last used date, status (active/revoked chip)

**WHEN** a Platform Administrator filters the API key list by status "revoked"
**THEN** only revoked keys are shown; active keys are hidden

**WHEN** a Platform Administrator clicks "Revoke" on an active API key and confirms in the dialog
**THEN** the key's status changes to "revoked", the list auto-refreshes, and the revoked key immediately becomes unusable for authentication

**WHEN** a revoked API key is displayed in the list
**THEN** no "re-activate" or "un-revoke" action is available; the key is permanently deactivated

### API Key Authentication — External Agent

**WHEN** an external agent connects to the Communication Hub MCP endpoint with a valid active API key in the `Authorization: Bearer` header
**THEN** the CH validates the key via CC internal API, resolves the identity+role+permissions, establishes a connection, and the agent can discover skills and invoke tools

**WHEN** an external agent connects with an API key in the `?apiKey=` query parameter
**THEN** authentication succeeds identically to the Bearer token path

**WHEN** an external agent connects with an invalid, revoked, or non-existent API key
**THEN** the CH returns a clear authentication error response; the failed attempt is logged with the key identifier (if available)

**WHEN** an external agent successfully authenticates
**THEN** the agent NEVER receives the identity token in ANY response; the identity token is held exclusively by the Communication Hub for proxying MCP requests to downstream servers

**WHEN** an authenticated external agent invokes a tool
**THEN** the CH verifies the tool is in the resolved permission set, proxies the request with the identity token, and returns the result — the external agent never sees or handles the identity token

### Skill Discovery & Version Tracking

**WHEN** an external agent calls `load_skills` without a `since` parameter
**THEN** all skills permitted by the bound role are returned with full tool definitions, input/output schemas, and `updated_at` timestamps

**WHEN** an external agent calls `load_skills` with a `since` timestamp
**THEN** only skills where `updated_at > since` are returned; skills not modified since the given timestamp are excluded

**WHEN** an administrator updates a skill definition
**THEN** the skill's `updated_at` timestamp is automatically set to the current time

**WHEN** an existing skill has no `updated_at` value (pre-migration)
**THEN** the migration backfills `updated_at` to the skill's `created_at` value

### Internal Agent — No Regression

**WHEN** an internal Agent Runtime instance connects via mTLS certificate
**THEN** authentication succeeds; skill discovery and tool invocation work identically to before the change

**WHEN** an internal Agent Runtime carries a valid mTLS certificate
**THEN** the CH routes the request through the existing cert middleware — the API key validator is NOT invoked

### Security & Audit

**WHEN** an API key is created or revoked
**THEN** an audit log entry is recorded with the operator's identity, key identifier (not key value), and operation timestamp

**WHEN** an API key is used for authentication (validate), skill discovery (load_skills), or tool invocation (tool_call)
**THEN** an `ApiKeyUsageLog` entry is created with the api_key_id, action type, tool_name (if applicable), client IP, timestamp, and success status

**WHEN** an authentication attempt fails with an invalid, expired, or revoked key
**THEN** the failure is logged for security monitoring; the log includes the attempted key identifier or indication of an unrecognized key

**WHEN** authentication attempts exceed the rate limit threshold
**THEN** subsequent attempts are throttled to prevent brute-force attacks

---

## Edge Cases & Risks

### Data Integrity

- **Duplicate key creation**: Attempting to create a second active key for the same identity-role pair returns 409 Conflict with a clear message
- **Key created with a deleted identity or role**: Foreign key constraints prevent this; if an identity is deleted after key creation, the key remains but validation should fail gracefully
- **Key created while identity is deactivated**: Key creation should be allowed (admin may activate identity later), but authentication should fail with a clear message until the identity is active
- **Empty key list**: Page renders empty state message; no crashes
- **Skill with NULL `updated_at` after migration**: Backfill must be verified; the `since` filter must handle edge case where timestamp comparison fails silently

### Race Conditions

- **Concurrent key creation for same identity-role pair**: Unique constraint enforcement at database level; second request returns 409
- **Key revoked while external agent is mid-session**: Already-established connections should be terminated on next auth check or tool call; tool calls after revocation return auth error
- **Skill updated while agent is downloading**: Agent receives the new `updated_at` on its next sync; no partial or corrupted downloads

### Security Edge Cases

- **API key submitted via both Bearer header AND query parameter**: One takes precedence (documented behavior); no ambiguous dual-auth
- **Key prefix guessing**: `key_prefix` is public (e.g., `phn_sk_`) but provides no advantage for brute-forcing the full key since the hash uses SHA-256 over the full key value
- **Key value in logs**: Key value must NEVER appear in any log (application, audit, or access log); only the key ID or prefix may appear
- **mTLS cert + API key on same request**: CH must reject requests carrying both auth types; only one auth method per request
- **Token injection attack path**: External agent sends a crafted `Authorization` header alongside an API key to attempt identity token injection — CH must detect and reject
- **CC internal validation endpoint exposed externally**: The `POST /internal/auth/validate-api-key` endpoint must reject all callers except Communication Hub (enforced by mTLS service certificate); external requests receive 403

### UI Edge Cases

- **Create dialog opened with no identities or no roles**: Dropdowns show empty state; form submission blocked until selections made
- **Create dialog with very long key**: Display handles truncation gracefully with copy button
- **Key list pagination with mixed active/revoked items**: Filter applies before pagination; page count updates correctly on filter change
- **Rapid create-revoke-create cycle**: Each operation succeeds independently; list refreshes correctly each time
- **Browser back/forward after key creation**: Clear-text key is never visible again; page shows list view

### Performance Risks

- **Large number of API keys in the list**: Pagination handles this; query performance acceptable with indexing on status and identity_id
- **External agent with many skills (100+)**: `load_skills` response size manageable; incremental sync via `since` parameter reduces payload for repeat calls
- **Audit log growth**: `ApiKeyUsageLog` entries are append-only; consider retention archiving strategy for production deployment (out of scope for this change)

### Deployment Risks

- **Migration applied out of order**: Alembic version chain verification before deployment
- **Partial rollback**: If `api_keys` table is created but the Communication Hub hasn't been updated, existing flows unaffected (table is unused). If CH is updated but migration hasn't run, auth path fails gracefully (table not found → 503).
- **Skill backfill on large dataset**: `UPDATE skills SET updated_at = created_at WHERE updated_at IS NULL` must complete within migration timeout; test against production-scale data volume

---

## Acceptance Criteria Checklist

Maps each PRD acceptance criterion to coverage areas.

### API Key CRUD Management

- [ ] **AC-CRUD-01**: Platform Administrator can create a new API key by selecting an existing agent identity and an agent role from dropdowns → *Coverage: Backend Unit/Integration, Frontend Component, E2E Mocked*
- [ ] **AC-CRUD-02**: Created API key is displayed once at creation time; key value is never shown again → *Coverage: Frontend Component, E2E Mocked*
- [ ] **AC-CRUD-03**: API keys are stored hashed; clear-text key never retrievable after creation → *Coverage: Backend Unit/Integration, Schema Verification*
- [ ] **AC-CRUD-04**: API key list shows columns: name/label, bound identity, bound role, creation date, last used date, status → *Coverage: Frontend Component, E2E Mocked*
- [ ] **AC-CRUD-05**: Can revoke an API key with confirmation dialog → *Coverage: Frontend Component, E2E Mocked*
- [ ] **AC-CRUD-06**: Revoked key immediately unusable for authentication → *Coverage: Backend Integration, E2E Real Backend*
- [ ] **AC-CRUD-07**: Revoked key remains in list with "revoked" status; cannot be re-activated → *Coverage: Frontend Component, E2E Mocked*
- [ ] **AC-CRUD-08**: API key list auto-refreshes after create or revoke — no manual reload → *Coverage: Frontend Component, E2E Mocked*
- [ ] **AC-CRUD-09**: Can filter API key list by status (active/revoked) → *Coverage: Frontend Component*

### API Key Authentication on Communication Hub

- [ ] **AC-AUTH-01**: External agent authenticates via Bearer token (`Authorization: Bearer <api_key>`) → *Coverage: Backend Integration, E2E Real Backend*
- [ ] **AC-AUTH-02**: External agent authenticates via query parameter (`?apiKey=<api_key>`) → *Coverage: Backend Integration, E2E Real Backend*
- [ ] **AC-AUTH-03**: Invalid or revoked API keys receive clear authentication error → *Coverage: Backend Integration, E2E Real Backend*
- [ ] **AC-AUTH-04**: Successful auth resolves bound identity, role, and permitted skills/tools → *Coverage: Backend Integration*
- [ ] **AC-AUTH-05**: External agents only access skills/tools granted by bound role → *Coverage: Backend Integration*
- [ ] **AC-AUTH-06**: External agents NEVER receive identity token → *Coverage: Backend Integration, E2E Real Backend*

### Skill Loading and Version Tracking

- [ ] **AC-SKILL-01**: `load_skills` returns all permitted skills with full tool definitions and schemas → *Coverage: Backend Integration, E2E Mocked*
- [ ] **AC-SKILL-02**: Each skill includes `updated_at` timestamp → *Coverage: Backend Integration, Schema Verification*
- [ ] **AC-SKILL-03**: `since` parameter / `get_skill_updates` returns only changed skills → *Coverage: Backend Integration*

### Security and Audit

- [ ] **AC-SEC-01**: Key create/revoke events recorded in audit log → *Coverage: Backend Integration, Schema Verification*
- [ ] **AC-SEC-02**: Key usage logged with key identifier (not key value) → *Coverage: Backend Integration*
- [ ] **AC-SEC-03**: CH→CC internal calls mTLS-secured with service certificates → *Coverage: Backend Integration*
- [ ] **AC-SEC-04**: Failed authentication attempts logged → *Coverage: Backend Integration*
- [ ] **AC-SEC-05**: Rate limiting applied to auth attempts → *Coverage: Backend Integration*

### No Regression

- [ ] **AC-REGRESS-01**: Existing certificate-based agent auth continues unchanged → *Coverage: Backend Integration, E2E Real Backend*
- [ ] **AC-REGRESS-02**: Internal Agent Runtime agents can connect, discover skills, and invoke tools as before → *Coverage: E2E Real Backend*
- [ ] **AC-REGRESS-03**: Web UI agent management, role management, MCP pages unaffected → *Coverage: Frontend Component, E2E*

---

## Pre-Test Checklist for Database Changes

> **`has_db_changes: true`** — The following steps MUST be completed before running any tests.

### Migration Verification

- [ ] Confirm Alembic migration file exists in `backend/alembic/versions/` for the `api_keys` and `api_key_usage_logs` tables
- [ ] Confirm data migration file exists for `skills.updated_at` backfill
- [ ] Run `alembic upgrade head` against local test database
- [ ] Verify with `alembic current` that the latest migration revision is applied

### Schema Verification

- [ ] `api_keys` table exists with columns: `id` (uuid), `name` (string), `key_hash` (string), `key_prefix` (string), `agent_identity_id` (uuid FK), `agent_role_id` (uuid FK), `status` (enum: active/revoked), `created_at` (datetime), `last_used_at` (datetime nullable), `created_by` (uuid FK)
- [ ] `api_key_usage_logs` table exists with columns: `id` (uuid), `api_key_id` (uuid FK), `action` (enum: validate/load_skills/tool_call), `tool_name` (string nullable), `ip_address` (string nullable), `timestamp` (datetime), `success` (boolean)
- [ ] Unique constraint on (`agent_identity_id`, `agent_role_id`, `status`) for active keys
- [ ] `skills.updated_at` column has no NULL values after backfill migration
- [ ] Foreign key `agent_identity_id` references `agent_identities.id`
- [ ] Foreign key `agent_role_id` references `agent_roles.id`

### Database Test Fixture

- [ ] Test conftest applies migrations via `alembic upgrade head` before test session
- [ ] Test database matches production schema (same Alembic head)
- [ ] Backend integration tests use real PostgreSQL (not in-memory SQLite)

---

## Test File References

> Paths from `docs/config.yaml` `source.tests`: `backend/tests/`, `frontend/src/__tests__/`, `e2e/tests/`

### Backend Unit Tests (`backend/tests/`)

| Test File | Coverage |
|-----------|----------|
| `backend/tests/test_api_key_service.py` | ✅ Key generation (randomness, length), SHA-256 hashing, hash comparison, key prefix generation — 8 tests |
| `backend/tests/test_api_key_admin_api.py` | ✅ Pydantic schema validation for all API key schemas — 13 tests |

### Backend Integration Tests (`backend/tests/`)

| Test File | Coverage |
|-----------|----------|
| `backend/tests/api/v1/test_api_keys_api.py` | ✅ Full CRUD: create (POST with identity_id + role_id, one-time clear-text return), list (GET with status filter), revoke (POST revoke), duplicate prevention (409), 404 for non-existent key, auth required (401), validation errors (422), idempotent revoke — 12 tests |
| `backend/tests/communication_hub/api/internal/test_validate_api_key.py` | ✅ Internal validation endpoint: valid active key returns identity token + permissions, revoked key returns 401, invalid/unknown key returns 401, empty key_hash returns 422, `since` parameter flow, service cert requirement — 6 tests |
| `backend/tests/integration/test_api_key_schema.py` | ✅ Schema verification: model columns, column lengths, enum values (`active`, `revoked`, `validate`/`load_skills`/`tool_call`), FK constraints (CASCADE), unique constraint (uq_agent_api_keys_identity_role), indexes, no-plaintext-storage negative test — 17 tests |

### Frontend Component Tests (`frontend/src/__tests__/`)

| Test File | Coverage |
|-----------|----------|
| `frontend/src/__tests__/api-keys/ApiKeyListPage.test.tsx` | ✅ Table rendering with columns, status filter, empty state, error state, loading state, key rows, identity/role names — 7 tests |
| `frontend/src/__tests__/api-keys/CreateApiKeyDialog.test.tsx` | ✅ Identity dropdown populated from existing identities, role dropdown filtered by identity, form validation (create button disabled when incomplete, enabled when complete), clear-text key step 2, copy button, error handling, form reset on close/reopen, scoping info, save key warning — 13 tests |
| `frontend/src/__tests__/api-keys/RevokeApiKeyDialog.test.tsx` | ✅ Confirmation dialog with key name, identity/role info, revoke API call triggers onRevoke, error handling, cancel button, loading state during revoke — 11 tests |
| `frontend/src/__tests__/api-keys/useApiKeys.test.tsx` | ✅ Hook data fetching, loading state, error state, status filter — 5 tests |

### E2E Tests (`e2e/tests/`)

| Test File | Coverage |
|-----------|----------|
| `e2e/tests/api-key-management.spec.ts` | ✅ **Mocked suite** (3 test.describe blocks): Full admin CRUD flow — page renders, key names/identities/roles/status chips visible, create button, info banner, status filter, create dialog with name/identity/role fields, step 2 success view, revoke dialog with warning/confirmation, filter options. **Real backend suite**: endpoint auth checks (GET/POST require auth), health endpoint verification — 27 tests |

---

## Test Execution Order

1. **Pre-test**: Run pre-test checklist for database changes (migrations, fixtures)
2. **Backend Unit Tests**: Fast feedback on business logic correctness
3. **Backend Integration Tests**: API endpoint correctness, schema verification, database constraint enforcement
4. **Frontend Component Tests**: UI rendering, state management, dialog workflows
5. **E2E Mocked Tests**: Full user journeys with mocked API responses
6. **E2E Real Backend Tests**: End-to-end verification against running services — catches migration issues, auth middleware gaps, inter-service wiring errors

**Gate**: All six layers must achieve 100% pass rate before marking the change as implemented.
