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
- Caller-scoped allowlists enforced independently for `agent_runtime` and `communication_hub` callers
- Requests to internal endpoints outside caller allowlist are denied by default before handler logic executes
- Authorized tool call: `authorized=true` + identity token included in response; decision logged with outcome `authorized`
- Unauthorized tool call (insufficient permissions): `authorized=false` with reason `insufficient_permissions`; returns 403; decision logged with outcome `denied`; identity token NOT included in response
- Invalid/expired/revoked certificate: authorization rejected before permission check; 401/403 returned; no identity token exposed

### Agent Execution Guardrail Policy and Persistence (add-agent-execution-guardrails)
- Internal context endpoints return effective guardrail policy snapshots used by runtime pre-check and loop enforcement
- Session status updates preserve guardrail stop semantics separately from functional error semantics
- Execution log persistence captures structured guardrail events used by execution summary views
- Control Center remains the only persistence owner for guardrail stop outcomes and guardrail event logs

### Model-Usage Guardrails (vendor → model → guardrail hierarchy)
- Per-period guardrail CRUD: `POST /api/v1/agents/guardrails/model-usage-limits` creates exactly one guardrail per `(model_id, model_name, period)`; `(model_id, model_name, period)` uniqueness is enforced and returns 409 on duplicate
- `GET` / `PUT` / `DELETE` per-period guardrail: list/read/update/delete a single per-period guardrail row using the per-guardrail shape (`period`, `limit_value`, `unit`, `enforcement_posture`, `is_active`)
- Default `unit = 'k'` and default `enforcement_posture = 'terminate'` on create; explicit values preserved through update
- `GET /api/v1/agents/guardrails/model-usage-posture` returns current posture rollups (within_limit, approaching_limit, breached) for all configured per-period guardrails
- `ModelAvailabilityService._check_guardrail_breach()` is invoked on every pre-execution availability check; multi-vendor breach dominates other deny reasons
- Vendor `is_disabled` toggle cascades to every `ModelAvailability` row under the vendor (set `is_disabled = true`, `disabled_reason = vendor_cascaded`); re-enable restores each row to its prior manual state
- Per-model `ModelAvailability` toggle sets `disabled_reason = manual` on operator-driven changes
- `preflight_availability` returns `{ allowed, reason?, disabled_reason? }` for the resolved model; on deny, the run is recorded with `AgentJob.termination_category` of `model_disabled` or `vendor_disabled`
- `ExecutionEventCategory` accepts `model_disabled`, `vendor_disabled`, and `guardrail_breached` as user-visible event categories; these are distinct from standard execution failures

### Runtime Topology and Operator Termination
- `RuntimeTopologyController` merges three sources: `AgentJob` (live), `ConversationSession` (synthetic active/sleep), and `AgentInstance` (created/active/closed/error)
- `AgentJob.status = terminated` is a distinct enum value from `failed`; migration `f4a5b6c7d8e9` adds it
- Late-arriving status updates from the underlying LangChain framework are rejected by terminal-state guards in `update_session_status`
- `TerminationOrchestrator` performs permission-gated terminate requests; the request is routed Control Center → Communication Hub → Agent Runtime
- Cascade termination: terminating a parent `AgentJob` walks the delegation graph and cancels all active delegated children
- Sleep conversations (no live agent) cannot be terminated — only ended via the conversation session management endpoint
- 404 from Agent Runtime `/terminate` is treated as success

### Recursion and Dead-Loop Prevention
- `RecursionValidationService` runs at agent create, update, and run initiation
- `result = fail` blocks the action; `result = pass` allows it
- The validation outcome is recorded in `SopRecursionValidationCheck` with `check_trigger = create | update | run`
- Specific cycle paths are recorded in `SopRecursionValidationFinding` as JSON arrays of SOP IDs

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

### Scenario: Guardrail Policy Snapshot and Stop Metadata
- Agent Runtime requests context from Control Center before execution starts
- Control Center returns effective guardrail fields and policy snapshot details through internal APIs
- Runtime terminal guardrail outcomes are persisted via status/log APIs without schema drift or metadata loss

## Edge Cases
- Serial number collision: database unique constraint prevents duplicate serial numbers; tested with bulk issuance
- Token refresh during tool execution: Control Center refreshes proactively (within 5-minute window) before returning token; prevents mid-execution expiry
- OAuth provider prolonged outage: after max retries, clear 503 returned; operator can resolve by fixing OAuth provider
- Revocation status check service outage: internal requests fail closed and produce auditable deny events

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
- `backend/tests/integration/test_agent_session_lifecycle.py` — session status lifecycle and persisted terminal outcome behavior used by runtime stop propagation
- `backend/tests/integration/test_internal_allowlist_partitioning.py` — endpoint partitioning by caller type with explicit allow/deny outcomes
- `backend/tests/integration/test_internal_deny_audit_events.py` — deny-by-default and structured deny evidence assertions
- `backend/tests/integration/test_internal_revocation_fail_closed.py` — fail-closed behavior when revocation validation is unavailable

### E2E Tests
- `e2e/tests/agent-security-segregation.spec.ts` — **Real Backend Integration**: certificate authentication endpoint wiring, metadata security assertion (no identity tokens in response), tool authorization with certificate validation, revocation flow
- `e2e/tests/agent-identity-token-refresh.spec.ts` — **Real Backend Integration**: token refresh endpoint wiring and auth requirement verification
