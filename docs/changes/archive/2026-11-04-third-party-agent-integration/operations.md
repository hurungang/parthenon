# Operations Notes: third-party-agent-integration

## Monitoring

- **Rate-limit / abuse metrics** — counters for `rate_limited`, `invalid_credential`, and `revoked_credential` outcomes per client; alert on sustained `rate_limited` spikes or a single client tripping its limit repeatedly.
- **Latency & error rate** — track `response_ms` and error outcomes per client and per agent type on the `/integrate/*` endpoints.
- **Agent execution health** — client-invoked turns reuse existing agent-runtime health/guardrail metrics (timeouts, guardrail breaches) and should be visible alongside first-party traffic.
- **Exposure posture** — surface which agent types are exposed through `publishable` clients (and are thus publicly reachable), so operators can audit the public surface.

## Logging

- All client invocations (success **and** failure) are recorded in `AgentClientUsageLog` (action = `conversation_turn`/`submit_request`), keyed to the client, never storing the credential value.
- Edge-level rejections (origin/rate/credential) are logged in `backend/logs/communication-hub.log` with the masked credential prefix and reason.
- Resolution/audit writes are logged in `backend/logs/control-center.log`. All traffic is instrumented with OTEL traces, metrics, and logs.

## Common Issues

| Symptom | Likely cause | Resolution |
|---------|--------------|------------|
| Widget returns `origin_denied` | Serving origin not in the client's `allowed_origins` | Add the exact origin on the client |
| Requests return `rate_limited` | Per-client budget exceeded | Raise the client's rate limit or split across clients |
| Chat hangs / error turn | Guardrail/timeout hit in Agent Runtime | Inspect agent-runtime logs for `timeout_or_failed`/`guardrail_*`; treat as an agent-execution issue |
| `invalid_credential` / `revoked_credential` | Client credential rotated, revoked, or expired | Re-issue the credential and update the consumer |
| Client can't reach tools / MCP hub | Expected — clients grant input-interface-only access | Use the API-key (identity) path for tool access; clients only invoke the agent type |

## Master Operations Update Instructions

- **`docs/master/operations/monitoring.md`** — add the integration-gateway metrics and alert guidance above.
- **`docs/master/operations/logging.md`** — document `AgentClientUsageLog` and the CH/CC log lines for client traffic.
- **`docs/master/operations/runbooks/`** — add a `third-party-agent-integration.md` runbook covering origin-denied, rate-limited, credential-rotated, and input-interface-only failure modes and their resolutions.
- **`docs/master/architecture/security/api-key-security.md`** (cross-reference) — document the clients-vs-API-keys credential-class distinction, as noted in the architecture doc's master-update instructions.
