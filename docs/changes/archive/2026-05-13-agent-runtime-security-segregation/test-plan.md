# Test Plan: Agent Runtime Security Segregation

**Created by:** Tester Agent  
**Date:** 2026-05-13  
**Status:** Ready for test implementation

---

## 1. Test Strategy

### Overall Approach
This change requires **comprehensive testing across all three layers** because it involves database schema changes, backend service logic, and end-to-end authorization flows. Given the security-critical nature (certificate-based auth, token management), testing must verify both happy paths and failure modes.

### Test Layers
1. **Backend Unit Tests** — Test individual functions in isolation (CA operations, token refresh logic, permission resolution)
2. **Backend Integration Tests** — Test against real database with migrations applied; verify schema changes took effect
3. **E2E Tests** — Test full agent execution flow; **MUST include at least ONE test against real backend** (no mocked responses)

### Test Environment
- **Backend tests:** Real PostgreSQL database with Alembic migrations applied (`alembic upgrade head`)
- **E2E tests:** Mix of mocked API responses (for speed) and real backend integration tests (for migration verification)
- **Test data:** Seed database with test agent types, identities, and roles
- **Mock OAuth provider:** For token refresh tests (deterministic responses)

---

## 2. Coverage Areas

### Critical Coverage Areas

#### 1. Database Schema Changes
**Why Critical:** Migration issues can cause production failures that mocked tests don't catch

**What to Test:**
- All four new tables created with correct columns and types
- `agent_identity` table updated with three new columns
- Constraints work as expected (unique serial numbers, foreign keys, nullable fields)
- Indexes created for performance-critical lookups (serial_number, validated_at)
- Existing data unaffected by migration (agent_identity records still accessible)

**Test Approach:**
- Run `alembic upgrade head` in test fixture setup
- Query `information_schema.columns` to verify table structure
- Insert test records to verify constraints
- Query test records to verify data integrity

#### 2. Certificate Lifecycle
**Why Critical:** Invalid certificates must be rejected immediately; compromised certs must be revocable

**What to Test:**
- CA initialization (root CA cert generation on first startup)
- Certificate issuance (sign CSR, store in database, return to agent)
- Certificate validation (signature, expiration, revocation checks)
- Certificate renewal (agent requests new cert before expiration)
- Certificate revocation (revoked certs immediately rejected)
- CN parsing (extract agent-type:instance-id correctly)

**Test Approach:**
- Backend integration tests against real database
- Mock CA operations in Agent Runtime tests (unit level)
- E2E test with real certificate issuance and validation

#### 3. Token Refresh Automation
**Why Critical:** Manual token refresh caused production outages; automatic refresh must be reliable

**What to Test:**
- Token expiration detection (identifies tokens expiring within 5 minutes)
- Token refresh success (calls OAuth provider, stores new token, logs success)
- Token refresh failure (invalid_grant, network errors, rate limiting)
- Retry logic (exponential backoff: 1s, 5s, 15s)
- Rate limit handling (respects HTTP 429, backs off appropriately)
- Audit logging (all refresh attempts logged with outcome)

**Test Approach:**
- Mock OAuth provider responses (success, failure, rate_limit)
- Backend integration tests verify database updates
- E2E test with real token expiration and refresh

#### 4. Authorization Flow (Certificate + Permission + Token)
**Why Critical:** Entire security model depends on correct authorization checks

**What to Test:**
- Certificate validation before tool execution
- Permission resolution (agent type → roles → SOPs → skills → tools)
- Tool authorization decision (allowed vs. denied)
- Identity token provision (Control Center provides token to Communication Hub, NOT to Agent Runtime)
- Authorization failures (invalid cert, expired cert, revoked cert, insufficient permissions, token refresh failure)
- Audit logging (all authorization decisions logged with certificate details)

**Test Approach:**
- Backend integration tests for permission resolution logic
- E2E tests with both mocked and real backend variants
- At least ONE E2E test hits real backend to verify authorization flow

#### 5. Agent Runtime Security Guarantees
**Why Critical:** Agent Runtime must NEVER receive identity tokens (zero-trust requirement)

**What to Test:**
- Metadata response does NOT contain identity tokens (security assertion)
- Agent Runtime uses client certificate for all requests (no JWT tokens)
- Certificate loaded from files on startup
- Certificate renewed before expiration
- Agent Runtime shuts down gracefully if certificate expires without renewal

**Test Approach:**
- E2E test verifies metadata response structure (assert no identity_token field)
- Backend test verifies `GET /agent/metadata` response schema excludes tokens
- E2E test with certificate expiration and renewal

---

## 3. Critical Scenarios

### Scenario 1: Certificate Issuance and First Use
**WHEN:**  
- Admin requests certificate for new agent instance via `POST /certificates/issue`

**THEN:**
- Certificate created in database with status `active`
- Certificate PEM and private key PEM returned to admin
- Certificate valid for 24 hours from issuance
- Certificate CN format: `agent-type:instance-id`
- Certificate serial number is unique and stored in database
- Certificate validation succeeds immediately after issuance

**Test Implementation:**
- Backend integration test: Issue certificate, verify database record, validate certificate
- E2E test: Agent Runtime loads newly issued certificate, requests metadata successfully

---

### Scenario 2: Valid Certificate Authentication
**WHEN:**
- Agent Runtime with valid certificate requests metadata from Control Center

**THEN:**
- Control Center validates certificate (signature, expiration, not revoked)
- Control Center extracts agent-type:instance-id from CN
- Control Center returns metadata (SOPs, skills, instructions, model configs)
- Response does NOT include identity tokens
- Certificate validation logged in `certificate_validation_log` with outcome `valid`

**Test Implementation:**
- Backend integration test: Mock TLS handshake, provide valid cert, verify metadata response
- Backend integration test: Query `certificate_validation_log`, verify log entry with outcome `valid`
- E2E test: Real Agent Runtime with valid cert requests metadata, receives response without tokens

---

### Scenario 3: Expired Certificate Rejection
**WHEN:**
- Agent Runtime with expired certificate attempts to request metadata or call tool

**THEN:**
- Control Center validates certificate, detects expiration
- Control Center returns 401 Unauthorized with message "Certificate expired"
- Certificate validation logged with outcome `expired`
- No metadata returned, no tool executed
- Agent Runtime receives clear error message

**Test Implementation:**
- Backend integration test: Provide expired certificate, verify 401 response
- Backend integration test: Query `certificate_validation_log`, verify log entry with outcome `expired`
- E2E test: Agent Runtime with expired cert receives 401, logs error

---

### Scenario 4: Revoked Certificate Rejection
**WHEN:**
- Admin revokes certificate via `POST /certificates/revoke`
- Agent Runtime with revoked certificate attempts to request metadata or call tool

**THEN:**
- Certificate marked `revoked` in `agent_instance_certificate` table
- Entry added to `certificate_revocation_entry` table with serial number and reason
- Subsequent validation attempts return outcome `revoked`
- Control Center returns 403 Forbidden with message "Certificate revoked: {reason}"
- Certificate validation logged with outcome `revoked`

**Test Implementation:**
- Backend integration test: Issue cert, revoke cert, attempt to use revoked cert, verify 403 response
- Backend integration test: Query `certificate_revocation_entry`, verify entry exists
- Backend integration test: Query `certificate_validation_log`, verify log entry with outcome `revoked`
- E2E test: Agent Runtime with revoked cert receives 403, cannot execute tools

---

### Scenario 5: Automatic Token Refresh on Expiration
**WHEN:**
- Communication Hub requests authorization for tool call
- Agent identity's access token is expired
- Control Center detects expiration and triggers refresh

**THEN:**
- Control Center retrieves encrypted refresh token from `agent_identity` table
- Control Center calls OAuth provider token endpoint with refresh token grant
- OAuth provider returns new access token with expiration
- Control Center stores new encrypted access token in `agent_identity` table
- Control Center updates `access_token_expires_at` and `last_token_refresh_at`
- Control Center updates `token_status` to `active`
- Control Center logs refresh attempt in `token_refresh_log` with outcome `success`
- Control Center returns fresh access token to Communication Hub
- Communication Hub uses fresh token for tool execution

**Test Implementation:**
- Backend integration test: Mock expired token, mock OAuth provider success response, verify token updated in database
- Backend integration test: Query `token_refresh_log`, verify log entry with outcome `success`
- Backend integration test: Verify `agent_identity.token_status` is `active` after refresh
- E2E test: Agent calls tool with expired token, tool executes successfully after automatic refresh

---

### Scenario 6: Token Refresh Failure
**WHEN:**
- Control Center attempts to refresh expired token
- OAuth provider returns error (invalid_grant, network error, etc.)

**THEN:**
- Control Center retries with exponential backoff: 1s, 5s, 15s (max 3 attempts)
- If all retries fail, Control Center updates `token_status` to `refresh_failed`
- Control Center logs refresh attempt in `token_refresh_log` with outcome `failure` and error message
- Control Center returns 503 Service Unavailable to Communication Hub
- Communication Hub returns 503 to Agent Runtime with message "Identity token refresh failed: {reason}"
- Agent execution is blocked until operator resolves identity issue

**Test Implementation:**
- Backend integration test: Mock OAuth provider failure responses, verify retry logic
- Backend integration test: Query `token_refresh_log`, verify 3 log entries with outcome `failure`
- Backend integration test: Verify `agent_identity.token_status` is `refresh_failed`
- E2E test: Agent calls tool with expired token, OAuth refresh fails, receives 503 error

---

### Scenario 7: Token Refresh Rate Limiting
**WHEN:**
- Control Center attempts to refresh token
- OAuth provider returns HTTP 429 (Too Many Requests) with Retry-After header

**THEN:**
- Control Center respects rate limit, does NOT retry immediately
- Control Center logs refresh attempt in `token_refresh_log` with outcome `rate_limited`
- Control Center waits for Retry-After duration before next attempt
- If rate limit clears, subsequent refresh succeeds
- Authorization request returns cached token if still valid (fallback behavior)

**Test Implementation:**
- Backend integration test: Mock OAuth provider 429 response with Retry-After header
- Backend integration test: Query `token_refresh_log`, verify log entry with outcome `rate_limited`
- Backend integration test: Verify Control Center respects Retry-After duration (does not retry early)

---

### Scenario 8: Authorization Decision - Sufficient Permissions
**WHEN:**
- Communication Hub receives tool call from Agent Runtime with valid certificate
- Communication Hub requests authorization from Control Center
- Agent type has permissions for requested tool

**THEN:**
- Control Center validates certificate (succeeds)
- Control Center extracts agent_type_id from certificate
- Control Center resolves agent type → roles → SOPs → skills → tools
- Control Center checks if requested tool is in allowed tool set (succeeds)
- Control Center retrieves agent identity and checks/refreshes token (succeeds)
- Control Center returns authorization response: `authorized=true`, includes identity token
- Communication Hub executes tool with Control Center-provided identity token
- Tool execution succeeds, result returned to Agent Runtime
- Authorization decision logged with outcome `authorized`

**Test Implementation:**
- Backend integration test: Provide valid cert, authorized tool, verify authorization response
- Backend integration test: Verify identity token included in response
- E2E test: Real Agent Runtime calls authorized tool, tool executes successfully

---

### Scenario 9: Authorization Decision - Insufficient Permissions
**WHEN:**
- Communication Hub receives tool call from Agent Runtime with valid certificate
- Agent type does NOT have permissions for requested tool

**THEN:**
- Control Center validates certificate (succeeds)
- Control Center resolves permissions (agent type → roles → tools)
- Control Center checks if requested tool is in allowed tool set (fails)
- Control Center returns authorization response: `authorized=false`, reason `insufficient_permissions`
- Communication Hub returns 403 Forbidden with message "Insufficient permissions: tool '{tool_name}' not allowed for agent type '{agent_type}'"
- Tool is NOT executed
- Authorization decision logged with outcome `denied`

**Test Implementation:**
- Backend integration test: Provide valid cert, unauthorized tool, verify 403 response
- Backend integration test: Verify response includes required permission details
- E2E test: Real Agent Runtime attempts unauthorized tool call, receives 403 error

---

### Scenario 10: Certificate Renewal Before Expiration
**WHEN:**
- Agent Runtime background task detects certificate expires within 5 hours (80% of 24-hour lifetime)

**THEN:**
- Agent Runtime requests new certificate from Control Center `POST /certificates/issue`
- Control Center issues new certificate with fresh 24-hour validity
- Agent Runtime receives new certificate and private key
- Agent Runtime atomically switches to new certificate (no downtime)
- Agent Runtime discards old certificate
- Subsequent metadata requests and tool calls use new certificate
- Certificate renewal logged with new serial number and expiration

**Test Implementation:**
- Backend integration test: Issue certificate, simulate time advance to 19 hours, trigger renewal, verify new cert issued
- E2E test: Agent Runtime with near-expired cert renews automatically, continues operation

---

### Scenario 11: Agent Runtime Shutdown on Certificate Expiration
**WHEN:**
- Agent Runtime certificate expires
- Certificate renewal fails (Control Center unavailable, network error, admin revoked cert issuance permission)

**THEN:**
- Agent Runtime detects certificate expired and renewal failed
- Agent Runtime logs critical error: "Certificate expired and renewal failed, shutting down"
- Agent Runtime shuts down gracefully (no new tool calls accepted)
- Agent Runtime does NOT attempt tool calls with expired certificate (fail-safe)

**Test Implementation:**
- E2E test: Agent Runtime with expired cert, mock Control Center unavailable, verify graceful shutdown

---

### Scenario 12: Metadata Response Security Assertion
**WHEN:**
- Agent Runtime requests metadata from Control Center with valid certificate

**THEN:**
- Control Center returns metadata: SOPs, skills, instructions, model configs
- Response does NOT include `identity_token`, `access_token`, or `refresh_token` fields (security requirement)
- Agent Runtime validates response structure, asserts no identity tokens present
- If identity tokens found in response, Agent Runtime logs security violation and rejects response

**Test Implementation:**
- Backend integration test: Call `GET /agent/metadata`, verify response schema excludes identity fields
- E2E test: Agent Runtime asserts metadata response has no identity tokens, logs security check passed

---

## 4. Edge Cases & Risks

### Edge Case 1: CA Private Key Corruption
**Risk:** CA private key becomes corrupted or inaccessible; cannot issue new certificates

**Test:**
- Simulate CA key file corruption on Control Center startup
- Verify Control Center fails to start with clear error message
- Verify existing certificates can still be validated (uses CA public cert only)

### Edge Case 2: Certificate Serial Number Collision
**Risk:** Certificate serial numbers are not unique; collision causes validation failures

**Test:**
- Issue 1000 certificates in rapid succession
- Verify all serial numbers are unique
- Verify database unique constraint prevents duplicate serial numbers

### Edge Case 3: Token Refresh During Tool Execution
**Risk:** Token expires mid-tool-execution; tool call fails

**Mitigation:** Control Center checks token expiration BEFORE returning it; if expires within 5 minutes, refreshes proactively

**Test:**
- Mock token that expires in 3 minutes
- Trigger tool call, verify Control Center refreshes token before tool execution
- Verify tool executes with fresh token, does not fail mid-execution

### Edge Case 4: Agent Runtime Restart During Certificate Renewal
**Risk:** Agent restarts during renewal; new cert not yet stored, old cert expired

**Mitigation:** Certificate renewal triggered at 80% lifetime (19 hours), giving 5-hour window before expiration

**Test:**
- Simulate Agent Runtime restart at 19.5 hours (after renewal triggered, before completion)
- Verify Agent Runtime loads old (still valid) certificate on restart
- Verify renewal re-triggered on next expiration check
- Verify new certificate issued and loaded within 5-hour window

### Edge Case 5: OAuth Provider Prolonged Outage
**Risk:** OAuth provider unavailable for extended period; all token refreshes fail; all agents blocked

**Mitigation:** Token status set to `refresh_failed`; operator alerted to resolve OAuth provider issue

**Test:**
- Mock OAuth provider returning network errors for 10 consecutive refresh attempts
- Verify token status set to `refresh_failed` after max retries
- Verify authorization requests return 503 with clear error message
- Verify audit logs show all failed refresh attempts with error details

### Edge Case 6: Certificate Revocation Race Condition
**Risk:** Certificate revoked during active tool execution; tool completes with revoked cert

**Mitigation:** Certificate validation happens BEFORE tool execution; revocation takes effect immediately

**Test:**
- Agent Runtime calls tool with valid cert
- Admin revokes cert while tool call is in-flight (before Communication Hub validates)
- Verify Communication Hub validates cert, detects revocation, returns 403
- Verify tool is NOT executed

---

## 5. Acceptance Criteria Checklist

Mapping test scenarios to PRD acceptance criteria:

### AC-1: Agent Runtime Isolation
- [x] **Scenario 2:** Metadata response does NOT include identity tokens
- [x] **Scenario 12:** Agent Runtime asserts metadata response has no identity tokens
- [x] **Scenario 8:** Communication Hub uses Control Center-provided token (not agent-provided)
- [x] **Backend Test:** Verify agent runtime logs contain ZERO identity tokens

### AC-2: Certificate-Based Authentication
- [x] **Scenario 1:** Certificate CN format: `agent-type:instance-id`
- [x] **Scenario 2:** Valid certificate authentication succeeds
- [x] **Scenario 3:** Expired certificate rejected
- [x] **Scenario 4:** Revoked certificate rejected
- [x] **Backend Test:** Control Center validates certificate signature against CA

### AC-3: Automatic Token Refresh
- [x] **Scenario 5:** Token refresh on expiration detected before permission check
- [x] **Scenario 6:** Token refresh failure results in explicit error (not silent failure)
- [x] **Backend Test:** Token refresh operations logged with outcome in `token_refresh_log`

### AC-4: Zero-Trust Tool Authorization
- [x] **Scenario 8:** Certificate validated before tool call processed
- [x] **Scenario 9:** Insufficient permissions result in 403 before tool execution
- [x] **Backend Test:** Communication Hub requests permissions for EVERY tool call
- [x] **Backend Test:** Authorization check failures logged before tool execution

### AC-5: Audit Trail
- [x] **Scenario 2, 3, 4:** Certificate validation logged with outcome in `certificate_validation_log`
- [x] **Scenario 5, 6, 7:** Token refresh logged with outcome in `token_refresh_log`
- [x] **Backend Test:** Audit logs include sufficient detail (cert CN, identity ID, tool name, timestamp)

### AC-6: Fail-Safe Error Handling
- [x] **Scenario 3:** Invalid certificate → explicit error (not silent failure)
- [x] **Scenario 6:** Token refresh failure → explicit error with reason
- [x] **Scenario 9:** Insufficient permissions → explicit error with required vs. granted
- [x] **Backend Test:** All error responses include actionable information

---

## 6. Test File References

### Backend Integration Tests (SQLite in-memory, all passing ✅)
- `backend/tests/integration/test_certificate_lifecycle.py` — CA init, certificate issuance, validation (valid/expired/revoked), CN parsing, audit logging (Scenarios 1, 2, 3, 4) — **10 tests**
- `backend/tests/integration/test_token_refresh_security.py` — Token expiration detection, OAuth refresh (success/failure/rate-limited), retry logic, audit logging (Scenarios 5, 6, 7) — **8 tests**
- `backend/tests/integration/test_authorization_flow.py` — Permission resolution (no role, invalid cert, valid cert with token refresh), authorization middleware (Scenarios 8, 9) — **6 tests**

### E2E Tests (Playwright, all passing ✅)
- `e2e/tests/agent-security-segregation.spec.ts` — Certificate auth flow, metadata security (AC-1 zero-trust), tool authorization outcomes, certificate revocation; includes **6 real backend integration tests** (endpoint wiring + routing checks) — **15 tests**

### Defect Fixed During Testing
- **`backend/app/services/certificate_authority.py`** — RSA signature verification used wrong `verify()` call (missing PKCS1v15 padding). Fixed by replacing with `cert.verify_directly_issued_by(_ca_certificate)` which handles RSA/EC keys correctly. This was a production defect that caused all certificate validation to fail with `invalid_signature`.

**CRITICAL E2E Test Requirements:**
- At least ONE test in each spec file must run against **real backend** (no `page.route()` mocks)
- Label real backend tests clearly: `test.describe('Real Backend Integration - ...')`
- Real backend tests verify migrations applied and authorization flow works end-to-end

---

## 7. Pre-Test Checklist for Database Changes

**CRITICAL:** Before running backend integration or E2E tests:

1. **Generate migration:**
   ```bash
   cd backend
   alembic revision --autogenerate -m "Add certificate management and audit tables"
   ```

2. **Apply migration locally:**
   ```bash
   alembic upgrade head
   ```
   **⚠️ EASY TO FORGET:** This step is critical; tests can pass with mocked databases while real database is not migrated

3. **Verify migration applied:**
   ```bash
   alembic current
   ```
   Verify output shows new migration ID

4. **Verify table structure:**
   ```sql
   SELECT column_name, data_type, is_nullable
   FROM information_schema.columns
   WHERE table_name IN ('agent_instance_certificates', 'certificate_revocation_entries', 'token_refresh_logs', 'certificate_validation_logs');
   ```
   Verify all expected columns exist with correct types

5. **Run backend integration tests against real database:**
   ```bash
   pytest backend/tests/integration/ -v
   ```
   Verify all tests pass

6. **Run at least ONE E2E test against real backend:**
   ```bash
   npm run test:e2e -- agent-runtime/tool-authorization.spec.ts
   ```
   Verify test hits real backend and passes (checks authorization flow with real database)

**Why this matters:** Tests can pass with in-memory databases or mocked APIs while the real database migration was never applied. This causes production failures that tests didn't catch.

---

## Summary

This test plan ensures comprehensive coverage of:
- ✅ Database schema changes (real database, verify migrations applied)
- ✅ Certificate lifecycle (issue, validate, renew, revoke)
- ✅ Token refresh automation (success, failure, rate limiting)
- ✅ Authorization flow (cert + permission + token)
- ✅ Security guarantees (no identity tokens in Agent Runtime)
- ✅ Audit logging (all critical operations logged)
- ✅ Edge cases and failure modes

**Test Distribution:**
- Backend unit tests: ~25 tests (fast, isolated)
- Backend integration tests: ~40 tests (real database, verify schema)
- E2E tests: ~15 tests (including real backend variants)

**Total estimated test count:** ~80 tests covering all critical paths and edge cases.
