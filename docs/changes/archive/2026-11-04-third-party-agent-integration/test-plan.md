# Test Plan: third-party-agent-integration

## 1. Test Strategy

Multi-layer coverage across all four test directories (`backend/tests/`, `frontend/src/__tests__/`, `e2e/tests/`, SDK/example tests):

- **Backend unit tests** — client model/`key_type` logic, credential hashing/rotation, rate-limit math, scope enforcement.
- **Backend integration tests** — real-database verification of the schema change (see the critical DB-change requirements below), client CRUD, credential resolution, input-interface-only scope, tenant isolation, audit-log writes.
- **Frontend component tests** — clients list, create dialog (secret/publishable + soft warning), revoke, integration guide, error handling.
- **E2E tests** — full widget and request/response flows, including at least one real-backend (no-mocks) variant for the migration.
- **SDK/example tests** — JS and Python SDKs and the runnable local example.

Manual verification covers visual white-labeling (no Parthenon branding) and embed-snippet accuracy.

## 2. Coverage Areas

| Area | Why critical |
|------|--------------|
| Client → agent-type binding | A client is bound to exactly one agent type and grants access to its input interface only |
| Secret vs publishable | `secret` = server-side; `publishable` = browser-safe; `key_type` immutable |
| Input-interface-only scope | A client credential cannot list/call tools, reach the MCP hub, or impersonate an identity |
| Credential resolution | Invalid/revoked/expired credentials fail closed with non-distinguishing errors |
| Conversational widget | Multi-turn, streamed reply, error turn, white-label theme, no Parthenon branding |
| Non-conversational request/response | Validated typed `AgentOutput` with validation status + raw-output fallback; clear input-shape errors |
| Server-to-server secret client + dual identity | Consumer backend with secret client; optional end-user token validated + tenant-matched (server-only) |
| Origin / rate limit | Non-allowlisted origins rejected; over-limit rejected (`rate_limited`) |
| Tenant isolation | Clients never reach another tenant's agent types/data/resources |
| Audit logging | Every invocation (success + failure) recorded in `AgentClientUsageLog` |

## 3. Critical Scenarios

### Client management
- WHEN an admin creates a client for an agent type, THEN it is bound to exactly that type and appears in the clients list.
- WHEN an admin creates a `publishable` client, THEN a soft warning is shown (exposing the agent type's full behavior publicly) and creation proceeds.
- WHEN an admin revokes a client, THEN its credential becomes immediately unusable.
- WHEN an admin attempts to change a client's `key_type`, THEN it is rejected (immutable).

### Input-interface-only scope (critical)
- WHEN a client credential is used, THEN it can only invoke the target agent type's input interface — never list/call tools, never reach the MCP hub, never authenticate as an agent identity.
- WHEN a client invokes a conversational agent type, THEN the conversation is streamed with heartbeats and error turns.
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

## 4. Edge Cases & Risks

- **Origin matching** — exact vs wildcard origins; trailing-slash/port normalization; malformed entries must not open access.
- **Rate-limit windows** — requests at the limit and across window rollover counted correctly.
- **Concurrent credential rotation** — rotating a credential mid-flight must not leave the old credential usable.
- **`key_type` immutability** — secret↔publishable mutation must be rejected.
- **Exposed agent-type risk** — a `publishable` client exposes the agent type's full behavior publicly; the soft warning is the only guard (tenant-owned risk).
- **SDK drift** — SDKs and the served embed snippet must stay in sync with the gateway's routes/payloads.
- **Streaming disconnect** — reconnecting clients receive in-flight replies via the session registry.

## 5. Acceptance Criteria Checklist

- [ ] Client bound to exactly one agent type; grants input-interface-only access
- [ ] Secret vs publishable credential types; `key_type` immutable
- [ ] Client cannot list/call tools, reach the MCP hub, or impersonate an identity
- [ ] Publishable client creation shows a soft warning (no hard block)
- [ ] Conversational white-label widget works for anonymous end users; no Parthenon branding
- [ ] Non-conversational submit returns a validated typed response; invalid input rejected clearly
- [ ] App-to-app secret client + optional server-side dual identity works
- [ ] Origin + rate limits enforced; tenant isolation maintained; no sensitive data leaked
- [ ] All invocations audited; credential value never logged
- [ ] JS + Python SDKs and runnable local example work end-to-end

## 6. Test File References

| Test file | Layer | Covers |
|-----------|-------|--------|
| `backend/tests/test_agent_client.py` | unit/integration | `AgentClient`/`AgentClientUsageLog` schema verification, credential generation/hashing, lifecycle, expiry, duplicate checks, usage log, revocation, 1:N binding |
| `backend/tests/test_integration_gateway.py` | unit | Per-client rate limiter (window, per-key isolation, no-limit passthrough) |
| `frontend/src/__tests__/agent-clients/AgentClientsPage.test.tsx` | component | Clients list, publishable soft warning, create + credential-once display |
| `e2e/tests/agent-clients.spec.ts` | E2E (mocked) | Renders, lists clients, publishable warning, create + credential-once (4 scenarios) |
| `e2e/tests/agent-clients.real-backend.spec.ts` | E2E (real backend) | `test.describe('Real Backend Integration - third-party-agent-integration')` — real POST with real DB insert |
| `sdk/parthenon-python/test/test_client.py` | SDK | Python SDK request construction (submit, config) |
| `sdk/parthenon-js/index.js` | SDK | JS SDK (syntax/structure via `node --check`) |

## Critical: Database-Change Test Requirements

This change has `has_db_changes: true`. The following are mandatory (per the change-lifecycle skill):

1. **Backend integration tests MUST verify schema changes took effect** — `backend/tests/test_agent_client.py` must inspect the schema (information_schema on Postgres; SQLAlchemy inspector on the SQLite test DB) to verify the `agent_clients` and `agent_client_usage_logs` tables exist with the expected columns (incl. `agent_type_id` FK, `key_type`, and the publishable-only config columns). Include negative tests (revoked credential unresolvable; duplicate-name rejection; expired-client rejection).
2. **E2E MUST include at least one real-backend test** — `e2e/tests/agent-clients.real-backend.spec.ts` must submit a real POST to the real API and verify a real DB insert (not a mock), labeled `test.describe('Real Backend Integration - third-party-agent-integration')`.
3. **Pre-test checklist**:
   - Verify the migration is applied: `cd backend && python -m alembic current` shows the third-party-integration revision.
   - If not applied: `python -m alembic upgrade head` before running tests.
   - Backend test fixtures must apply `alembic upgrade head` in setup.
   - The test database must match production schema.
