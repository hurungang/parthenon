# Control Center Test Plan

## What to Test

### Certificate Authority (CA) Management
- CA initialization on first startup: root CA certificate and private key generated; stored securely; startup fails with clear error if key is unavailable or corrupt
- CA initialization is idempotent: second startup uses existing CA, does not regenerate
- Certificate issuance (`POST /certificates/issue`): signed certificate created in `agent_instance_certificate` with status `active`; CN format `agent-type:instance-id`; serial number globally unique (database unique constraint enforced)
- Certificate serial numbers remain unique across 1000+ rapid issuances
- Issued certificate PEM and private key returned to requester; private key not stored in database
- Issued certificate valid for 24 hours from issuance time

### Certificate Validation
- Valid certificate: signature verified against CA cert, expiration checked, revocation checked → outcome `valid` logged in `certificate_validation_log`
- Expired certificate: returns 401 with "Certificate expired"; outcome `expired` logged
- Revoked certificate: returns 403 with "Certificate revoked: {reason}"; outcome `revoked` logged
- Unknown serial number: returns certificate_not_found error; outcome logged
- CN parsing: extracts `agent_type_id` and `instance_id` from `agent-type:instance-id` format correctly; malformed CN rejected
- All validation outcomes written to `certificate_validation_log` (cert serial, outcome, timestamp, reason)

### Certificate Revocation
- `POST /certificates/revoke`: marks certificate `revoked` in `agent_instance_certificate`; inserts entry into `certificate_revocation_entry` with serial number and reason
- Revocation is immediate: next validation of revoked serial returns `revoked` outcome
- Revocation entries persist correctly (serial number, revoked_at, reason)

### Automatic Token Refresh
- Token expiration detection: identifies agent identities with `access_token_expires_at` within 5 minutes
- Token refresh success: calls OAuth provider token endpoint; stores new encrypted access token; updates `access_token_expires_at`, `last_token_refresh_at`, `token_status → active`; logs outcome `success` in `token_refresh_log`
- Token refresh failure (`invalid_grant`, network error): logs outcome `failure` with error message; retries with exponential backoff (1 s, 5 s, 15 s); after max retries, sets `token_status → refresh_failed`; returns 503 to caller
- Token refresh rate limiting: OAuth provider HTTP 429 with Retry-After header respected; logs outcome `rate_limited`; does not retry before Retry-After elapses
- All refresh attempts logged in `token_refresh_log` (identity_id, outcome, error_message, timestamp)
- Proactive refresh: token expiring within 5 minutes refreshed before being returned to Communication Hub (prevents mid-execution expiry)

### Permission Resolution
- `AgentPermissionManager` traversal: `AgentType → AgentRole → SOPs → Skills → MCP tools`; direct Skill assignments merged; result set has no duplicates
- LRU cache returns consistent results for same `role_id`; cache invalidated on role update or delete
- Circular SOP dependency detected; finite tool set resolved without infinite recursion
- Missing role or type returns empty permission set (not an error)

### Metadata Endpoint Security
- `GET /agent/metadata` returns SOPs, skills, system instructions, model configs for the requesting agent type
- Response does NOT contain `identity_token`, `access_token`, or `refresh_token` fields — zero-trust requirement; any identity token in metadata response is a critical defect
- Endpoint requires valid client certificate; unauthenticated requests rejected
- Certificate CN determines which agent type's metadata is returned (no cross-type data leakage)

### Authorization Decision
- Full authorization flow: validate certificate → resolve permissions → check tool in allowed set → check/refresh token → return authorization response
- Authorized tool call: `authorized=true` + identity token included in response; decision logged with outcome `authorized`
- Unauthorized tool call (insufficient permissions): `authorized=false` with reason `insufficient_permissions`; returns 403; decision logged with outcome `denied`; identity token NOT included in response
- Invalid/expired/revoked certificate: authorization rejected before permission check; 401/403 returned; no identity token exposed

## Critical Scenarios

### Scenario: Certificate Authority Bootstrap
- First startup generates CA root cert
- Existing certs remain validatable after CA re-initialization
- Corrupted CA key file produces startup failure, not silent operation

### Scenario: Full Authorization Chain
- Valid cert → agent type resolved from CN → roles/permissions resolved → requested tool authorized → token refreshed if needed → authorized response with fresh token
- Any link in the chain failing produces an explicit error, not a silent failure or data leak

### Scenario: Token Refresh Under Failure
- OAuth provider unreachable for extended period → all refresh attempts logged → `token_status = refresh_failed` → 503 returned to callers with actionable error message

## Edge Cases
- Serial number collision: database unique constraint prevents duplicate serial numbers; tested with bulk issuance
- Token refresh during tool execution: Control Center refreshes proactively (within 5-minute window) before returning token; prevents mid-execution expiry
- OAuth provider prolonged outage: after max retries, clear 503 returned; operator can resolve by fixing OAuth provider

## Acceptance Criteria
- AC-1 (Agent Runtime Isolation): Metadata endpoint verified to exclude identity tokens
- AC-2 (Certificate-Based Auth): All certificate states (valid, expired, revoked) handled correctly with appropriate HTTP status codes
- AC-3 (Automatic Token Refresh): Refresh logged with outcome; failure results in explicit 503, not silent failure
- AC-4 (Zero-Trust Authorization): Certificate validated before every tool call; unauthorized tools blocked before execution; no token provided for denied requests
- AC-5 (Audit Trail): All certificate validations and token refresh attempts logged with full detail

## Test File References

### Backend — Unit Tests
- `backend/tests/unit/test_token_refresh_service.py` — token expiration detection, refresh logic, retry/backoff, rate-limit handling

### Backend — Integration Tests
- `backend/tests/integration/test_certificate_lifecycle.py` — CA initialization, certificate issuance, validation (valid/expired/revoked), CN parsing, revocation against real database with schema verification
- `backend/tests/integration/test_authorization_flow.py` — full authorization chain: certificate validation + permission resolution + token retrieval; `certificate_validation_log` population
- `backend/tests/integration/test_token_refresh_security.py` — token refresh with mocked OAuth provider; retry/backoff; rate-limit; `token_refresh_log` population; `token_status` transitions

### E2E Tests
- `e2e/tests/agent-security-segregation.spec.ts` — **Real Backend Integration**: certificate authentication endpoint wiring, metadata security assertion (no identity tokens in response), tool authorization with certificate validation, revocation flow
- `e2e/tests/agent-identity-token-refresh.spec.ts` — **Real Backend Integration**: token refresh endpoint wiring and auth requirement verification
