# Logging — Agent Runtime and Guardrail Events

Agent execution logging: session lifecycle, permission evaluation, OAuth identity validation, and the guardrail event taxonomy with its required fields.

Hub: [logging.md](logging.md) · Operations index: [README.md](README.md)

## Agent Runtime Log Events

### Log Sources

| Component | Log Source | Access |
|-----------|-----------|--------|
| `SessionDispatcher` | `control-center` container stdout | `docker compose logs control-center` or Loki: `{service="control-center"} |= "session_dispatcher"` |
| `AgentRuntimeExecutor` | `control-center` container stdout | `docker compose logs control-center` or Loki: `{service="control-center"} |= "runtime_executor"` |
| `AgentPermissionManager` | `control-center` container stdout | Loki: `{service="control-center"} |= "permission_manager"` |
| `AgentSessionService` | `control-center` container stdout | Loki: `{service="control-center"} |= "agent_session_service"` |
| `LifecycleHandler` (Gateway) | `control-center` container stdout | Loki: `{service="control-center"} |= "lifecycle_handler"` |

### Agent Session Lifecycle Events

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `session.enqueued` | INFO | `session_id`, `agent_type_id`, `triggered_by` | Session inserted with `status=queued` |
| `session.dispatched` | INFO | `session_id`, `agent_type_id`, `role_id` | `SessionDispatcher` picks up and hands to `AgentRuntimeExecutor` |
| `session.running` | INFO | `session_id`, `started_at` | Session status updated to `running` |
| `session.completed` | INFO | `session_id`, `duration_ms`, `output_size_bytes` | Session reached `completed` state |
| `session.failed` | ERROR | `session_id`, `error`, `duration_ms` | Session reached `failed` state; `error` contains the exception summary |
| `session.timeout` | WARN | `session_id`, `timeout_s`, `elapsed_ms` | Session exceeded the configured execution timeout |
| `langgraph.node_transition` | DEBUG | `session_id`, `from_node`, `to_node`, `state_snapshot` | LangGraph state machine transitions between nodes |

### Permission Evaluation Events

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `permission.cache_hit` | DEBUG | `role_id`, `tool_count` | Permission resolved from LRU cache |
| `permission.cache_miss` | DEBUG | `role_id` | Cache miss; DB query initiated |
| `permission.resolved` | INFO | `role_id`, `tool_count`, `duration_ms` | Full permission graph resolved from DB |
| `permission.denied` | WARN | `job_id`, `role_id`, `tool_id` | Agent attempted to call a tool not in its allowed set |
| `permission.cache_invalidated` | INFO | `role_id` | Role was updated or deleted; cache entry evicted |

### OAuth Identity Validation Events

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `identity.token_acquired` | DEBUG | `identity_id`, `identity_type` | Agent client credentials successfully exchanged for access token |
| `identity.token_refresh_failed` | ERROR | `identity_id`, `oidc_error` | Token refresh failed; OIDC provider error detail included |
| `identity.token_expired` | WARN | `identity_id`, `job_id` | Token discovered expired mid-execution |

---

## Agent Execution Guardrail Events

| Event | Level | Description |
|-------|-------|-------------|
| `guardrail.precheck.allowed` | INFO | Pre-execution guardrail checks passed |
| `guardrail.precheck.blocked_cycle` | WARN | Recursive delegation cycle detected and blocked before execution |
| `guardrail.runtime.iteration_limit_exceeded` | WARN | Cumulative iteration ceiling reached |
| `guardrail.runtime.timeout_exceeded` | WARN | Per-agent wall-clock timeout reached |
| `guardrail.runtime.delegation_depth_exceeded` | WARN | Delegation depth limit reached |
| `guardrail.runtime.delegated_steps_exceeded` | WARN | Delegated-step budget reached |
| `guardrail.runtime.token_budget_exceeded_non_conversational` | WARN | Non-conversational or automated execution exceeded hard token budget |
| `guardrail.runtime.conversational_token_threshold_observed` | INFO | Conversational token threshold reached, continuation still allowed |
| `guardrail.runtime.conversational_token_usage_snapshot` | INFO | Conversational current-session token usage snapshot emitted |
| `guardrail.runtime.token_fallback_applied` | INFO | Fallback mode activated where strict token enforcement is unavailable |
| `guardrail.session.terminal` | INFO | Session ended by guardrail with canonical stop reason |

### Guardrail Reason Taxonomy (Canonical)

Use a stable `guardrail_reason` value set for metrics and logs:

- `cycle_blocked`
- `iteration_limit_exceeded`
- `timeout_exceeded`
- `delegation_depth_exceeded`
- `delegated_steps_exceeded`
- `token_budget_exceeded_non_conversational`
- `conversational_token_threshold_observed`
- `token_fallback_applied`

### Required Fields for Guardrail Events

All guardrail events must include the following fields.

| Field | Requirement |
|-------|-------------|
| `timestamp` | ISO 8601 UTC with millisecond precision |
| `service_name` | Emitting service identifier |
| `trace_id` | Correlates to distributed trace |
| `span_id` | Correlates to specific trace span |
| `session_id` | Agent session identifier |
| `agent_type_id` | Agent type associated with the guardrail decision |
| `guardrail_reason` | Canonical reason from the taxonomy above |
| `execution_mode` | Mode used for policy resolution |
| `current_value` | Observed value at decision time |
| `threshold_value` | Policy threshold value used in the decision |
| `policy_snapshot_id` | Policy/version snapshot used to evaluate the guardrail |

Conditional fields:
- `token_usage_current_session` and `continuation_allowed` for conversational token events.
- `fallback_mode` for fallback events.
- `delegation_chain_depth` for delegation-depth and delegated-step events.

### Sensitive Data Exclusions for Guardrail Events

- Never log identity tokens, refresh tokens, JWT payload bodies, API keys, decrypted secrets, or credential material.
- Never log full prompt or tool payload contents in guardrail events.
- Log operational identifiers and counters only; keep guardrail analytics fields stable and non-secret.
