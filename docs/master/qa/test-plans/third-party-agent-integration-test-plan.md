# Third-Party Agent Integration Test Plan

## Scope

Covers external third-party agent clients: client model and credential types (`secret` / `publishable`, immutable `key_type`), input-interface-only scope enforcement, credential resolution (fail-closed), stateful conversational and typed request/response invocations, per-client rate limiting, tenant isolation, dual-identity (secret client + server-side end-user token), and audit logging.

## Test Strategy

Multi-layer coverage across all test layers plus the SDK suites:

- **Backend unit/integration** — real-DB schema verification of `agent_clients` and `agent_client_usage_logs` (per the mandatory DB-change requirements), credential generation/hashing, lifecycle, expiry, revocation, duplicate rejection, per-client rate limiter.
- **Frontend component** — clients list, create dialog (secret/publishable + soft warning), credential-once display.
- **E2E** — mocked-first Playwright journeys plus a mandatory real-backend variant (real POST + real DB insert, labeled `Real Backend Integration - third-party-agent-integration`).
- **SDK** — Python and JS SDK request construction kept in sync with gateway routes/payloads.

Pre-test: verify the Alembic migration is applied (`alembic current` / `alembic upgrade head`); test fixtures apply migrations in setup.

## Coverage Areas

| Area | Why critical |
|------|--------------|
| Client → agent-type binding | A client is bound to exactly one agent type and grants access to its input interface only |
| Secret vs publishable | `secret` = server-side; `publishable` = browser-safe; `key_type` immutable |
| Input-interface-only scope | A client credential cannot list/call tools, reach the MCP hub, or impersonate an identity |
| Credential resolution | Invalid/revoked/expired credentials fail closed with non-distinguishing errors |
| Stateful conversations | Multi-turn streaming with heartbeats and error turns for conversational agent types |
| Typed request/response | Validated typed `AgentOutput` with validation status and raw-output fallback |
| Dual identity (secret client) | End-user token validated, tenant-matched, held server-side only |
| Origin / rate limit | Non-allowlisted origins rejected; over-limit rejected with `rate_limited` |
| Tenant isolation | Clients never reach another tenant's agent types, data, or resources |
| Audit logging | Every invocation (success + failure) recorded; credential value never stored or logged |

## Critical Scenarios

### Client management
- WHEN an admin creates a client for an agent type, THEN it is bound to exactly that type and appears in the clients list.
- WHEN an admin creates a `publishable` client, THEN a soft warning (full behavior exposed publicly) is shown and creation proceeds.
- WHEN an admin revokes a client, THEN its credential becomes immediately unusable.
- WHEN a mutation attempts to change a client's `key_type`, THEN it is rejected (immutable).

### Input-interface-only scope (critical)
- WHEN a client credential is used, THEN it can only invoke the target agent type's input interface — never list/call tools, never reach the MCP hub, never authenticate as an agent identity.
- WHEN a client invokes a conversational agent type, THEN the conversation is stateful and streamed with heartbeats and error turns.
- WHEN a client invokes a typed agent type, THEN a validated typed result is returned.

### Credential resolution & isolation
- WHEN a client credential is invalid/revoked/expired, THEN it is rejected with a non-distinguishing error.
- WHEN a client attempts to reach another tenant's agent type, THEN it is rejected (strict tenant isolation).
- WHEN a `publishable` client resolves, THEN no identity token is returned; the agent type runs with its own identity.

### Dual identity (secret client, server-only)
- WHEN a backend invokes with a secret client + end-user token, THEN the token is validated, tenant-matched, held server-side, and forwarded only to passthrough/dual-identity MCP servers.
- WHEN the end-user token is invalid or cross-tenant, THEN the request is rejected.

### Rate limit & audit
- WHEN the per-client rate limit is exceeded, THEN requests are rejected with `rate_limited`.
- WHEN any invocation succeeds or fails, THEN an `AgentClientUsageLog` row is written, never storing the credential value.

## Edge Cases & Risks

- Origin matching: exact vs wildcard, trailing-slash/port normalization; malformed entries must not open access.
- Rate-limit windows: requests at the limit and across window rollover counted correctly.
- Concurrent credential rotation: rotating mid-flight must not leave the old credential usable.
- Publishable exposure: soft warning is the only guard — tenant-owned risk.
- SDK drift: SDKs and the served embed snippet must stay in sync with gateway routes/payloads.
- Streaming disconnect: reconnecting clients receive in-flight replies via the session registry.

## Acceptance Criteria

- Client bound to exactly one agent type; input-interface-only access enforced.
- Secret vs publishable credential types; `key_type` immutable.
- Publishable client creation shows a soft warning (no hard block).
- Credential value displayed exactly once at creation; never retrievable afterward.
- Tenant isolation maintained; invocations audited without credential leakage.
- SDKs work end-to-end against the gateway contract.

## Test File References

| Test file | Layer | Covers |
|-----------|-------|--------|
| `backend/tests/test_agent_client.py` | unit/integration | Schema verification (tables/columns incl. `agent_type_id` FK, `key_type`), credential generation/hashing, lifecycle, expiry, duplicate checks, usage log, revocation |
| `backend/tests/test_integration_gateway.py` | unit | Per-client rate limiter (window, per-key isolation, no-limit passthrough) |
| `frontend/src/__tests__/agent-clients/AgentClientsPage.test.tsx` | component | Clients list, publishable soft warning, create + credential-once display |
| `e2e/tests/agent-clients.spec.ts` | E2E (mocked) | Renders, lists clients, publishable warning, create + credential-once |
| `e2e/tests/agent-clients.real-backend.spec.ts` | E2E (real backend) | `Real Backend Integration - third-party-agent-integration` — real POST with real DB insert |
| `sdk/parthenon-python/test/test_client.py` | SDK | Python SDK request construction (submit, config) |
| `sdk/parthenon-js/index.js` | SDK | JS SDK syntax/structure check |
