# Operations: Implement Agent Runtime with Gateway

## 1. Monitoring

### New Metrics

The following metrics are introduced by this change. All are emitted via OpenTelemetry and collected by the OTEL Collector.

#### Agent Session Queue (`AgentSessionQueue` / `SessionDispatcher`)

| Metric | Type | Description | Alert Threshold |
|--------|------|-------------|----------------|
| `agent.session.queue_depth` | Gauge | Number of sessions in `queued` state at any point in time | > 50 sustained for 5 min |
| `agent.session.dispatch_latency` | Histogram | Time from session enqueue to first dispatch attempt (p50, p99) | p99 > 30 s |
| `agent.session.failures_total` | Counter | Sessions that reached `failed` terminal state | Rate > 5/min |
| `agent.session.timeouts_total` | Counter | Sessions that exceeded the configured execution timeout | Any non-zero sustained rate |
| `agent.session.completed_total` | Counter | Sessions that reached `completed` terminal state | For success rate: completed / (completed + failed) < 0.95 |

#### Agent Runtime (`AgentRuntimeExecutor` with LangGraph)

| Metric | Type | Description | Alert Threshold |
|--------|------|-------------|-----------------|  
| `agent.runtime.active_sessions` | Gauge | Sessions currently in `running` state | > configured `max_concurrent_sessions` |
| `agent.runtime.execution_duration` | Histogram | Total wall-clock time per session from dispatch to completion (p50, p99) | p99 > configured session timeout |
| `agent.runtime.permission_denials_total` | Counter | Tool call attempts denied by the Permission Manager | Any non-zero sustained rate |
| `agent.runtime.llm_call_duration` | Histogram | Time waiting for LLM inference response (p99) | p99 > 60 s |
| `agent.runtime.langgraph_node_transitions_total` | Counter | Total number of LangGraph state node transitions across all sessions | For diagnostics |
| `agent.runtime.langgraph_errors_total` | Counter | LangGraph state machine errors (invalid transitions, missing nodes) | Any non-zero rate |

#### Agent Permission Manager (`AgentPermissionManager`)

| Metric | Type | Description | Alert Threshold |
|--------|------|-------------|-----------------|
| `agent.permission.cache_hits_total` | Counter | Permission resolution requests served from LRU cache | — |
| `agent.permission.cache_misses_total` | Counter | Permission resolution requests that required a full DB query | — |
| `agent.permission.cache_hit_rate` | Derived | `cache_hits / (cache_hits + cache_misses)` | < 80% (indicates frequent role mutations or undersized cache) |
| `agent.permission.resolution_duration` | Histogram | Time to resolve the full SOP → Skill → MCP tool graph (p99) | p99 > 500 ms |

#### Agent Identities (`AgentIdentityService`)

| Metric | Type | Description | Alert Threshold |
|--------|------|-------------|-----------------|
| `agent.identity.token_refresh_failures_total` | Counter | Failed OIDC token refresh attempts for agent client credentials | Any sustained rate |

### Dashboards to Add

#### Agent Runtime Dashboard

Add to the Grafana instance alongside the existing Agent Engine and MCP Hub dashboards. Minimum panels:

- **Session Queue Depth** — `agent.session.queue_depth` as a time series; horizontal threshold line at alert level.
- **Session Throughput** — `agent.session.completed_total` and `agent.session.failures_total` as stacked bars; failure rate as a percentage line overlay.
- **Session Dispatch Latency** — `agent.session.dispatch_latency` p50 and p99 as a dual-line time series.
- **Active Runtime Sessions** — `agent.runtime.active_sessions` gauge with max-concurrent marker.
- **Execution Duration** — `agent.runtime.execution_duration` p99 histogram.
- **LangGraph Node Transitions** — `agent.runtime.langgraph_node_transitions_total` counter rate for operational insights.
- **Permission Cache Hit Rate** — Derived from `agent.permission.cache_hits_total` and `agent.permission.cache_misses_total`; alert when below threshold.
- **Permission Denials** — `agent.runtime.permission_denials_total` rate; alert annotations when non-zero.

### Alerts to Create

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `AgentSessionQueueBacklog` | `agent.session.queue_depth > 50` for 5 min | Warning | Check `SessionDispatcher` health; verify backend process is running |
| `AgentSessionFailureSpike` | `rate(agent.session.failures_total) > 5/min` for 2 min | Critical | Inspect session failure logs; check OIDC and MCP connectivity |
| `AgentPermissionDenialDetected` | `rate(agent.runtime.permission_denials_total) > 0` for 5 min | Warning | Review agent role assignments; check for misconfigured role |
| `AgentPermissionCacheDegraded` | `agent.permission.cache_hit_rate < 0.80` for 10 min | Warning | Check for unusual role mutation frequency; consider increasing LRU cache size |
| `AgentIdentityTokenFailure` | `rate(agent.identity.token_refresh_failures_total) > 0` for 2 min | Critical | Verify OIDC provider connectivity; check agent client credentials in identity provider |
| `AgentSessionTimeout` | `rate(agent.session.timeouts_total) > 0` for 5 min | Warning | Inspect timed-out sessions; check LLM provider latency and MCP server responsiveness |
| `LangGraphStateErrors` | `rate(agent.runtime.langgraph_errors_total) > 0` for 2 min | Critical | Inspect LangGraph state machine errors; validate agent type configurations |

---

## 2. Logging

All components emit structured JSON logs via OpenTelemetry. Every log entry includes `trace_id` and `span_id` for correlation with distributed traces in Jaeger.

### Log Sources

| Component | Log Source | Access |
|-----------|-----------|--------|
| `SessionDispatcher` | `backend` container stdout | `docker compose logs backend` or Loki query `{service="backend"} |= "session_dispatcher"` |
| `AgentRuntimeExecutor` | `backend` container stdout | `docker compose logs backend` or Loki query `{service="backend"} |= "runtime_executor"` |
| `AgentPermissionManager` | `backend` container stdout | Loki query `{service="backend"} |= "permission_manager"` |
| `AgentSessionService` | `backend` container stdout | Loki query `{service="backend"} |= "agent_session_service"` |
| `LifecycleHandler` (Gateway) | `backend` container stdout | Loki query `{service="backend"} |= "lifecycle_handler"` |

### Key Log Events

#### Agent Session Lifecycle

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `session.enqueued` | INFO | `session_id`, `agent_type_id`, `triggered_by` | Session inserted with `status=queued` |
| `session.dispatched` | INFO | `session_id`, `agent_type_id`, `role_id` | `SessionDispatcher` picks up and hands to `AgentRuntimeExecutor` |
| `session.running` | INFO | `session_id`, `started_at` | Session status updated to `running` |
| `session.completed` | INFO | `session_id`, `duration_ms`, `output_size_bytes` | Session reached `completed` state |
| `session.failed` | ERROR | `session_id`, `error`, `duration_ms` | Session reached `failed` state; `error` contains the exception summary |
| `session.timeout` | WARN | `session_id`, `timeout_s`, `elapsed_ms` | Session exceeded the configured execution timeout |
| `langgraph.node_transition` | DEBUG | `session_id`, `from_node`, `to_node`, `state_snapshot` | LangGraph state machine transitions between nodes |

#### Permission Evaluation

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `permission.cache_hit` | DEBUG | `role_id`, `tool_count` | Permission resolved from LRU cache |
| `permission.cache_miss` | DEBUG | `role_id` | Cache miss; DB query initiated |
| `permission.resolved` | INFO | `role_id`, `tool_count`, `duration_ms` | Full permission graph resolved from DB |
| `permission.denied` | WARN | `job_id`, `role_id`, `tool_id` | Agent attempted to call a tool not in its allowed set |
| `permission.cache_invalidated` | INFO | `role_id` | Role was updated or deleted; cache entry evicted |

#### OAuth Identity Validation

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `identity.token_acquired` | DEBUG | `identity_id`, `identity_type` | Agent client credentials successfully exchanged for access token |
| `identity.token_refresh` | DEBUG | `identity_id` | Existing token refreshed before expiry |
| `identity.token_refresh_failed` | ERROR | `identity_id`, `oidc_error` | Token refresh failed; includes OIDC provider error detail |
| `identity.token_expired` | WARN | `identity_id`, `job_id` | Token discovered to have expired mid-execution |

#### Session Queue Worker

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `dispatcher.poll` | DEBUG | `queued_count`, `worker_slots_available` | Each poll cycle of the `SessionDispatcher` background worker |
| `dispatcher.stalled` | WARN | `session_id`, `stalled_for_s` | A session has been `running` longer than the stall threshold |
| `dispatcher.max_concurrency_reached` | INFO | `active_sessions` | Worker skipped dispatch because concurrency limit was reached |

### Trace Correlation

All agent session operations are wrapped in an OpenTelemetry trace. The `trace_id` appears in every log line emitted during the session's execution span. Use the `trace_id` from a session failure log to locate the full distributed trace in Jaeger, which shows the complete call graph: `LifecycleHandler → AgentSessionService → SessionDispatcher → AgentRuntimeExecutor → AgentPermissionManager → LangGraph State Graph → Skill Engine → MCP Hub`.

---

## 3. Common Issues

### 3.1 Sessions Stuck in `queued` State

**Symptoms**: `agent.session.queue_depth` grows without a corresponding rise in `agent.runtime.active_sessions`; sessions remain in `queued` state for minutes.

**Likely Causes**:
- The `SessionDispatcher` background worker has stopped (backend process crash or unhandled exception in the worker loop).
- Maximum concurrency limit reached — all worker slots are occupied by long-running sessions.
- Database connectivity issue preventing the dispatcher from reading the session queue.

**Resolution**:
1. Check `dispatcher.poll` DEBUG logs — absence of these entries confirms the worker loop is not running.
2. Check `dispatcher.stalled` warnings — long-running sessions occupying all slots will block new dispatches.
3. Verify backend process health: `docker compose ps backend` or equivalent Kubernetes pod status.
4. If the process is healthy but the worker is stalled, restart the backend service to reset the worker loop.
5. If stuck sessions need to be retried, update their status from `running` to `queued` via the Platform API admin tools or database console.

---

### 3.2 Permission Evaluation Failures

**Symptoms**: `agent.runtime.permission_denials_total` is non-zero; sessions complete but produce no output; `permission.denied` WARN logs appear.

**Likely Causes**:
- An agent role's SOP or Skill assignments were modified after the session was dispatched but while the session was using a cached permission set.
- The agent role references an SOP or Skill that has been deleted.
- A newly created agent type was assigned a role with no SOP or Skill assignments.

**Resolution**:
1. Identify the `role_id` and `tool_id` from the `permission.denied` log entry.
2. Open the Agent Roles page in the admin UI; verify the role's SOP and Skill assignments include the tool the agent attempted to call.
3. If the role is correct, check whether the SOP or Skill was recently modified (check `permission.cache_invalidated` events for the `role_id`).
4. Re-launch the failed session after correcting the role assignments — previously denied sessions are not automatically retried.

---

### 3.3 OAuth Token Expiration During Execution

**Symptoms**: `identity.token_expired` WARN log appears mid-session; the session fails shortly after with an authentication error from the OIDC provider or from a downstream MCP server.

**Likely Causes**:
- The OIDC provider's token lifetime is shorter than the maximum session execution time.
- Token refresh logic failed silently before the expiry threshold.
- Network interruption between the backend and the OIDC provider during refresh.

**Resolution**:
1. Check `identity.token_refresh_failed` ERROR logs for the affected `identity_id`.
2. Verify OIDC provider connectivity from the backend host.
3. If the token lifetime is shorter than the session timeout, extend the OIDC client's access token TTL in the identity provider (Keycloak realm settings or external OIDC provider configuration).
4. Verify the agent identity's client credentials are still valid (not expired or revoked) in the identity provider console.
5. Re-launch the failed session after resolving the credential issue.

---

### 3.4 Session Timeout

**Symptoms**: `session.timeout` WARN log; session transitions to `failed` with a timeout error; `agent.session.timeouts_total` counter increments.

**Likely Causes**:
- The LLM provider is slow to respond (`agent.runtime.llm_call_duration` p99 is elevated).
- An MCP server is unresponsive or rate-limiting calls, causing the Skill Engine to block.
- The SOP chain is longer than anticipated (more steps / tool calls than the timeout budget allows).

**Resolution**:
1. Check `agent.runtime.llm_call_duration` p99 in the Agent Runtime dashboard to isolate whether the bottleneck is in LLM inference.
2. Check MCP Hub tool call error rate for the relevant MCP server.
3. If LLM latency is elevated, check LLM provider status pages and API rate limits.
4. If the SOP is inherently long-running, increase the per-session timeout in the backend configuration and align the polling interval on the frontend accordingly.
5. Check for LangGraph state machine errors or infinite loops in `agent.runtime.langgraph_errors_total`.
6. Re-launch the timed-out session once the bottleneck is resolved.

---

### 3.5 Queue Overflow / Backlog

**Symptoms**: `AgentSessionQueueBacklog` alert fires; `agent.session.queue_depth` stays elevated; dispatch latency p99 grows.

**Likely Causes**:
- A burst of simultaneous session submissions (scheduled triggers firing together or a user submitting many sessions at once).
- The `SessionDispatcher` maximum concurrency limit is too low for current load.
- Downstream bottleneck (LLM provider throttling or LangGraph state machine overhead) causing sessions to take longer than usual, starving new dispatches.

**Resolution**:
1. Check `dispatcher.max_concurrency_reached` log events — frequent occurrences confirm a concurrency limit is the constraint.
2. Check `agent.runtime.execution_duration` p99 — if execution time has grown, the same concurrency limit produces lower throughput.
3. If LLM throttling is the cause, consider staggering scheduled session triggers to avoid simultaneous bursts.
4. If infrastructure capacity allows, increase the `SessionDispatcher` concurrency limit in the backend configuration and restart the backend service.
5. Monitor `agent.session.queue_depth` after the change to confirm the backlog is draining.

---

### 3.6 Permission Cache Degradation

**Symptoms**: `AgentPermissionCacheDegraded` alert fires; `agent.permission.cache_hit_rate` drops below 80%; `agent.permission.resolution_duration` p99 increases; DB query load rises.

**Likely Causes**:
- Frequent role updates in the admin UI are continuously invalidating cache entries.
- The LRU cache size is too small for the number of distinct agent roles in use.
- A bulk import or automated process is cycling through many role mutations.

**Resolution**:
1. Check `permission.cache_invalidated` log events for frequency and the affected `role_ids`.
2. If the invalidation rate is normal but the hit rate is still low, the LRU cache capacity is the constraint — increase `AGENT_PERMISSION_CACHE_SIZE` in the backend environment configuration.
3. If bulk role mutations are the cause, schedule them outside peak execution hours.

---

## 4. Master Operations Update Instructions

When this change is promoted to `master-updated`, apply the following changes to `docs/master/operations/`:

### `docs/master/operations/monitoring.md`

Add a new **Agent Runtime** section to the "Key Metrics by Component" table with all metrics listed in Section 1 of this document:
- `agent.session.*` metrics (queue depth, dispatch latency, failures, timeouts, completions) under an **Agent Session Queue** component row.
- `agent.runtime.*` metrics (active sessions, execution duration, permission denials, LLM call duration, LangGraph node transitions, LangGraph errors) under an **Agent Runtime** component row.
- `agent.permission.*` metrics (cache hits, cache misses, cache hit rate, resolution duration) under an **Agent Permission Manager** component row.
- `agent.identity.token_refresh_failures_total` under an **Agent Identity** component row.

Add the **Agent Runtime Dashboard** to the "Dashboards to Create" section with the panel list described in Section 1.

Add all six alerts from Section 1 to an **Agent Runtime Alerts** subsection.

### `docs/master/operations/logging.md`

Add an **Agent Runtime** section covering:
- The four log sources (`SessionDispatcher`, `AgentRuntimeExecutor`, `AgentPermissionManager`, `AgentSessionService`) with their Loki query patterns.
- The full log event tables from Section 2: session lifecycle events (including LangGraph node transitions), permission evaluation events, OAuth identity events, and session queue worker events.
- A note on trace correlation: `trace_id` links agent session logs to the distributed trace in Jaeger spanning `LifecycleHandler → AgentSessionService → SessionDispatcher → AgentRuntimeExecutor → AgentPermissionManager → LangGraph State Graph → Skill Engine → MCP Hub`.

### `docs/master/operations/runbooks/`

Create a new file `docs/master/operations/runbooks/agent-runtime.md` containing the six common issue runbooks from Section 3 of this document (stuck sessions, permission failures, token expiration, session timeouts, queue overflow, permission cache degradation).

### `docs/master/operations/README.md`

- Add **Agent Runtime** to the Dashboards table.
- Add `agent-runtime.md` to the runbooks index with a one-line description: "Resolving stuck sessions, permission failures, OAuth expiry, timeouts, and queue backlogs in the Agent Runtime with LangGraph."
