# Runbook: Third-Party Agent Integration Failures

Covers failure modes of the public `/integrate/*` gateway (Communication Hub) and its client credentials (Control Center).

## Symptoms

- Widget or API call returns `origin_denied`
- Requests return `rate_limited`
- Calls return `invalid_credential` / `revoked_credential`
- Chat hangs or returns an error turn (`timeout_or_failed` / `guardrail_*`)
- Client cannot reach tools or the MCP hub (expected — clients are input-interface-only)
- `integration.client.auth.failed` WARN entries in `backend/logs/communication-hub.log`

---

## Resolution Steps

### 1. `origin_denied` — Serving Origin Not Allowlisted

**Log indicator:** `integration.client.auth.failed` with `reason=origin_denied` in `backend/logs/communication-hub.log`

1. Read the `origin` field on the rejected request; it must match **exactly** (scheme + host + port) one of the client's `allowed_origins`.
2. Add the exact origin on the client via the Clients UI (or `PATCH /api/v1/clients/{id}`). Trailing slashes and port mismatches are the most common causes.
3. Confirm the deployment-level `INTEGRATION_CORS_ORIGINS` allowlist on Communication Hub is not empty — an empty list rejects all requests regardless of per-client origins.
4. Verify nginx forwards the `Origin` header unchanged on `/integrate/*` (no rewriting/stripping).

### 2. `rate_limited` — Per-Client Budget Exceeded

**Log indicator:** `integration.client.auth.failed` with `reason=rate_limited`; `rate_limited` outcomes on `integration.request_total`

1. Identify the tripping client by `client_id` on the rejected requests.
2. Raise the client's rate limit (or widen its window) via the Clients UI, or split the consumer's traffic across multiple clients.
3. If a single client trips its limit repeatedly and unexpectedly, treat as abuse: investigate the caller IP in `AgentClientUsageLog` and consider deactivating the client (`PATCH /api/v1/clients/{id}/status`).
4. Check the integration-gateway Redis counters are reachable — a Redis outage surfaces as gateway errors, not silent bypass.

### 3. `invalid_credential` / `revoked_credential` — Credential Rotated, Revoked, or Expired

**Log indicator:** `integration.client.auth.failed` with `reason=invalid_credential` or `revoked_credential`

1. Confirm the consumer holds the **current** credential: a recent rotation via `POST /api/v1/clients/{id}/credential` invalidates the previous value immediately.
2. Re-issue via credential rotation and update the consumer; the clear-text is shown once at rotation.
3. If `revoked_credential`, check the client's status in the Clients UI — reactivate (`active`) if deactivation was unintentional, or re-issue a credential if revoked deliberately.
4. Sustained rejection rates with no matching client change may indicate probing — review `AgentClientUsageLog` IP addresses and consider rotating all exposed credentials.

### 4. Chat Hangs / Error Turn — Agent Execution Failure (Not a Gateway Issue)

**Log indicator:** agent-runtime logs show `timeout_or_failed` or `guardrail_*`

1. Treat as an **agent-execution issue**, not an integration issue: inspect `backend/logs/agent-runtime.log` for `timeout_or_failed` / `guardrail_<reason>` on the target agent type.
2. Follow the [agent-execution-guardrails runbook](agent-execution-guardrails.md) for guardrail stops.
3. Client-invoked turns appear in the same agent-runtime health/guardrail metrics as first-party traffic — filter by the agent type.

### 5. Client Cannot Reach Tools or MCP Hub — Expected Behavior

1. This is by design: a client grants **input-interface-only** access (conversation turn or typed submit). It is not an identity and cannot list/call tools, reach the MCP hub, or impersonate an agent.
2. If the consumer needs tool/MCP access, direct them to the API-key (identity) path — see [runbooks/api-key-auth.md](api-key-auth.md).
3. Confirm the invoked agent type runs with its own identity + role: no identity is ever derived from the client credential.

---

## Escalation

- Gateway-wide 5xx or all clients rejected: check Communication Hub health, its mTLS path to Control Center, and Redis reachability — see [runbooks/communication-hub-disconnect.md](communication-hub-disconnect.md).
- Suspected credential compromise: rotate the credential immediately, review `AgentClientUsageLog`, then follow section 3.
