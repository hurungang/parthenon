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

## Service Segregation Security Requirements

Changes that touch internal service boundaries must include:
- Backend integration assertions for allowlist partitioning by caller type (`agent_runtime` vs `communication_hub`)
- Deny-by-default validation for non-allowlisted internal endpoints before handler execution
- Fail-closed behavior checks when certificate revocation status cannot be validated
- Structured deny-event validation including caller type, endpoint, method, reason, and timestamp
- At least one real-backend E2E suite validating internal endpoint wiring and browser API/WS-only boundaries
