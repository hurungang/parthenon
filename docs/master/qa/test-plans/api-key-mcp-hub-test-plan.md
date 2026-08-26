# Test Plan — API Key MCP Hub

## Test Strategy

### Overall Approach

API Key authentication opens the platform to external agents by providing an alternative auth path alongside the existing mTLS certificate-based authentication. This feature spans three layers: **Control Center** (database, API, permission engine), **Communication Hub** (auth middleware, MCP endpoint), and **Frontend** (API key management page).

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

### Quality Gate
- 100% pass rate across all three layers required
- Each PRD acceptance criterion must map to at least one test case
- `has_db_changes: true` — migrations must be applied before testing

---

## Coverage Areas

### 1. API Key CRUD Management (Control Center Backend)
**Why critical**: API keys are the entry point for external agent access. Every CRUD operation must be correct, secure, and audited.

**Covered**:
- Key creation with valid identity + role binding
- One-time clear-text key return; hash-only persistence
- Duplicate constraint enforcement: one active key per identity-role pair
- Key revocation (status update, immediate invalidation)
- Key list with filtering by status (active/revoked)
- Automatic table refresh after create and revoke
- Audit log entries for create and revoke operations
- `created_by` linkage to the admin who issued the key

### 2. API Key Authentication (Communication Hub)
**Why critical**: New auth path that opens the platform to external agents. Must never leak identity tokens.

**Covered**:
- Bearer token and query parameter key extraction
- Internal CC validation for valid active keys
- Invalid, revoked, or non-existent keys return clear auth error
- Key validation resolves bound identity, role, and full permission set
- External agent NEVER receives the identity token in any response
- Auth failure logging (invalid key, revoked key, missing key)
- Existing mTLS cert auth path continues unchanged (no regression)

### 3. Permission Resolution (Control Center)
**Why critical**: Resolution chain must produce identical results to internal agent path.

**Covered**:
- Resolution chain: API key → bound identity → bound role → policy evaluation → allowed tools/skills/SOPs
- Identity-token resolution returns same token used for internal agent proxying
- Permission set identical to internal agent with same role

### 4. Skill Loading & Version Tracking
**Why critical**: External agents depend on this for skill discovery and caching.

**Covered**:
- `load_skills` returns all skills permitted by bound role
- Response includes full tool definitions with input/output schemas
- `updated_at` timestamp present on every skill
- `since` parameter filters to only skills modified after given timestamp
- Skills with `updated_at` <= `since` are excluded
- Backfill: existing skills without `updated_at` have it set to `created_at`
- Skill update triggers `updated_at` change

### 5. Audit & Security Logging
**Why critical**: Audit trail for security monitoring and compliance.

**Covered**:
- `ApiKeyUsageLog` entries for validate, load_skills, and tool_call actions
- Log entries include api_key_id (not key value), action, tool_name, ip_address, timestamp, success flag
- Failed auth attempts logged with success=false
- Audit log entries are append-only
- Key creation and revocation events recorded in audit log

### 6. Frontend API Key Management Page
**Why critical**: Admin-facing UI for entire API key lifecycle.

**Covered**:
- Table columns: name, bound identity, bound role, created date, last used date, status
- Status filter dropdown (active/revoked/all)
- Create dialog with identity and role dropdowns
- Clear-text key displayed once at creation with copy mechanism
- Clear-text key never shown again after dialog close
- Revoke confirmation dialog
- List auto-refreshes after create and revoke (no manual reload)
- Revoked items show "revoked" status chip; cannot be re-activated
- Error handling: 403, 422, 500 displayed inside dialog (dialog error pattern)
- No regression on existing agent/role/MCP pages

### 7. Schema & Migration Verification
**Why critical**: `has_db_changes: true`. The `api_keys` table and `skills.updated_at` backfill must be correct.

**Covered**:
- `api_keys` table: all columns (id, name, key_hash, key_prefix, agent_identity_id, agent_role_id, status, created_at, last_used_at, created_by)
- `api_key_usage_logs` table: all columns
- `status` enum: active, revoked
- One-active-key-per-identity-role constraint
- `key_hash` uses SHA-256; never stores plaintext
- `skills.updated_at` backfill: no NULL values after migration
- Foreign key constraints verified

### 8. No Regression — Internal Agent Auth Path
**Why critical**: Stated requirement. mTLS certificate-based auth must work identically.

**Covered**:
- Internal Agent Runtime mTLS cert accepted as before
- Internal agent discovers skills and invokes tools identically
- No changes to identity token resolution or proxying for internal agents
- Web UI agent/role/MCP pages unaffected

### 9. API Key Expiration
**Why critical**: Expiration is time-based access control; a missed check leaves external access open past the intended window.

**Covered**:
- Key creation with optional `expires_at`; omitting it yields a non-expiring key (`NULL`)
- `is_key_expired` logic for none / future / past / timezone-naive datetime cases
- Expired key rejected at authentication with a clear error (not a 500), exactly like a revoked key
- Key with future `expires_at` or no `expires_at` authenticates normally
- `expires_at` column presence and nullability verified at the schema level
- Key list surfaces expiration date (or "No expiration" when unset)

---

## Critical Scenarios

### API Key Lifecycle — Admin CRUD

**WHEN** a Platform Administrator creates an API key by selecting an agent identity and agent role from dropdowns
**THEN** the key is generated, stored as a hash, the clear-text key is displayed once in the dialog, and the API key list auto-refreshes showing the new entry with status "active"

**WHEN** the Platform Administrator closes the create dialog after creating a key
**THEN** the clear-text key is never retrievable again; only the key_prefix and metadata are visible in the list

**WHEN** a Platform Administrator views the API key list
**THEN** the list shows columns: name/label, bound agent identity, bound agent role, creation date, last used date, status (active/revoked chip)

**WHEN** a Platform Administrator filters the API key list by status "revoked"
**THEN** only revoked keys are shown; active keys are hidden

**WHEN** a Platform Administrator clicks "Revoke" on an active API key and confirms
**THEN** the key's status changes to "revoked", the list auto-refreshes, and the revoked key immediately becomes unusable

**WHEN** a revoked API key is displayed in the list
**THEN** no "re-activate" or "un-revoke" action is available; the key is permanently deactivated

### API Key Authentication — External Agent

**WHEN** an external agent connects to the Communication Hub MCP endpoint with a valid active API key in the `Authorization: Bearer` header
**THEN** the CH validates the key via CC internal API, resolves the identity+role+permissions, establishes a connection, and the agent can discover skills and invoke tools

**WHEN** an external agent connects with an API key in the `?apiKey=` query parameter
**THEN** authentication succeeds identically to the Bearer token path

**WHEN** an external agent connects with an invalid, revoked, or non-existent API key
**THEN** the CH returns a clear authentication error; the failed attempt is logged

**WHEN** an external agent successfully authenticates
**THEN** the agent NEVER receives the identity token in ANY response

**WHEN** an authenticated external agent invokes a tool
**THEN** the CH verifies the tool is in the resolved permission set, proxies the request with the identity token — the external agent never sees or handles the identity token

### Skill Discovery & Version Tracking

**WHEN** an external agent calls `load_skills` without a `since` parameter
**THEN** all skills permitted by the bound role are returned with full tool definitions and `updated_at` timestamps

**WHEN** an external agent calls `load_skills` with a `since` timestamp
**THEN** only skills where `updated_at > since` are returned

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

**WHEN** an API key is used for authentication, skill discovery, or tool invocation
**THEN** an `ApiKeyUsageLog` entry is created with the api_key_id, action type, tool_name, client IP, timestamp, and success status

**WHEN** an authentication attempt fails with an invalid or revoked key
**THEN** the failure is logged for security monitoring

**WHEN** authentication attempts exceed the rate limit threshold
**THEN** subsequent attempts are throttled to prevent brute-force attacks

### API Key Expiration

**WHEN** a Platform Administrator creates an API key with an optional `expires_at` timestamp
**THEN** the key is stored with that timestamp and rejected at authentication once the timestamp passes

**WHEN** a Platform Administrator creates an API key without an `expires_at`
**THEN** the key is stored with `NULL` and authenticates indefinitely

**WHEN** an external agent authenticates with a key whose `expires_at` has passed
**THEN** the CH returns a clear authentication error (not a 500), exactly like a revoked key

**WHEN** an external agent authenticates with a key whose `expires_at` is in the future
**THEN** authentication succeeds normally

**WHEN** the API key list is displayed
**THEN** each key shows its expiration date, or "No expiration" when unset

---

## Edge Cases

### Data Integrity
- **Duplicate key creation**: Second active key for same identity-role pair returns 409 Conflict
- **Key with deleted identity or role**: FK constraints prevent; if identity deleted after key creation, validation fails gracefully
- **Key created while identity is deactivated**: Creation allowed; auth fails with clear message until identity active
- **Empty key list**: Page renders empty state; no crashes
- **Skill with NULL `updated_at` after migration**: Backfill must be verified; `since` filter handles edge case

### Race Conditions
- **Concurrent key creation for same identity-role pair**: DB unique constraint enforces; second request returns 409
- **Key revoked while external agent is mid-session**: Already-established connections terminated on next auth check; tool calls after revocation return auth error
- **Skill updated while agent is downloading**: Agent receives new `updated_at` on next sync; no partial/corrupted downloads

### Security Edge Cases
- **API key via both Bearer header AND query parameter**: One takes precedence; no ambiguous dual-auth
- **Key prefix guessing**: `key_prefix` is public but provides no advantage for brute-forcing (SHA-256 over full key)
- **Key value in logs**: Key value must NEVER appear in any log; only key ID or prefix may appear
- **mTLS cert + API key on same request**: CH must reject requests carrying both auth types
- **Token injection attack path**: External agent sends crafted `Authorization` header alongside API key — CH must detect and reject
- **CC internal validation endpoint exposed externally**: `POST /internal/auth/validate-api-key` must reject all callers except Communication Hub (mTLS service certificate enforcement)

### UI Edge Cases
- **Create dialog with no identities or no roles**: Dropdowns show empty state; form submission blocked
- **Create dialog with very long key**: Display handles truncation gracefully with copy button
- **Key list pagination with mixed active/revoked items**: Filter applies before pagination
- **Rapid create-revoke-create cycle**: Each operation succeeds independently; list refreshes correctly
- **Browser back/forward after key creation**: Clear-text key is never visible again; page shows list view

### Performance Risks
- **Large number of API keys**: Pagination handles; indexing on status and identity_id
- **External agent with many skills (100+)**: `load_skills` response size manageable; incremental sync via `since` parameter
- **Audit log growth**: `ApiKeyUsageLog` entries are append-only; retention archiving strategy out of scope

### Deployment Risks
- **Migration applied out of order**: Alembic version chain verification before deployment
- **Partial rollback**: If api_keys table exists but CH hasn't been updated, existing flows unaffected. If CH is updated but migration hasn't run, auth path fails gracefully (table not found → 503)
- **Skill backfill on large dataset**: `UPDATE skills SET updated_at = created_at WHERE updated_at IS NULL` must complete within migration timeout

---

## Acceptance Criteria Checklist

### API Key CRUD Management
- [ ] **AC-CRUD-01**: Platform Administrator can create a new API key by selecting an existing agent identity and an agent role from dropdowns
- [ ] **AC-CRUD-02**: Created API key is displayed once at creation time; key value is never shown again
- [ ] **AC-CRUD-03**: API keys are stored hashed; clear-text key never retrievable after creation
- [ ] **AC-CRUD-04**: API key list shows columns: name/label, bound identity, bound role, creation date, last used date, status
- [ ] **AC-CRUD-05**: Can revoke an API key with confirmation dialog
- [ ] **AC-CRUD-06**: Revoked key immediately unusable for authentication
- [ ] **AC-CRUD-07**: Revoked key remains in list with "revoked" status; cannot be re-activated
- [ ] **AC-CRUD-08**: API key list auto-refreshes after create or revoke — no manual reload
- [ ] **AC-CRUD-09**: Can filter API key list by status (active/revoked)

### API Key Authentication on Communication Hub
- [ ] **AC-AUTH-01**: External agent authenticates via Bearer token (`Authorization: Bearer <api_key>`)
- [ ] **AC-AUTH-02**: External agent authenticates via query parameter (`?apiKey=<api_key>`)
- [ ] **AC-AUTH-03**: Invalid or revoked API keys receive clear authentication error
- [ ] **AC-AUTH-04**: Successful auth resolves bound identity, role, and permitted skills/tools
- [ ] **AC-AUTH-05**: External agents only access skills/tools granted by bound role
- [ ] **AC-AUTH-06**: External agents NEVER receive identity token

### Skill Loading and Version Tracking
- [ ] **AC-SKILL-01**: `load_skills` returns all permitted skills with full tool definitions and schemas
- [ ] **AC-SKILL-02**: Each skill includes `updated_at` timestamp
- [ ] **AC-SKILL-03**: `since` parameter / `get_skill_updates` returns only changed skills

### Security and Audit
- [ ] **AC-SEC-01**: Key create/revoke events recorded in audit log
- [ ] **AC-SEC-02**: Key usage logged with key identifier (not key value)
- [ ] **AC-SEC-03**: CH→CC internal calls mTLS-secured with service certificates
- [ ] **AC-SEC-04**: Failed authentication attempts logged
- [ ] **AC-SEC-05**: Rate limiting applied to auth attempts

### No Regression
- [ ] **AC-REGRESS-01**: Existing certificate-based agent auth continues unchanged
- [ ] **AC-REGRESS-02**: Internal Agent Runtime agents can connect, discover skills, and invoke tools as before
- [ ] **AC-REGRESS-03**: Web UI agent management, role management, MCP pages unaffected

### API Key Expiration
- [ ] **AC-EXP-01**: Administrator can create a key with an optional `expires_at`; omitting it yields a non-expiring key
- [ ] **AC-EXP-02**: A key with a past `expires_at` is rejected at authentication with a clear error
- [ ] **AC-EXP-03**: A key with a future `expires_at` or no `expires_at` authenticates normally
- [ ] **AC-EXP-04**: The key list shows each key's expiration date (or "No expiration")

---

## Pre-Test Checklist (Database Changes)

> **`has_db_changes: true`** — Complete before running tests.

### Migration Verification
- [ ] Confirm Alembic migration file exists for api_keys and api_key_usage_logs tables
- [ ] Confirm data migration file exists for skills.updated_at backfill
- [ ] Run `alembic upgrade head` against local test database
- [ ] Verify `alembic current` shows latest migration revision

### Schema Verification
- [ ] `api_keys` table: all columns present
- [ ] `api_key_usage_logs` table: all columns present
- [ ] Unique constraint on (agent_identity_id, agent_role_id, status) for active keys
- [ ] `skills.updated_at` has no NULL values after backfill
- [ ] FK: agent_identity_id → agent_identities.id
- [ ] FK: agent_role_id → agent_roles.id

### Database Test Fixture
- [ ] Test conftest applies migrations via `alembic upgrade head` before session
- [ ] Test database matches production schema (same Alembic head)
- [ ] Backend integration tests use real PostgreSQL (not in-memory SQLite)

---

## Test File References

### Backend Unit Tests
| Test File | Coverage |
|-----------|----------|
| `backend/tests/test_api_key_service.py` | Key generation (randomness, length), SHA-256 hashing, hash comparison, key prefix generation, `is_key_expired` (none/future/past/naive-datetime cases) — 8 tests |
| `backend/tests/test_api_key_admin_api.py` | Pydantic schema validation for all API key schemas — 13 tests |

### Backend Integration Tests
| Test File | Coverage |
|-----------|----------|
| `backend/tests/api/v1/test_api_keys_api.py` | Full CRUD: create (POST, one-time clear-text return), list (GET with status filter), revoke (POST), duplicate prevention (409), 404 for non-existent, auth required (401), validation errors (422), idempotent revoke — 12 tests |
| `backend/tests/communication_hub/api/internal/test_validate_api_key.py` | Internal validation: valid active key returns identity token + permissions, revoked key returns 401, invalid/unknown returns 401, empty key_hash returns 422, since parameter flow, service cert requirement — 6 tests |
| `backend/tests/integration/test_api_key_schema.py` | Schema verification: model columns, column lengths, enum values, FK constraints (CASCADE), unique constraint, indexes, no-plaintext-storage negative test, `expires_at` column presence + nullability — 17 tests |

### Frontend Component Tests
| Test File | Coverage |
|-----------|----------|
| `frontend/src/__tests__/api-keys/ApiKeyListPage.test.tsx` | Table rendering with columns, status filter, empty state, error state, loading state, key rows, identity/role names — 7 tests |
| `frontend/src/__tests__/api-keys/CreateApiKeyDialog.test.tsx` | Identity dropdown, role dropdown filtered by identity, form validation, clear-text key step 2, copy button, error handling, form reset on close/reopen, scoping info, save key warning — 13 tests |
| `frontend/src/__tests__/api-keys/RevokeApiKeyDialog.test.tsx` | Confirmation dialog with key name, identity/role info, revoke API call, error handling, cancel button, loading state — 11 tests |
| `frontend/src/__tests__/api-keys/useApiKeys.test.tsx` | Hook data fetching, loading state, error state, status filter — 5 tests |

### E2E Tests
| Test File | Coverage |
|-----------|----------|
| `e2e/tests/api-key-management.spec.ts` | **Mocked suite** (4 test.describe blocks): Full admin CRUD flow — page renders, key names/identities/roles/status chips visible, create button, info banner, status filter, create dialog with name/identity/role fields, step 2 success view, revoke dialog with warning/confirmation, filter options. **Real backend suite**: endpoint auth checks (GET/POST require auth), health endpoint verification — 27 tests |

---

## Test Execution Order

1. **Pre-test**: Run pre-test checklist for database changes (migrations, fixtures)
2. **Backend Unit Tests**: Fast feedback on business logic correctness
3. **Backend Integration Tests**: API endpoint correctness, schema verification, database constraint enforcement
4. **Frontend Component Tests**: UI rendering, state management, dialog workflows
5. **E2E Mocked Tests**: Full user journeys with mocked API responses
6. **E2E Real Backend Tests**: End-to-end verification against running services — catches migration issues, auth middleware gaps, inter-service wiring errors

**Gate**: All six layers must achieve 100% pass rate before marking the change as implemented.
