# Testing Strategy: Parthenon Enterprise AI Harness

## Test Pyramid
- **Unit Tests**: Backend service logic, permission enforcement, skill composition (pytest). Frontend component rendering and state management (vitest).
- **Integration Tests**: REST API endpoints, MCP proxy round-trips, OIDC token flow. Database schema migration verification against real PostgreSQL.
- **End-to-End (E2E) Tests**: Full user journeys via Playwright browser automation covering all major UI flows.
- **Security Tests**: Auth boundary enforcement, permission isolation, credential leak prevention, max-instance enforcement, caller-scoped internal allowlists, and deny-by-default verification with audit evidence.
- **Performance Tests**: Agent instance throughput, MCP tool call round-trip latency, Communication Hub message throughput under concurrent sessions.

## Test Layers
- **Backend (pytest)**: API endpoints, service logic, data model operations. Location: `backend/tests/`
- **Frontend (vitest)**: React component rendering, state, and user interaction. Location: `frontend/src/__tests__/`
- **E2E (Playwright)**: User journeys, cross-module flows, UI+backend integration. Location: `e2e/tests/`

## Database Migration Testing Requirements

Changes that include database schema changes (`has_db_changes: true`) require additional verification:

**Pre-test checklist (must be confirmed before running any tests):**
1. Alembic migration generated and committed
2. `alembic upgrade head` applied locally — verify with `alembic current`
3. Test database fixture applies migrations via `alembic upgrade head` in setup

**Backend integration tests must:**
- Run against a real PostgreSQL database (not in-memory mocks)
- Verify schema changes took effect by querying `information_schema.columns`
- Include negative tests for constraint violations (e.g., rejected legacy enum values)
- Test nullable column acceptance and non-nullable constraint enforcement

**E2E tests for database changes must include:**
- At least one `test.describe('Real Backend Integration - ...')` block per domain area that hits the running backend without `page.route()` mocking
- This catches migration issues that purely mocked tests cannot detect

## Frontend Component Test Infrastructure

Some complex components using React Query + MSW in the Vitest environment require workaround test files (`*.simple.test.tsx`, `*.minimal.test.tsx`). These cover core rendering assertions. Full CRUD coverage for affected components is provided by E2E tests. This is an infrastructure limitation, not an implementation defect.

## Content-Type-Aware Rendering Testing

Changes that introduce content-type detection, HTML rendering, or content sanitization require:

**Pre-test checklist:**
1. DOMPurify is listed as an explicit dependency in `package.json`
2. `ContentRenderer` component implements a defensive null-check on DOMPurify before use
3. `dangerouslySetInnerHTML` is ONLY used with DOMPurify-sanitized output, never with raw/untrusted content
4. The detection regex (`containsHtmlTags`) requires `<` immediately followed by an ASCII letter — comparison operators (`< 5`, `> 10`) must not trigger false positives

**Frontend component tests must:**
- Cover all mode × content-type combinations (auto/chat × html/markdown/plain/null)
- Validate XSS sanitization: script tags, event handler attributes, and other XSS vectors stripped by DOMPurify
- Verify comparison operators are NOT misidentified as HTML tags
- Test the maximize/restore flow end-to-end: open dialog, verify content identity, close via all mechanisms (Escape, close button, backdrop)
- Ensure keyboard accessibility throughout the maximize flow (Tab navigation, focus trapping)
- Confirm regression: existing markdown, plain-text, and typed output rendering unchanged

**Security assertions:**
- At least one test must assert that `<script>` tags are stripped from rendered HTML output
- At least one test must assert that event handler attributes (`onclick`, `onerror`, etc.) are stripped
- At least one test must assert that `<` followed by a space or digit is NOT detected as HTML

Refer to `agent-response-rendering-test-plan.md` for module-specific coverage and test file references.

## Critical Quality Gates
- 100% pass rate required for all test layers before release
- All PRD acceptance criteria must be mapped to at least one test scenario
- Edge cases and failure modes must be covered in test plans
- For changes with DB schema changes: at least one real-backend E2E test must pass before deployment

## Certificate-Based Authentication Testing

Changes involving certificate issuance, validation, or revocation require:

**Pre-test checklist:**
1. Alembic migration applied: `alembic upgrade head`; confirm tables `agent_instance_certificate`, `certificate_revocation_entry`, `certificate_validation_log`, `token_refresh_log` exist
2. CA initialized on Control Center startup (root CA cert present)
3. Test fixtures seed certificates via `CertificateAuthorityService`; do not use self-signed certs outside the CA chain

**Backend integration tests must:**
- Issue certificates via the CA service (not handcrafted PEM strings) to test real signature verification
- Cover all certificate states: valid, expired, revoked, unknown serial
- Verify `certificate_validation_log` entries after each validation
- Verify `token_refresh_log` entries after each refresh attempt
- Assert metadata endpoint response schema excludes identity token fields

**Security assertion (zero-trust):**
- At least one test must assert that `GET /agent/metadata` response does NOT contain `identity_token`, `access_token`, or `refresh_token` keys — this is a critical security invariant
- Failing this assertion is a blocking defect; deployment must be halted until resolved

## Test File Locations
- Backend: `backend/tests/`
- Frontend: `frontend/src/__tests__/`
- E2E: `e2e/tests/`
- MCP Demo App (standalone): `mcp-demo-app/tests/` — unit and integration tests for the demo MCP server; uses its own pytest configuration with mocked Keycloak identities

## Agent Data Types & Typed Outputs Testing

Changes involving the Agent Data Type registry, typed output persistence, schema validation, or the `query_result` system tool require:

**Pre-test checklist:**
1. Applied migrations verified: `agent_data_types` table, `agent_outputs` table with FKs, `AgentOutputValidationStatus` enum, `agent_types.output_data_type_id` column, `agent_jobs.output_id` column all exist
2. All 5 field types (string, number, boolean, date, enum) have corresponding validators in `SchemaValidationService`
3. `save_result` path handles both typed (calls validation + `OutputService.save_typed`) and untyped (legacy `ResultRecord`) branches

**Backend integration tests must:**
- Cover full CRUD lifecycle for data types: create, read, update, delete, duplicate detection, delete guard
- Validate all 5 field types individually and in combination
- Test the two-phase output persistence: validate then persist, with correct handling of both valid and invalid outputs
- Verify `query_result` system tool routing through Communication Hub to Control Center
- Confirm backward compatibility: existing untyped agent execution paths unchanged

**Frontend component tests must:**
- Verify `TypedOutputRenderer` handles all 5 field types with type-aware formatting
- Verify `OutputTypeResultTab` detects typed vs untyped outputs and renders accordingly
- Test `DataTypeFormDialog` field editor: add, remove, configure fields; validation errors

**E2E tests must cover:**
- Full CRUD lifecycle on Data Types page with mocked API
- Agent Outputs Query page: filter bar, dynamic columns, CSV export, detail drawer
- Typed execution flow: agent management badge, detail dialog data type name, execution log typed rendering

Refer to individual test plans for module-specific coverage and test file references.

## Dual-Identity Tool Security Testing

The MCP Demo App (`mcp-demo-app`) demonstrates per-tool dual-identity role gating:
- **Agent identity** (via `Authorization: Bearer` header) — validated against the agent Keycloak realm
- **User identity** (via `X-User-Identity` header) — validated against a separate user Keycloak realm or same realm (fallback)

Security assertions for dual-identity features:
- **Cross-realm rejection**: User JWT signed by agent realm's key must be rejected (and vice versa)
- **Identity isolation**: helloAgent tool must ignore user identity headers; helloUser must ignore agent identity headers — no cross-contamination between identity chains
- **Access-denied as success**: Tool access-denied responses must return HTTP 200 with `access_denied: true` in the JSON-RPC body, never HTTP 403/401 — prevents information leakage through HTTP status codes
- **No unnecessary validation**: User-only tools must not validate agent JWTs (and vice versa) — a missing agent JWT must not block a user-tool call when user JWT is present
- **Single-realm fallback**: When user realm is unconfigured, app must validate user JWT against agent realm and still enforce role gating

## API Key Authentication Testing

Changes involving API key management, external agent authentication, or the Communication Hub auth middleware require:

**Pre-test checklist:**
1. Alembic migration applied: confirm `api_keys` and `api_key_usage_logs` tables exist; `skills.updated_at` backfill has no NULL values; `status` enum contains `active` and `revoked`
2. API key endpoints map to resource types registered in both `backend/app/core/resource_types.py` and `frontend/src/constants/resourceTypes.ts`
3. Test data uses identifiable prefixes to ensure cleanup after test runs

**Backend integration tests must:**
- Cover full CRUD lifecycle: create (one-time clear-text return), read (list with status filter), update (revoke), delete (not supported; keys are revoked, not deleted)
- Verify key hash stored as SHA-256, never plaintext
- Verify unique constraint: one active key per identity-role pair (409 on duplicate)
- Validate the internal `/internal/auth/validate-api-key` endpoint rejects all callers except Communication Hub (mTLS service certificate enforcement)
- Cover all key states: active, revoked; verify revoked keys are immediately unusable
- Verify `ApiKeyUsageLog` entries for validate, load_skills, and tool_call actions
- Verify `load_skills` returns `updated_at` on every skill; `since` parameter correctly filters

**Security invariances:**
- External agents MUST NEVER receive the identity token in any response — at least one test must assert the absence of `identity_token`, `access_token`, and `refresh_token` in external-facing API responses
- Key value MUST NEVER appear in any log, audit entry, or API response outside the one-time creation display
- Failed authentication attempts must be logged with `success=false` for security monitoring
- Rate limiting must be enforced on the auth endpoint to prevent brute-force attacks

**Frontend component tests must:**
- Verify clear-text key displayed once at creation with copy mechanism; never retrievable after dialog close
- Verify dialog error handling follows the Dialog Error Handling Standard: `dialogError` state, try-catch wrapping, error clearance on open/close
- Verify list auto-refreshes after create and revoke without manual page reload
- Verify status filter dropdown contains all/active/revoked options and applies correct filtering
- Verify revoked items show "revoked" status chip; no re-activation possible

**E2E tests must cover:**
- Full admin workflow: key list rendering → create dialog (identity + role selection, name input, form validation) → one-time key display → revoke dialog (confirmation with key name/identity/role) → status filter interaction
- Real-backend integration tests: endpoint auth checks verify GET/POST require authentication; health endpoint confirms schema migration applied
- No regression: all existing agent management, role management, MCP hub pages continue to render correctly

Refer to `api-key-mcp-hub-test-plan.md` for module-specific coverage and test file references.

## Service Segregation Security Requirements

Changes that touch internal service boundaries must include:
- Backend integration assertions for allowlist partitioning by caller type (`agent_runtime` vs `communication_hub`)
- Deny-by-default validation for non-allowlisted internal endpoints before handler execution
- Fail-closed behavior checks when certificate revocation status cannot be validated
- Structured deny-event validation including caller type, endpoint, method, reason, and timestamp
- At least one real-backend E2E suite validating internal endpoint wiring and browser API/WS-only boundaries

## Dashboard Operational Metrics Testing

Changes involving the dashboard operational metrics (stat cards, time-sensitive metrics, permission-aware cards) require:

**Pre-test checklist:**
1. Dashboard route (`/`) has NO `require_permission()` decorator — any authenticated user receives 200
2. All ten metric cards map to correct module-action pairs from `ResourceTypeManifest`
3. Human Interventions card uses `view` action (not `read`) per manifest

**Backend tests must:**
- Verify `DashboardMetricsService.aggregate_metrics()` returns correct counts vs. direct `SELECT COUNT(*)` queries
- Cover all four result states per domain: normal (count returned), permission-denied (flag=true, count=0), empty (count=0, flag=false), and individual query failure (count=0, other domains unaffected)
- Verify single domain query failure does not crash entire endpoint — remaining domains continue to aggregate
- Test date range boundary inclusivity (records at window edges included)
- Verify snapshot counts ignore date range changes — only `time_sensitive` counts affected

**Frontend tests must:**
- Verify all four visual states per card: normal, zero ("0" displayed), loading (skeleton), permission-denied (dashed border, lock icon, reduced opacity)
- Verify `DateRangePicker` presets trigger re-fetch but only for time-sensitive cards (snapshot cards remain static)
- Verify `permission_flags` boolean interpretation is correct (`true` = denied, NOT `true` = allowed)
- Verify IdP status section retained below operational metrics with all three cards

**E2E tests must cover:**
- Full dashboard load with all cards, date range switching, and IdP status section
- At least one real-backend test (no mocks) validating JSON response shape and real counts
- Permission-denied scenarios with mocked `permission_flags`

Refer to `dashboard-test-plan.md` for module-specific coverage and test file references.

## Namespaced Resource Types & Migration Testing

Changes involving the `::`-delimited resource type system, policy authoring with namespaced identifiers, or the Alembic data migration require:

**Pre-test checklist:**
1. All 17 namespaced identifiers registered in both `backend/app/core/resource_types.py` and `frontend/src/constants/resourceTypes.ts`
2. Alembic migration generated and reviewed for correct mapping of 15 legacy values to 17 namespaced values
3. All `require_permission()` call sites updated to use new `RT_*` constants

**Backend tests must:**
- Verify manifest contains exactly 17 entries across 3 modules (`agent`: 12, `integration`: 2, `system`: 3)
- Test `::` delimiter parsing: correct splitting, flat-value rejection, three-layer rejection, empty-value rejection
- Test wildcard expansion: `agent::*` → 12 concrete submodules, `*::*` → all 17
- Verify permission engine `_match_module()` uses manifest-aware expansion (not string prefix matching)
- Test batch save endpoint (`PUT /api/v1/user-roles/{id}/policies/batch`) for atomicity: single invalid policy rejects entire batch

**Migration tests must:**
- Verify `information_schema` confirms column types unchanged (`varchar(100)`)
- Verify no legacy flat values remain in `policy_statements.module` or `policy_resources.resource_type`
- Test consolidation groups (5→`system::permissions`, 2→`agent::trails`) with pre-seeded data — verify no data loss, no duplicates
- Test alembic downgrade restores flat values for the 15 legacy types

**Frontend tests must:**
- Verify `AddStatementDialog` dropdown groups options by module (Agents, Integrations, System)
- Verify `freeSolo` autocomplete accepts wildcards and predefined manifest values
- Verify `RolePolicyDialog` Form↔JSON view toggle preserves all changes bidirectionally (round-trip fidelity)
- Verify unsaved changes guard: Cancel/Escape/backdrop click → confirmation dialog when changes exist

Refer to `namespace-resource-types-test-plan.md` for module-specific coverage and test file references.

## OIDC Integration & Auth Pipeline Testing

Changes involving the three-tier auth pipeline (super admin → OIDC user → OIDC agent → public), database-backed identity provider configuration, or the super admin credential bootstrap require:

**Pre-test checklist:**
1. `super_admin_credentials` table exists; `identity_provider_configs` has `provider_scope`, `issuer_url`, `encrypted_client_secret` columns; removed columns (`realm_name`, `audience`, setup tracking fields) are absent
2. `provider_scope` enum has unique constraint (only one config per scope)
3. Alembic migration applied; `alembic current` shows latest revision

**Backend tests must:**
- Verify super admin credential validation uses bcrypt with timing-safe comparison
- Verify super admin `is_enabled` flag is checked at validation time (not just issue time) — disabled super admin tokens rejected even if still within expiry
- Verify guard rail: cannot disable super admin if no enabled OIDC provider exists
- Verify three-tier pipeline branches: super admin path, OIDC user path, OIDC agent path, public path, mixed states
- Verify client secret encryption at rest (DB stores ciphertext, not plaintext)
- Verify provider registry hot-reloads from DB on config change without service restart
- Verify identity.yaml → DB migration: field mapping correct, idempotent, database takes precedence after migration

**Frontend tests must:**
- Verify login page three-state rendering: super admin only (form), OIDC only (button), both (button + toggle)
- Verify identity provider config form: separate user/agent entries, field validation, enable toggle
- Verify test connection and test login modals without affecting active provider state

**Security invariants:**
- At least one test must assert that super admin credentials are never hardcoded in source code
- At least one test must assert that client secret is never returned in plaintext from any API response
- At least one test must assert that agent tokens are NOT validated against user provider (and vice versa)

Refer to `refine-oidc-integration-test-plan.md` for module-specific coverage and test file references.

## Production-Ready Configuration Testing

Changes involving startup dependency validation, environment-variable-based configuration resolution, or the consolidated setup tool require:

**Pre-test checklist:**
1. Control Center starts without Keycloak admin credentials (`KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` absent from environment)
2. All three backend services (CC, AR, CH) validate dependencies at startup and fail-fast with clear errors
3. Setup tool supports `--output json` for machine-parseable verification

**Backend tests must:**
- Verify Control Center `Settings` class does not load Keycloak admin credentials at runtime
- Verify `_initialize_agent_realm()` is NOT called during CC startup (only setup tool calls it)
- Verify PostgreSQL, OIDC, and Redis validation at startup: reachable → pass; unreachable → logged error + non-zero exit
- Verify Agent Runtime and Communication Hub validate Control Center reachability before certificate bootstrap
- Verify retry logic: transient failures within retry windows do not cause startup failure
- Verify configuration source logging: every connection logs source (env, yaml, or default); credentials redacted

**Setup tool tests must:**
- Verify all sub-commands (`identity`, `database`, `certificates`, `dev`, `verify`) are idempotent (run twice → "skipped" for all)
- Verify structured output: `created` / `skipped` / `error` indicators
- Verify credentials never appear in log output, error messages, or JSON output

Refer to `production-ready-configuration-test-plan.md` for module-specific coverage and test file references.
