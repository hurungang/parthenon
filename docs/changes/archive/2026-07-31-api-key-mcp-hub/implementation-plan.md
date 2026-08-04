# Implementation Plan: API Key MCP Hub

## Overview

This change adds API key authentication to Parthenon's Communication Hub so external third-party AI agents can connect via standard MCP protocol. It introduces a new `AgentApiKey` entity with hashed storage, a Control Center internal API for key validation and permission resolution, a Communication Hub middleware that detects API keys (Bearer token or query parameter) and routes them for validation, a `load_skills` system tool with `updated_at` version tracking, and a frontend management page for platform administrators to create, view, and revoke API keys.

## Task Checklist

### Phase 1 — Database & Model Foundation
- [x] 1.1 — Create `AgentApiKey` and `ApiKeyUsageLog` SQLAlchemy models
- [x] 1.2 — Generate and verify Alembic migration for new tables
- [x] 1.3 — Create Pydantic schemas for API key CRUD and validation
- [x] 1.4 — Backfill `skills.updated_at` for existing skills (one-time data migration)

### Phase 2 — Control Center Internal API (CH-facing)
- [x] 2.1 — Implement internal API key validation endpoint (`POST /api/v1/internal/auth/validate-api-key`)
- [x] 2.2 — Extend permission resolution service to accept API key as entry point
- [x] 2.3 — Implement internal skill resolution with `since` parameter (`POST /api/v1/internal/skills/resolve`)

### Phase 3 — Control Center Admin API (Frontend-facing)
- [x] 3.1 — Implement API key CRUD endpoints (list, create, revoke)
- [x] 3.2 — Integrate audit logging for API key create, revoke, and usage events

### Phase 4 — Communication Hub Middleware & System Tool
- [x] 4.1 — Implement API key auth detection middleware on Communication Hub
- [x] 4.2 — Implement `load_skills` system tool entry on Communication Hub

### Phase 5 — Frontend API Key Management
- [x] 5.1 — Create TypeScript types and API client for API key endpoints
- [x] 5.2 — Build API Key list page with status filtering and search
- [x] 5.3 — Build Create API Key dialog with one-time key reveal
- [x] 5.4 — Build Revoke API Key confirmation dialog
- [x] 5.5 — Add navigation entry and i18n translations

### Phase 6 — Testing & Verification
- [x] 6.1 — Write backend unit tests for API key service, models, and endpoints
- [x] 6.2 — Write frontend unit tests for API key page components
- [x] 6.3 — Run full test suite and verify no regressions

---

## Phase 1 — Database & Model Foundation

### Task 1.1 — Create `AgentApiKey` and `ApiKeyUsageLog` SQLAlchemy models

Create a new file `backend/app/db/models/agent_api_key.py` containing two SQLAlchemy declarative models:

- **`AgentApiKey`**: columns for `id`, `name`, `key_hash` (SHA-256 string), `key_prefix` (readable prefix like `phn_sk_`), `agent_identity_id` (FK to `agent_identities`), `agent_role_id` (FK to `agent_roles`), `status` (Enum: `active`/`revoked`), `created_at`, `last_used_at`, `created_by` (FK to `identities`). Include unique constraint on `(agent_identity_id, agent_role_id)` where `status = active`.
- **`ApiKeyUsageLog`**: columns for `id`, `api_key_id` (FK to `agent_api_keys`), `action` (Enum: `validate`/`load_skills`/`tool_call`), `tool_name` (nullable), `ip_address`, `timestamp`, `success` (boolean).

Register both models in `backend/app/db/models/__init__.py` so they are discoverable by Alembic auto-generation and the ORM.

**Done when**: Both model files are syntactically valid Python; models are importable from `backend.app.db.models`; `python -c "from app.db.models import AgentApiKey, ApiKeyUsageLog"` succeeds.

---

### Task 1.2 — Generate and verify Alembic migration for new tables

Generate an auto-migration for the new `agent_api_keys` and `api_key_usage_logs` tables:

1. Run `python -m alembic revision --autogenerate -m "add_api_key_tables"` in `backend/`
2. Review the generated migration for correctness: SQLAlchemy enums must use `postgresql.ENUM(..., create_type=False)`, no parameterized DDL statements
3. Apply the migration: `python -m alembic upgrade head`
4. Verify: `python -m alembic current` shows the new revision ID

**Done when**: Migration file exists in `backend/alembic/versions/`; `alembic current` shows the latest head; database has both new tables with correct columns and constraints.

---

### Task 1.3 — Create Pydantic schemas for API key CRUD and validation

Create `backend/app/schemas/api_key.py` with Pydantic v2 models:

- **`ApiKeyCreate`**: `name` (str, max 128), `agent_identity_id` (UUID), `agent_role_id` (UUID)
- **`ApiKeyCreateResponse`**: `id` (UUID), `name`, `key_prefix`, `api_key` (clear-text, returned once), `agent_identity_name`, `agent_role_name`, `created_at`
- **`ApiKeyRead`**: `id`, `name`, `key_prefix`, `agent_identity_id`, `agent_identity_name`, `agent_role_id`, `agent_role_name`, `status`, `created_at`, `last_used_at`
- **`ApiKeyValidateRequest`**: `key_hash` (str), `since` (optional datetime for incremental skill sync)
- **`ApiKeyValidateResponse`**: `agent_identity_id`, `agent_role_id`, `identity_token` (str), `permissions` (list of allowed tools/skills/SOPs)
- **`SkillWithVersion`**: extends existing skill schema with `updated_at` (datetime), `tools` (list of tool definitions with input/output schemas)

**Done when**: All Pydantic models import cleanly; `python -c "from app.schemas.api_key import ApiKeyCreate, ApiKeyCreateResponse"` succeeds.

---

### Task 1.4 — Backfill `skills.updated_at` for existing skills

Existing skills may have `updated_at` set automatically by the ORM, but to ensure consistency for the `since` parameter in `load_skills`, run a one-time data migration script:

1. Create a standalone migration script (`backend/alembic/versions/backfill_skills_updated_at.py`) that sets `updated_at = created_at` for any skill row where `updated_at IS NULL` or `updated_at` differs from `created_at` in an anomalous way
2. Apply the migration
3. Verify: `SELECT count(*) FROM skills WHERE updated_at IS NULL` returns 0

**Done when**: Migration applied; all skill rows have a non-null `updated_at` column matching their actual last modification time.

---

## Phase 2 — Control Center Internal API (CH-facing)

### Task 2.1 — Implement internal API key validation endpoint

Create `backend/app/api/v1/internal/validate_api_key.py` with an mTLS-protected endpoint:

- **`POST /api/v1/internal/auth/validate-api-key`**: Accepts `ApiKeyValidateRequest` (hashed key + optional `since`). Looks up the hash in `agent_api_keys`, checks status is `active`, resolves the bound `agent_identity_id` → identity token (decrypted from encrypted storage) and `agent_role_id` → permission set. Logs an `ApiKeyUsageLog` entry (action: `validate`). Updates `last_used_at` on the key record. Returns `ApiKeyValidateResponse`.

Service logic (key hashing, lookup, token resolution) should live in `backend/app/services/api_key_service.py`.

Register the router in `backend/app/api/v1/internal/__init__.py`. Protect with `require_service_certificate` dependency (same pattern as existing internal endpoints).

**Done when**: Endpoint is registered; route responds with 401 for invalid/revoked keys; returns identity token + permissions for valid active keys; only accessible with a valid service certificate.

---

### Task 2.2 — Extend permission resolution service to accept API key as entry point

Modify the existing permission resolution path (in `backend/app/services/permission_resolution.py`) to support resolution starting from an API key:

1. **`resolve_permissions_from_api_key(api_key_record, db)`** — Takes an `AgentApiKey` record, uses its `agent_role_id` to resolve the complete permission set (tools, skills, SOPs). Same logic as the existing identity-based resolution.
2. Ensure the permission set returned is identical to what an internal agent with the same role would receive.

No changes to the permission engine itself — only a new entry-point function that delegates to existing logic.

**Done when**: Function exists; calling it with an active key's record returns the same permission set as resolving directly from the key's bound role; unit test confirms parity.

---

### Task 2.3 — Implement internal skill resolution with `since` parameter

Extend or create an internal endpoint for skill resolution that supports the `since` parameter:

- **`POST /api/v1/internal/skills/resolve`**: Accepts `agent_role_id` and optional `since` (datetime). Queries skills accessible to the role via `agent_role_skills` join table. For each skill, includes full tool definitions (name, description, input schema, output schema), the skill's `updated_at` timestamp, and the canonical tool name. If `since` is provided, excludes skills where `updated_at <= since`. Returns list of `SkillWithVersion`.

Reuse existing skill/tool query logic from `backend/app/api/v1/skills.py` and `backend/app/db/models/mcp_hub.py`.

**Done when**: Endpoint is registered; returns full skill definitions with `updated_at` timestamps; when `since` is provided, only skills with `updated_at > since` are returned; accessible only with service certificate.

---

## Phase 3 — Control Center Admin API (Frontend-facing)

### Task 3.1 — Implement API key CRUD endpoints

Create `backend/app/api/v1/api_keys.py` with JWT-protected endpoints for platform administrators:

- **`GET /api/v1/api-keys`**: List all API keys with optional status filter (`?status=active|revoked`). Returns list of `ApiKeyRead`. Includes search by name/identity name.
- **`POST /api/v1/api-keys`**: Create a new API key. Validates that `agent_identity_id` references an existing agent identity and `agent_role_id` is an allowed role for that identity. Generates a cryptographically random key string (prefix `phn_sk_` + 32 random alphanumeric chars), SHA-256 hashes it, stores hash + prefix. Returns `ApiKeyCreateResponse` with the clear-text key shown once. Enforces one-active-key-per-identity-role-pair constraint.
- **`POST /api/v1/api-keys/{key_id}/revoke`**: Sets key status to `revoked`. Idempotent — revoking an already-revoked key is a no-op success.
- **`GET /api/v1/api-keys/identities-with-roles`**: Returns agent identities with their available roles for the create-key dropdown population.

Use `require_permission` dependency with appropriate resource type. Key generation logic (random string, hashing) in `backend/app/services/api_key_service.py`.

**Done when**: All four endpoints respond correctly; create enforces uniqueness; revoke is idempotent; list supports status filter; endpoints require JWT auth.

---

### Task 3.2 — Integrate audit logging for API key events

Extend the existing audit logging service to record:

- **API key created**: log key ID, bound identity, bound role, admin who created it
- **API key revoked**: log key ID, admin who revoked it
- **API key validation** (already handled via `ApiKeyUsageLog` in Task 2.1)
- **API key validation failure**: log the hash prefix (not the full key), failure reason

Use existing audit patterns in the codebase. The `ApiKeyUsageLog` table handles runtime usage auditing; the existing audit log (if any) handles admin CRUD events.

**Done when**: Create and revoke operations produce audit log entries; failed auth attempts are logged with key prefix and IP address.

---

## Phase 4 — Communication Hub Middleware & System Tool

### Task 4.1 — Implement API key auth detection middleware on Communication Hub

Add or extend middleware on the Communication Hub (in `backend/app/services/gateway/` or a new middleware module) to detect API key authentication on incoming MCP requests:

1. **Detection**: Check `Authorization: Bearer <value>` header and `?apiKey=<value>` query parameter (query param checked only if no Bearer header present). Extract the key value.
2. **Hashing**: SHA-256 hash the extracted key before sending to Control Center (never send raw key over the wire, even on mTLS).
3. **Validation call**: Call `POST /api/v1/internal/auth/validate-api-key` on Control Center via mTLS service certificate. Cache the response (identity token + permissions) for the request lifetime.
4. **Request enrichment**: Store resolved identity token and permission set on the request context/state for downstream handlers. Identity token is held exclusively by CH — never returned to the external agent.
5. **Error handling**: For invalid/revoked keys, return a clear 401 with error detail. Log failed attempts.

The middleware must coexist with existing mTLS certificate auth — detect which auth method is in use and route accordingly. Certificate-based auth path is unchanged.

**Done when**: External agent can connect with `Authorization: Bearer <valid_key>` and receive a successful MCP handshake; revoked key returns 401; certificate-based internal agent connections continue to work; identity token is confirmed absent from all external-facing responses.

---

### Task 4.2 — Implement `load_skills` system tool entry on Communication Hub

Add a system tool entry point on the Communication Hub that external agents can invoke via MCP protocol:

1. **`load_skills` tool registration**: Register as a system tool in the CH tool registry. Accepts optional `since` parameter (ISO 8601 datetime string).
2. **Resolution call**: CH calls `POST /api/v1/internal/skills/resolve` on Control Center with the agent's resolved `agent_role_id` and the `since` parameter. Communication is mTLS-secured.
3. **Response formatting**: Transforms the Control Center response into MCP-compliant tool definitions. Each skill includes: name, description, `inputSchema`, `outputSchema`, the canonical tool name for invocation, and the `updated_at` timestamp.
4. **Incremental sync**: When `since` is provided and no skills have changed, returns an empty list (not an error).
5. **SOPs as skills**: SOPs are included in the response as skill definitions (they are higher-order skills composed of multiple tool calls).

**Done when**: External agent can call `load_skills` and receive all accessible skills with full schemas and `updated_at`; calling with `since` returns only skills updated after that timestamp; calling `since` with a future date returns empty list; skill definitions include SOPs.

---

## Phase 5 — Frontend API Key Management

### Task 5.1 — Create TypeScript types and API client for API key endpoints

Create:

- **`frontend/src/types/apiKeys.ts`**: TypeScript interfaces/enums for `ApiKey`, `ApiKeyCreateRequest`, `ApiKeyCreateResponse`, `ApiKeyStatus`, `IdentityWithRoles`. Strongly typed — no `any`.
- **`frontend/src/api/apiKeysApi.ts`**: API client functions: `fetchApiKeys(status?)`, `createApiKey(request)`, `revokeApiKey(keyId)`, `fetchIdentitiesWithRoles()`. Uses the existing `apiClient` from `frontend/src/api/apiClient.ts` for HTTP calls. Handle errors per project convention.
- **`frontend/src/hooks/useApiKeys.ts`**: React hook wrapping the API client with loading/error/data state. Includes `refresh()` function for list refresh after create/revoke.

**Done when**: All TypeScript files compile without errors; types accurately reflect the Pydantic schemas from Task 1.3.

---

### Task 5.2 — Build API Key list page with status filtering and search

Create `frontend/src/pages/api-keys/ApiKeyListPage.tsx`:

- **Layout**: Full-page with header ("API Key Management"), description, and "Create API Key" primary button
- **Change banner**: Informational banner explaining API keys are for external agent MCP Hub access (matches prototype lines 323-329)
- **Filter bar**: Dropdown for status filter (All / Active / Revoked) and text search input filtering by name, identity name, or role name (matches prototype lines 332-343)
- **Key table**: Columns: Name, Agent Identity, Agent Role, Status (green chip "Active" / red chip "Revoked"), Key Hint (monospace partial prefix), Created (relative time), Last Used (relative time or "Never"), Actions
- **Empty state**: When no keys exist, show empty state with "Create API Key" CTA (matches prototype lines 367-373)
- **Loading state**: Skeleton or spinner while fetching
- **Error state**: Error alert with retry button using `PermissionDeniedAlert` pattern
- **Actions column**: Active keys show "Revoke" (red) + "Delete" button; Revoked keys show "Delete" button only (matches prototype lines 1056-1063)

All UI text must use the `t()` function from i18next.

**Done when**: Page renders all mock/stub data correctly when API is unavailable, matches prototype layout, filtering and search work, empty and loading states display correctly.

---

### Task 5.3 — Build Create API Key dialog with one-time key reveal

Create `frontend/src/pages/api-keys/CreateApiKeyDialog.tsx`:

- **Two-step dialog**: Step 1 (form) → Step 2 (key reveal success)
- **Step 1 — Form**:
  - "Key Name" text input (required, max 128 chars) with placeholder
  - "Agent Identity" dropdown (populated from `fetchIdentitiesWithRoles()`)
  - "Agent Role" dropdown (filtered by selected identity's available roles; disabled until identity selected)
  - Info alert: "Key Scoping — inherits full permission set of selected role"
  - Footer: Cancel + "Create Key" button (disabled until form valid)
- **Step 2 — Success**:
  - Success icon + "API Key Created Successfully" heading
  - Warning banner: "Save this key now — it will not be shown again"
  - Key display: dark background, monospace font, masked by default with "Reveal Key" toggle
  - Copy button with "Copied!" feedback (2-second timeout)
  - Key format hint: `phn_sk_` + 32 random chars
  - Summary: bound identity, bound role, key hint
  - Footer: "Done — I have saved this key" button
- **Error handling**: Follow the Dialog Error Handling Standard from `docs/config.yaml` — use `dialogError` state, wrap async in try-catch, clear error on close, display `PermissionDeniedAlert` at top of dialog content
- **Form validation**: Client-side validation before submit — name required, identity required, role required. Show inline error messages per field.

**Done when**: Dialog opens/closes with proper state reset; form validation works; successful creation transitions to step 2; key is masked by default with reveal/copy functionality; error state displays correctly; dialog matches prototype lines 380-486.

---

### Task 5.4 — Build Revoke API Key confirmation dialog

Create `frontend/src/pages/api-keys/RevokeApiKeyDialog.tsx`:

- **Warning icon + heading**: "Revoke API Key"
- **Body**: Warning alert with key name, explanation that agents using this key will immediately lose access, and that the action cannot be undone
- **Footer**: Cancel button + "Revoke Key" danger button
- **On success**: Close dialog, refresh key list, toast notification
- **Error handling**: Follow Dialog Error Handling Standard

**Done when**: Dialog matches prototype lines 490-518; revoke action calls API and refreshes list; toast notification appears on success.

---

### Task 5.5 — Add navigation entry and i18n translations

- **Navigation**: Add "API Keys" sub-item under the "Integrations" sidebar section in the app's navigation configuration. Use the existing route/navigation pattern (likely in a router config or sidebar component). Route path: `/api-keys`
- **i18n**: Add English translation keys in `frontend/src/i18n/` for all user-facing strings: page title, column headers, button labels, dialog titles, status labels, validation messages, toast messages, empty state text, change banner text. Follow existing i18n key naming conventions.

**Done when**: "API Keys" appears in sidebar under Integrations; clicking navigates to the API Keys page; all visible text uses `t()` function with valid translation keys; `npm run build` (or `npx tsc --noEmit`) succeeds with no missing key warnings.

---

## Phase 6 — Testing & Verification

### Task 6.1 — Write backend unit tests for API key service, models, and endpoints

Create tests in `backend/tests/`:

- **`test_api_key_service.py`**: Unit tests for key generation (randomness, format `phn_sk_*`), SHA-256 hashing, hash lookup, uniqueness constraint enforcement, status transition (active → revoked), `last_used_at` update, `ApiKeyUsageLog` creation
- **`test_api_key_internal_api.py`**: Test internal validation endpoint: valid key returns identity token + permissions; revoked key returns 401; invalid hash returns 401; endpoint requires service certificate; `since` parameter is passed through correctly
- **`test_api_key_admin_api.py`**: Test admin CRUD endpoints: list with/without status filter; create with valid identity+role; create with invalid identity (404); create with duplicate active identity-role pair (409); revoke active key (success); revoke already-revoked key (success, idempotent)
- **`test_permission_resolution_api_key.py`**: Test that permissions resolved from an API key match permissions resolved from the same role directly

Use pytest with async test fixtures. Mock the service certificate dependency where needed. Use the existing test database and fixture patterns.

**Done when**: All new tests pass; test coverage includes happy path, error cases, and edge cases (duplicate, revoked, invalid).

---

### Task 6.2 — Write frontend unit tests for API key page components

Create tests in `frontend/src/__tests__/`:

- **`api-keys/ApiKeyListPage.test.tsx`**: Render list page; test status filter changes; test search input filters; test empty state renders when no keys; test loading state; test error state with retry; test revoke and delete button visibility based on key status
- **`api-keys/CreateApiKeyDialog.test.tsx`**: Open dialog; test form validation (required fields); test role dropdown enables after identity selection; test create button disabled until valid; test step 2 appears after successful creation; test "Reveal Key" toggle; test "Copy" button; test dialog reset on close
- **`api-keys/RevokeApiKeyDialog.test.tsx`**: Open dialog; test key name displayed; test cancel closes; test confirm calls revoke API; test list refreshes after revoke
- **`hooks/useApiKeys.test.ts`**: Test data fetching, loading state, error state, refresh function

Use Vitest + React Testing Library. Mock API calls with `vi.mock()`. Follow existing test patterns in the project.

**Done when**: All tests pass with `npx vitest run`; tests cover rendering, user interactions, API call mocking, and state transitions.

---

### Task 6.3 — Run full test suite and verify no regressions

1. Run backend tests: `cd backend && python -m pytest tests/ -v`
2. Run frontend tests: `cd frontend && npx vitest run`
3. Run any existing e2e tests
4. Verify all existing tests still pass — zero regressions
5. Start the full stack and manually verify: create an API key in the UI; confirm the key appears in the list; revoke it and confirm status changes; verify existing agent management, role management, skills, and MCP server pages are unaffected

**Done when**: All existing tests pass; all new tests pass; manual smoke test confirms API key CRUD works end-to-end; no regressions in existing functionality.

---

## Completion Checklist

- [x] All 13 tasks in the Task Checklist are marked `[x]`
- [x] `python -m alembic current` shows migrations applied up to head
- [x] All new backend models importable from `app.db.models`
- [x] Internal validation endpoint returns correct responses for valid, revoked, and invalid keys
- [x] `load_skills` returns full skill definitions with `updated_at` timestamps
- [x] `since` parameter filters skills correctly in `load_skills`
- [x] Communication Hub middleware detects API keys via both Bearer token and query parameter
- [x] Certificate-based internal agent auth path still works
- [x] External agents never receive identity tokens in any response
- [x] Frontend API Key list page renders with filtering and search
- [x] Create dialog shows key once, hides on close, and key text is not in any network response after creation
- [x] Revoke dialog confirms and immediately invalidates key
- [x] All i18n translation keys are present and used (no hardcoded strings)
- [x] All unit tests pass (backend + frontend)
- [x] Zero regressions in existing test suites
