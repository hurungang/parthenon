# Runbook: Agent Runtime

Resolving stuck sessions, permission failures, OAuth expiry, timeouts, and queue backlogs in the Agent Runtime with LangGraph.

---

## 1. Sessions Stuck in `queued` State

**Trigger Alert**: `AgentSessionQueueBacklog` — `agent.session.queue_depth > 50` sustained for 5 min.

**Symptoms**: `agent.session.queue_depth` grows without a corresponding rise in `agent.runtime.active_sessions`; sessions remain in `queued` state for minutes.

**Likely Causes**:
- The `SessionDispatcher` background worker has stopped (backend process crash or unhandled exception in the worker loop).
- Maximum concurrency limit reached — all worker slots are occupied by long-running sessions.
- Database connectivity issue preventing the dispatcher from reading the session queue.

**Resolution**:
1. Check `dispatcher.poll` DEBUG logs — absence of these entries confirms the worker loop is not running.
2. Check `dispatcher.stalled` warnings — long-running sessions occupying all slots will block new dispatches.
3. Verify backend process health: `docker compose ps agent-runtime` or equivalent Kubernetes pod status.
4. If the process is healthy but the worker is stalled, restart the backend service to reset the worker loop.
5. If stuck sessions need to be retried, update their status from `running` to `queued` via the Platform API admin tools or database console.

---

## 2. Permission Evaluation Failures

**Trigger Alert**: `AgentPermissionDenialDetected` — `rate(agent.runtime.permission_denials_total) > 0` for 5 min.

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

## 3. OAuth Token Expiration During Execution

**Trigger Alert**: `AgentIdentityTokenFailure` — `rate(agent.identity.token_refresh_failures_total) > 0` for 2 min.

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

## 4. Session Timeout

**Trigger Alert**: `AgentSessionTimeout` — `rate(agent.session.timeouts_total) > 0` for 5 min.

**Symptoms**: `session.timeout` WARN log; session transitions to `failed` with a timeout error; `agent.session.timeouts_total` counter increments.

**Likely Causes**:
- The LLM provider is slow to respond (`agent.runtime.llm_call_duration` p99 is elevated).
- An MCP server is unresponsive or rate-limiting calls, causing the Skill Engine to block.
- The SOP chain is longer than anticipated (more steps / tool calls than the timeout budget allows).

**Resolution**:
1. Check `agent.runtime.llm_call_duration` p99 in the Agent Runtime Dashboard to isolate whether the bottleneck is in LLM inference.
2. Check MCP Hub tool call error rate for the relevant MCP server.
3. If LLM latency is elevated, check LLM provider status pages and API rate limits.
4. If the SOP is inherently long-running, increase the per-session timeout in the backend configuration and align the polling interval on the frontend accordingly.
5. Check for LangGraph state machine errors or infinite loops in `agent.runtime.langgraph_errors_total`.
6. Re-launch the timed-out session once the bottleneck is resolved.

---

## 5. Queue Overflow / Backlog

**Trigger Alert**: `AgentSessionQueueBacklog` — `agent.session.queue_depth > 50` sustained for 5 min.

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

## 6. Permission Cache Degradation

**Trigger Alert**: `AgentPermissionCacheDegraded` — `agent.permission.cache_hit_rate < 0.80` for 10 min.

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

## 7. Paused Conversational Turns and Durable Checkpoints

**Trigger Alerts**: `ResumePausePersistFailed`, `ResumeSuccessRateDegraded`, `ResumeCheckpointUnavailable`, `ResumeClaimContentionSustained`, `ResumeReaperStalled`.

**Symptoms**: an approval does nothing; a turn reports "the paused turn could not be resumed"; `pause could not be persisted`; `claim lost` / `claim renewal failed`; a restarted instance cannot continue a turn it paused.

**How Agent Runtime behaves on this build**

- Each conversational turn runs with a durable checkpointer backed by Control Center (through the Communication Hub relay). AR holds **no** datastore path: the payload leaves AR over the existing mTLS internal client.
- A pause flushes the checkpoint **before** the turn reports waiting. If the flush or the resume-index write fails, the turn ends `timeout_or_failed` instead of pretending to wait — a shown-as-waiting turn is always answerable.
- The paused turn is **instance-independent**: any AR instance can claim it, load the payload, rebuild the agent, and continue with the operator's answer. Restarting or replacing AR does not orphan a pause.
- A turn that was actively working (no pause checkpoint) has no resumable state; a restart resolves it terminally with "the assistant stopped unexpectedly…".
- The claim lease is `CONVERSATION_TURN_CLAIM_TTL_SECONDS` (default 45 s) and is renewed while the resumed turn streams; a holder may renew its own lease, a different instance gets `409` and does not double-dispatch.

**Diagnosis**

1. `Durable checkpoint flushed for conversation …` must precede the `waiting_for_human` report. Absent → item 5 below (the pause failed to persist).
2. `Resume …: checkpoint load failed`, `no loadable checkpoint — marking unresumable`, or `checkpoint unusable` → the payload is missing, consumed, or from an incompatible schema version. The turn resolves terminally; re-issue is safe (nothing was applied).
3. `claim lost (…, holder=…)` while another instance is alive → duplicate dispatch; while the holder is dead → wait one claim TTL, then re-answer (idempotent). Never clear claim fields by hand.
4. `claim renewal failed` repeatedly → certificate/transport trouble on the AR→CH relay; check the AR certificate and the relay 401 signature (`Turn resume relay upstream rejection … HTTP 401`).
5. `Conversation … pause could not be persisted` → the relay refused the write (CH down or AR ahead of CH), the payload exceeded the byte cap, or CC returned 5xx (usually an unapplied migration). Fix the ordering/cap/schema, then retry the request; no write occurred.

**Resolution order**

1. Confirm the deployed build on all three services — the legacy "delegated step timed out or failed" message means old code handled the answer.
2. Confirm `alembic current` reports head and the resume/checkpoint tables exist.
3. Confirm CH is serving the checkpoint relay before AR writes pauses (AR must never be rolled forward ahead of CH).
4. If only one instance misbehaves, remove it from the fleet rather than clearing claims; the lease will expire.

Full operator procedure: [conversational-turn-recovery.md](conversational-turn-recovery.md).
