# Monitoring — Alerts

Alert names, conditions, severities, and first actions. Metric definitions live in [monitoring-metrics.md](monitoring-metrics.md); panel layout lives in [monitoring-dashboards.md](monitoring-dashboards.md).

Hub: [monitoring.md](monitoring.md) · Operations index: [README.md](README.md)

## Alerts to Configure

| Alert | Condition | Severity |
|-------|-----------|----------|
| Agent instance saturation | Active instance count for any agent type ≥ 90% of its configured `max_instances` for 5 minutes | Warning |
| MCP tool call error rate | Tool call error rate > 5% over a 5-minute window | Critical |
| Scheduler queue backlog | Scheduler queue depth growing continuously for more than 10 minutes without decreasing | Warning |
| Platform API 5xx rate | Platform API 5xx HTTP error rate > 1% over a 5-minute window | Critical |
| Redis eviction | Redis eviction rate > 0 (any eviction event) | Warning |
| OTEL Collector export errors | OTEL Collector export error rate > 0 | Warning |
| OTEL Collector health endpoint down | `http://otel-collector:13133/` returns non-200 for > 2 minutes | Warning |
| No traces ingested in Jaeger | No new spans for > 10 minutes in a production environment | Warning |
| Backend telemetry init failure | Backend log contains `[TELEMETRY ERROR]` at startup | Critical |
| File exporter disk pressure | Disk usage on the file exporter volume > 80% | Warning |
| Frontend config endpoint error | `GET /api/v1/telemetry/config` returning 5xx for > 5 minutes | Warning |

Route Warning alerts to the operations on-call channel. Route Critical alerts to the on-call engineer with immediate escalation.

### Agent Runtime Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `AgentSessionQueueBacklog` | `agent.session.queue_depth > 50` for 5 min | Warning | Check `SessionDispatcher` health; verify backend process is running |
| `AgentSessionFailureSpike` | `rate(agent.session.failures_total) > 5/min` for 2 min | Critical | Inspect session failure logs; check OIDC and MCP connectivity |
| `AgentPermissionDenialDetected` | `rate(agent.runtime.permission_denials_total) > 0` for 5 min | Warning | Review agent role assignments; check for misconfigured role |
| `AgentPermissionCacheDegraded` | `agent.permission.cache_hit_rate < 0.80` for 10 min | Warning | Check for unusual role mutation frequency; consider increasing LRU cache size |
| `AgentIdentityTokenFailure` | `rate(agent.identity.token_refresh_failures_total) > 0` for 2 min | Critical | Verify OIDC provider connectivity; check agent client credentials in identity provider |
| `AgentSessionTimeout` | `rate(agent.session.timeouts_total) > 0` for 5 min | Warning | Inspect timed-out sessions; check LLM provider latency and MCP server responsiveness |
| `LangGraphStateErrors` | `rate(agent.runtime.langgraph_errors_total) > 0` for 2 min | Critical | Inspect LangGraph state machine errors; validate agent type configurations |

### Agent Execution Guardrail Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `GuardrailStopRateSpike` | `guardrail_stop_total` above baseline for 5 min | Warning | Check stop reasons by `agent_type` and `execution_mode`; confirm no workflow rollout regression |
| `CycleBlockSurge` | `guardrail_cycle_block_total` above baseline for 5 min | Warning | Follow [runbooks/agent-execution-guardrails.md](runbooks/agent-execution-guardrails.md) cycle triage and isolate recursive delegation paths |
| `TimeoutRegression` | `guardrail_timeout_limit_hit_total` above baseline for 10 min | Warning | Correlate with LLM and MCP latency; validate timeout policy thresholds |
| `DelegationBudgetExhaustion` | `guardrail_delegation_budget_hit_total` above baseline for 5 min | Warning | Validate delegation depth and delegated-step budgets for affected agent types |
| `ConversationalTokenVisibilityGap` | `guardrail_conversational_token_usage_snapshot_total = 0` while conversational sessions are active for 5 min | Critical | Treat as observability gap; verify conversational token snapshot event flow immediately |
| `ConversationalTokenHardStopDetected` | conversational terminal sessions classified with token-budget stop reason for 2 min | Critical | Treat as policy regression; validate execution-mode branch and continuation behavior |
| `TokenFallbackOveruse` | `guardrail_token_fallback_applied_total` above baseline for 15 min | Warning | Review provider capability mapping and fallback policy usage |
| `StopReasonMissing` | terminal sessions without stop reason classification for 2 min | Critical | Validate stop metadata forwarding and persistence fields end-to-end |

### Control Center Assistant Alerts

Signals marked *proposed* have no OTel counter yet — create the alert against the log-derived series described in [logging-control-center-assistant.md](logging-control-center-assistant.md) until the counter ships.

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `AssistantPermissionDenialSpike` | `rate(internal_management_tool_permission_denials_total) > baseline` for 5 min | Warning | Review the authenticated user's role/`agent::*` grants; distinguish user-scope denials from parity-map regression (see [runbooks/control-center-assistant.md](runbooks/control-center-assistant.md) §2) |
| `AssistantIdentityResolutionFailure` | `rate(internal_management_tool_identity_resolution_failures_total) > 0` for 2 min | Critical | Fail-closed enforcement is rejecting valid actions; check OAuth `sub` → `PlatformUser` mapping immediately |
| `McpOAuthAuthRejectionSpike` | `rate(mcp_oauth_auth_rejections_total) > baseline` for 5 min | Warning | Investigate token issuer/JWKS/clock-skew/identity-provisioning and tenant resolution; runbook §1 |
| `AssistantDeleteRejectionSurge` | `rate(internal_management_tool_delete_rejections_total) > baseline` for 5 min | Warning | Investigate misuse or an assistant instruction regression — deletion is never supported |
| `AssistantSeedFailed` | `assistant_seed_result_total{outcome="failed"}` present at startup, or `AssistantSeeder failed` ERROR in `control-center.log` | Critical | Assistant agent type/tools missing for at least one tenant; runbook §3 |
| `AssistantTurnWatchdogFires` *(proposed)* | `rate(assistant_turn_watchdog_fires_total) > 0` for 5 min | Warning | Separate `timeout` (hung AR turn) from `persistence_timeout` (reply delivered, CC write hung); runbook §4 |
| `AssistantIterationLimitSurge` | `rate(guardrail_iteration_limit_hit_total{agent_type="<seeded assistant>"}) > baseline` for 10 min | Warning | Assistants are looping on tool discovery; check the tool-catalog size and the model's tool-selection behavior; runbook §4 |
| `AssistantInterventionTimeoutSpike` *(proposed)* | `rate(assistant_intervention_total{outcome="timeout"}) > baseline` for 10 min | Warning | Operators are not answering confirmations within `conversation_intervention_timeout_seconds`; writes are aborting (no mutation) |
| `AssistantWsDisconnectSpike` *(proposed)* | `rate(chat_ws_disconnect_total) > baseline` for 5 min | Warning | Distinguish idle-proxy closes (normal) from `4003`/`1008` auth-and-tenant rejections; runbook §5 |
| `AssistantCatalogAnomaly` *(proposed)* | `increase(assistant_catalog_anomalies_total[10m]) > 0` | Warning | Empty catalog, page-cap truncation, or `cc` entity visibility anomaly; runbook §7 |

### Conversational Turn Resume Alerts

These counters are new with the conversational-durability changes and are **log-derived until OTel counters ship** (see [logging-conversation-turns.md](logging-conversation-turns.md) under Conversation Activity and Resumable Turn Events). The orphaned alert is a **zero-tolerance invariant** alert, not a routine-expiry signal.

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `ConversationActivityStaleBacklog` | Non-terminal working rows older than the staleness bound > 0 for 10 min | Warning | Confirm the reaper started and is resolving stale rows, and that CH heartbeats are touching live rows; investigate the hung AR turn; runbook §8 |
| `ConversationActivityHydrationFailure` | `Activity hydration failed` rate > 0 for 5 min | Critical | Users cannot recover status on reconnect. Check the CH→CC internal route, signed tenant headers, internal allowlist, and migrations; runbook §7 |
| `ConversationActivityForwardFailure` | `Activity upsert failed` rate sustained above baseline | Warning | The persisted state lags the live transition. Check CC health and the internal allowlist; a single failed forward self-heals on the next hydration |
| `ResumePausePersistFailed` | Any `pause could not be persisted` in `agent-runtime.log` (or `failed` pauses) for 5 min | Critical | Approvals will not survive a restart. Check the CH checkpoint relay, the byte cap (CC and CH equal), and that AR is not running ahead of CH; runbook §5 |
| `ResumeSuccessRateDegraded` | Resume success ratio < 0.95 over 15 min (min 20 attempts) | Critical | Split by reason: checkpoint reasons → runbook §4; dispatch/instance reasons → AR reachability, certificates, CH routing (runbook §1, §5) |
| `ResumeOrphanedTurn` | Any turn shown as waiting that is not answerable, within 10 min | Critical | The core invariant broke. Capture the `conv_session_id`s, verify the activity's live resume link, then page the owning team; runbook §7 |
| `ResumeCheckpointUnavailable` | Any `checkpoint_*` resume failure in 10 min | Critical | Purge horizon shorter than the answer window, cap too small, or payload schema drift after an upgrade; runbook §4 |
| `ResumeClaimContentionSustained` | `held_by_other` > 50% of claims for 10 min | Warning | Duplicate dispatch loop or a stale claim from a dead AR instance; wait out the claim TTL, then remove the offending instance; runbook §3 |
| `ResumeTerminalExpirySpike` | `expired` terminal resolutions above baseline for 15 min | Warning | Operators are answering outside the window — raise the tenant resume TTL or fix notification delivery; runbook §1 |
| `ResumeCheckpointSizePressure` | Checkpoint p99 > 80% of the cap, or any `rejected_too_large` | Warning | Reduce agent context or raise the cap deliberately, in both CC and the CH relay guard |
| `ResumeCheckpointStorageGrowth` | Stored bytes or row count monotonic for 6 h with a flat purge | Warning | Purge step not running — check the reaper loop and its retention sweep; runbook §6 |
| `ResumeReaperStalled` | No `ConversationActivityReaper started` line since startup, or non-terminal working rows keep growing past the staleness bound with no reaper sweep/resolution line for 15 min | Critical | Waiting turns will never terminalise and dead working rows will spin; check the CC background loop; runbook §4 |
| `ResumeWriteAppliedDuplicated` | More than one `applied` line per paused turn within 24 h | Critical | Exactly-once violation in the confirmed-write chokepoint — data-integrity incident; runbook §2 |

### Model-Usage Guardrail Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `GuardrailBreachSurge` | `rate(model_guardrail_breach_total{enforcement_posture="terminate"}) > baseline` for 5 min | Critical | Expect execution blocks; check operator posture intent and model usage |
| `ObserveOnlyGuardrailAlertSurge` | `rate(model_guardrail_breach_total{enforcement_posture="observe_only"}) > baseline` for 5 min | Warning | Review observe-only threshold alerts in execution logs |
| `ModelDisabledSurge` | `rate(model_disabled_block_total{disabled_reason="model_disabled"}) > baseline` for 5 min | Warning | Verify operator-driven disables; expect execution blocks |
| `VendorDisabledSurge` | `rate(model_disabled_block_total{disabled_reason="vendor_cascaded"}) > baseline` for 5 min | Warning | Verify vendor disable; check cascade transaction completed |
| `ApproachingLimitSurge` | `rate(model_usage_posture_transitions_total{to_state="approaching_limit"}) > baseline` for 10 min | Warning | Notify FinOps / Platform Governance Lead before breach |
| `RuntimeTopologyPollingFailure` | `rate(runtime_topology_polling_requests_total{status=~"5.."}) > 0` for 2 min | Warning | Verify topology endpoint health; check operator permission |
| `RuntimeTerminateCascadeIncomplete` | `rate(runtime_termination_requests_total{outcome="cascade_incomplete"}) > 0` for 2 min | Critical | Follow [runbooks/agent-execution-guardrails.md](runbooks/agent-execution-guardrails.md) operator termination triage |
| `RecursionValidationFailureSurge` | `rate(recursion_validation_total{result="fail"}) > baseline` for 5 min | Warning | Follow recursion triage in [runbooks/agent-execution-guardrails.md](runbooks/agent-execution-guardrails.md) section 1 |

### Integration Gateway Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `IntegrationRateLimitedSpike` | `rate(integration.request_total{outcome="rate_limited"})` sustained above baseline for 10 min | Warning | Identify the tripping client; raise its rate limit or split load across clients (see [runbooks/third-party-agent-integration.md](runbooks/third-party-agent-integration.md)) |
| `IntegrationCredentialRejections` | `rate(integration.request_total{outcome=~"invalid_credential|revoked_credential"}) > 0` for 10 min | Warning | Stale/rotated consumer credential or probing attempt; verify consumer holds the current credential |
| `IntegrationErrorRateHigh` | `error` outcome > 5% per client for 5 min | Warning | Inspect CH/AR logs for the affected client and agent type; correlate with guardrail/timeout metrics |
| `IntegrationPublicExposureGrowth` | publishable-client exposure count increases unexpectedly | Warning | Audit newly created publishable clients; confirm intentional public exposure |

### Notification Service Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `NotificationChannelFailureSpike` | `rate(notification_sent_total{status="failed"}) / rate(notification_sent_total) > 0.10` for 5 min | Warning | Check individual channel logs; test connectivity to external provider |
| `NotificationDeliveryLatencyHigh` | `notification_delivery_duration_seconds{quantile="0.99"} > 10` for 5 min | Warning | Identify slow channel type; check provider rate limits or network latency |
| `NotificationChannelDown` | `notification_channel_health == 0` for 10 min | Critical | Channel consistently failing; check channel credentials and external provider status |
| `NotificationRetryStorm` | `rate(notification_retry_total) > 50/min` for 5 min | Warning | High retry rate across channels; check provider availability and backoff configuration |

---

### OIDC Identity Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `OIDCProviderUnreachable` | `oidc.provider.reachability == 0` for 5 min | Critical | OIDC login is broken for affected provider; check network, DNS, and provider health |
| `OIDCJWKSFetchFailureSustained` | `rate(oidc.jwks.fetch_failures_total) > 0` for 2 min | Critical | All JWT validation is failing; JWT signatures cannot be verified |
| `OIDCJWKSCacheDegraded` | `oidc.jwks.cache_hit_rate < 0.90` for 10 min | Warning | Excessive JWKS key rotation or undersized cache TTL |
| `OIDCRegistryReloadError` | `rate(oidc.registry.reload_errors_total) > 0` for 2 min | Critical | Registry reload failed; OIDC config is stale and provider changes are not reflected |
| `AuthPipelineOIDCLatencyHigh` | `auth.pipeline.latency` p99 > 5 s for `oidc_user` or `oidc_agent` tier for 5 min | Warning | OIDC provider or network is slow; user login experience degraded |
| `OIDCTestFailureSustained` | `rate(oidc.config.test_failure_total) > 0` for 10 min | Warning | Operator repeatedly unable to validate OIDC connectivity; check provider configuration |
| `OIDCSecretEncryptionError` | `rate(oidc.config.secret_encryption_errors_total) > 0` | Critical | Client secret encryption/decryption failing; OIDC authentication may not function |

### Super Admin Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `SuperAdminBruteForce` | `rate(superadmin.login_failures_total) > 10/min` for 5 min | Critical | Potential brute-force attack on super admin credentials; consider disabling super admin or rotating credentials |
| `SuperAdminDisabledLoginAttempt` | `rate(superadmin.login_failures_total{reason="disabled"}) > 0` for 5 min | Warning | Login attempts to a disabled super admin; may indicate misconfiguration or unauthorized access attempt |

### MCP Demo App Alerts

Metrics are emitted via OpenTelemetry; panels live in the **MCP Demo App** panel group on the MCP Hub Grafana dashboard.

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|---------|
| `MCPDemoRegistrationFailed` | `mcp_demo.startup.registration_success == 0` at startup | Critical | Check Hub connectivity and API key; see Hub registration runbook |
| `MCPDemoJWTValidationFailures` | `rate(mcp_demo.auth.jwt_validation_failures_total) > 0` for 5 min | Warning | Verify calling agent is using `ai_agents` realm tokens; check JWKS cache |
| `MCPDemoKeycloakTokenFailure` | `rate(mcp_demo.auth.token_refresh_failures_total) > 0` for 2 min | Critical | Verify Keycloak `ai_agents` realm is reachable; check client secret rotation |
| `MCPDemoHighToolErrorRate` | Tool call error rate > 10% for 5 min | Warning | Inspect tool invocation logs; correlate with JWT validation failures |

### Passthrough Session Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `PassthroughJWTValidationFailureSpike` | JWT validation failures > 10% over 5 minutes | Critical | Check Keycloak JWKS endpoint availability; see [passthrough-session.md](runbooks/passthrough-session.md) |
| `PassthroughSessionCreationFailures` | Session creation failures > 20/hour | Warning | Check database constraints and backend logs; verify `auth_type = 'passthrough'` enum migration is applied |
| `PassthroughHighToolLatency` | Passthrough tool call latency p99 > 5 s | Warning | Check MCP server performance and network latency to upstream MCP server |
| `PassthroughJWKSCacheDegraded` | JWKS cache hit rate < 80% over 10 min | Warning | Review JWKS cache TTL configuration in `backend/app/services/oidc_provider_registry.py` |
| `PassthroughSessionCreationRateAnomaly` | New passthrough sessions > 100/hour | Warning | Review session creation logs for potential abuse patterns |

### API Key Access Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `ApiKeyAuthFailureSpike` | `rate(api_key.auth_failure_total) > 10/min` for 5 min | Warning | Check key validity and CH → CC connectivity; review `failure_reason` breakdown |
| `ApiKeyAuthFailureSustained` | `rate(api_key.auth_failure_total) > 50/min` for 2 min | Critical | Possible brute-force attack; consider temporary IP-level rate limiting |
| `RevokedKeyAttemptDetected` | `rate(api_key.revoked_key_attempt_total) > 0` sustained for 5 min | Warning | Investigate source IP and key prefix; may indicate compromised key or misconfigured agent; see [api-key-auth.md](runbooks/api-key-auth.md) |
| `ApiKeyAuthLatencyHigh` | `api_key.auth_latency_seconds` p99 > 2 s for 5 min | Warning | Check CC database query performance; verify `api_keys` table indexes |
| `ApiKeyLoadSkillsEmpty` | `api_key.load_skills_skill_count` p50 = 0 sustained for 10 min | Warning | Load skills returning empty for most callers; verify role-to-skill assignments |
| `ApiKeyPermissionDenialSpike` | `rate(api_key.tool_call_total{outcome="permission_denied"}) > 5/min` for 5 min | Warning | Tools requested outside bound role permissions; review agent configuration |

### Certificate Security Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `CACertificateExpirySoon` | CA certificate expires within 6 months | Warning | Begin CA rotation planning; check `GET /api/v1/certificates/ca` `expires_at` field |
| `AgentCertRenewalFailure` | `cert.renewal_failed` ERROR log present | Critical | Certificate will expire without intervention; re-provision immediately; see [certificate-security.md](runbooks/certificate-security.md) |
| `AgentCertExpired` | `cert.validation.failed` WARN with `outcome = expired` sustained | Critical | Agent runtime shutting down; manually issue replacement certificate; see [certificate-security.md](runbooks/certificate-security.md) |
| `AgentIdentityRefreshFailed` | Count of `agent_identities.token_status = 'refresh_failed'` > 0 | Critical | Agent identity requires manual re-authorization via Admin UI → Agent Identities; see [certificate-security.md](runbooks/certificate-security.md) |

### Startup Validation and Configuration Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `StartupValidationFailed` | `startup.validation.*_failed` log event present | Critical | Page on-call; service cannot start; check the specific dependency in the log event |
| `ConfigurationFromDefault` | Any `resolved from built-in default` log event in production | Warning | Operator review: ensure all production infrastructure env vars are set |
| `KeycloakConfigNotFound` | `startup.validation.keycloak_not_found` log event present | Critical | Operator must run `setup identity` or verify OIDC environment variables |
| `KeycloakAdminCredsInRuntime` | `KEYCLOAK_ADMIN` detected in CC environment at startup | Critical | Security violation: admin credentials exposed to runtime; remove immediately |
| `ServiceRestartLoop` | Any service restarts > 3 times in 10 minutes | Critical | Page on-call; intermittent infrastructure connectivity likely |
