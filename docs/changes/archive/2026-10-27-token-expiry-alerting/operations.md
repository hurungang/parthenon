# Operations — Token Expiry Alerting

Operational view of the Token Expiry Alerting epic: what to monitor, where events are logged, and how to respond to failures. Context: [Architecture](./architecture.md) · [Tech Spec](./tech-spec.md). Log destinations follow `docs/config.yaml` (`backend/logs/`).

---

## Monitoring

New metrics, emitted with OpenTelemetry per project convention and tenant-scoped:

- **Token health gauges** — count of agent identities and MCP sessions in each state (`healthy` / `expiring` / `expired` / `unknown`), exportable per tenant. Sustained non-zero `expired` counts indicate un-remediated credentials.
- **Token health ratio** — percentage of identities/sessions expiring within 7 days; a rising trend warns before expiry counts grow.
- **Preflight outcomes** — counters for PROCEED, PROCEED+WARN, and BLOCKED per execution start, labeled by target kind (agent identity vs MCP session).
- **Preflight block rate** — BLOCKED ÷ total preflight checks; spikes indicate an IdP-side token policy change or a mass expiry event (e.g., after an IdP realm migration).
- **Preflight failure rate** — preflight calls that error or time out (Gateway could not get an outcome); should be ~0 — non-zero means CC reachability or signed-header problems and executions fail closed.
- **Token refresh failures** — rate of `last_token_refresh_outcome = failure` on identities and MCP sessions; persistent failure on a single identity suggests revocation; correlated failure across many suggests IdP outage.
- **Refresh loop latency/duration** — time spent in refresh attempts (identity and MCP session paths); growth may indicate IdP slowness.
- **Alert conditions** (suggested): expired-token gauge > 0 for > 24h; block rate > threshold over 15 min; preflight error rate > 0; refresh failure rate spikes.

## Logging

Per `docs/config.yaml`, logs live in `backend/logs/` (rotated ~10 MB; read the file without numeric suffix for current output). No token values, refresh tokens, or credential material is ever logged.

- **`control-center.log`** — primary file for this feature:
  - Token Health Service classification results (entity type, entity ID, resulting state, threshold decision at the 7-day boundary).
  - Token refresh attempts and outcomes for agent identities (success/failure, retry count, error class) — extends the existing `token_refresh_logs` audit; failures logged with reason but no token material.
  - MCP session OAuth refresh outcomes (session ID, success/failure, error detail).
  - Preflight evaluations from the internal API: execution context, resolved targets (agent + subagents), per-target state, final outcome (PROCEED / PROCEED+WARN / BLOCKED), and the user-facing message.
  - Every `TokenHealthCheck` audit row write (blocked runs especially — proof that expired tokens were surfaced before the run).
  - Re-auth/refresh trigger endpoint activity from the dashboard remediation actions.
- **`communication-hub.log`** — Agent Gateway preflight gate:
  - Preflight call issued per execution start (correlation with session/job ID), CC round-trip duration.
  - BLOCKED decisions and the blocked message delivered to the requester; WARN notices attached to started executions.
  - Fail-closed events: preflight unreachable, timeout, or missing/invalid signed internal headers (search for rejection entries; cross-reference `control-center.log` for the receiving side).
- **`agent-runtime.log`** — minimal by design:
  - Execution rejected/not started due to an upstream preflight BLOCKED outcome surfaced via the Gateway (outcome only; agents never receive token data).
  - No token-health computation or token logging occurs in AR.
- **Troubleshooting tips**:
  - "Why was this execution blocked?" — search `communication-hub.log` for the job/session ID, then `control-center.log` for the matching preflight evaluation and `TokenHealthCheck` row.
  - "Why is this identity stuck expired?" — search `control-center.log` for the identity ID to find refresh failure reasons.
  - Preflight rejections at CH — search `communication-hub.log` for rejection entries; see `docs/config.yaml` troubleshooting notes for internal-call failures.

## Common Issues

- **IdP unreachable during re-auth / refresh** — refresh attempts fail (logged in `control-center.log`); identities remain in their prior state and retries follow the existing refresh retry/backoff. Preflight sees stale-but-known state: still-valid tokens proceed, expired ones block. Resolution: restore IdP connectivity; health state self-corrects on the next refresh or read-time recomputation.
- **Refresh token revoked (user or admin action in the IdP)** — refresh fails persistently with an authorization error for that identity/session; `last_token_refresh_outcome` = failure; preflight blocks executions using it once the access token expires. Remediation: full interactive re-authentication via the dashboard deep-link; refresh alone cannot fix a revoked refresh token.
- **Clock skew between CC and the IdP** — tokens classified as expired while the IdP considers them valid (or vice versa); symptom is blocks/warnings that don't match reality, or premature refresh loops. Check that CC and containers sync time (NTP); classification uses CC's clock, so CC skew is the one that matters.
- **Expired token discovered mid-execution** — should not happen once the preflight gate is in place; if observed, it means either (a) the token expired between preflight and the tool call mid-run (acceptable; short-window race), or (b) a token was used that the preflight didn't resolve (a gap in subagent/session resolution — a defect; check the preflight evaluation log for the missing target and file against the resolution logic).
- **Preflight blocks everything after an IdP change** — mass expiry (e.g., realm keys rotated, refresh tokens invalidated) shows as a block-rate spike; remediate via dashboard bulk re-auth and verify with the expired-gauge metric returning to zero.
- **Warnings not clearing after re-auth** — health state persists until refresh/read recomputation; if it persists, check `control-center.log` for the refresh outcome and whether the re-auth flow actually stored new tokens.

## Master Operations Update Instructions

On completion, update `docs/master/operations/` (keep entries concise; no schema code):

- `docs/master/operations/monitoring.md` — add the token health gauges/ratios, preflight outcome and block-rate counters, refresh-failure rate, and the suggested alert conditions.
- `docs/master/operations/logging.md` — add rows to the per-component log-event table: Control Center (token health classification, refresh outcomes, preflight evaluations, `TokenHealthCheck` writes), Agent Gateway/Communication Hub (preflight gate decisions and fail-closed events), Agent Runtime (blocked-outcome surfacing only).
- `docs/master/operations/runbooks/oidc-token-failure.md` — extend with the new remediation flow: dashboard token-health cards → deep-link re-auth/refresh, and reference preflight BLOCKED as the front-line symptom.
- New runbook `docs/master/operations/runbooks/token-expiry-alerting.md` — cover: investigating a blocked execution (CH log → CC preflight log → `TokenHealthCheck` row), mass block-rate spikes, revoked refresh tokens, clock-skew diagnosis, and warnings not clearing.
- `docs/master/operations/runbooks/mcp-credential-error.md` — cross-reference MCP session token health state and the re-auth remediation path.
- `docs/master/operations/README.md` — index the new runbook.
