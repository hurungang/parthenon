# Operations Documentation — Parthenon Enterprise AI Harness

This section contains all operational reference material for running and maintaining a deployed Parthenon instance. It covers monitoring, logging, and step-by-step runbooks for the most common operational issues.

---

## Quick Reference

- **Setup-time vs. runtime credentials**: `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` must be set for the setup tool only — **never** on the Control Center service at runtime. If these variables are detected on the CC service, a `config.keycloak_admin_detected_in_runtime` WARNING is logged and the credentials are ignored.
- All infrastructure bootstrap operations (realm creation, DB seeding, certificate issuance) are performed via the consolidated `setup` command, which is idempotent and safe to run repeatedly.
- Startup validation runs on every service restart; if a service fails to start, check the startup validation log events to identify which dependency is unreachable.

---

## Dashboards

| Dashboard | Purpose |
|-----------|---------|
| **Platform Overview** | One-glance system health: HTTP error rate, active agent instances, active WebSocket connections, scheduler queue depth |
| **Agent Engine** | Instance count per agent type, creation and destruction rate, response latency histogram |
| **MCP Hub** | Tool call rate heatmap by tool and session, error rate, latency p99 |
| **MCP Hub — Passthrough Sessions** | Active passthrough session count, passthrough tool call rate and success rate, JWT extraction rate, JWKS cache hit rate, passthrough tool latency p99 |
| **API Key Access** | API key auth rate by action/outcome, failure breakdown, revoked key attempts, auth latency, load_skills call rate and response size, tool call volume (API key vs certificate) |
| **MCP Demo App** | Tool call rate, JWT validation failures, startup registration status, JWKS/token refresh failures |
| **Scheduling Engine** | Triggered vs. completed job counts over time, scheduler queue depth trend |
| **Infrastructure** | PostgreSQL connection count and query latency, Redis memory and eviction rate, OTEL Collector throughput |
| **Agent Runtime** | Session queue depth, session throughput and failure rate, dispatch latency, active runtime sessions, execution duration, LangGraph node transitions, permission cache hit rate, permission denials |
| **Agent Execution Guardrails** | Guardrail stop trends by reason, cycle blocks, iteration/timeout/delegation budget pressure, conversational token visibility, token fallback activation, terminal stop-category integrity |
| **OIDC Provider Health** | Per-provider reachability gauges, OIDC Discovery latency p99, JWKS cache hit rate, JWKS fetch failure rate, registry reload event count |
| **Super Admin & Auth Pipeline** | Auth pipeline tier distribution (super_admin, oidc_user, oidc_agent, public), super admin login success/failure rate, OIDC JWT validation failures by reason, auth pipeline latency per tier |
| **Service Segregation Boundary Enforcement** | Allowed vs denied internal calls by caller type, top deny reasons, unknown caller and certificate mismatch trends, revocation health, internal auth latency, and system-tools unauthenticated rejects |

For metric definitions and alert thresholds, see [monitoring.md](monitoring.md).

Agent execution guardrail metrics and alerts are defined in [monitoring.md](monitoring.md) under Agent Execution Guardrails.

Boundary policy metrics and alerts for internal caller segregation are defined in [monitoring.md](monitoring.md) under Service Segregation Boundary Enforcement.

---

## Log Sources

| Source | Access Method |
|--------|---------------|
| Container stdout/stderr (Docker Compose) | `docker compose logs <service>` or via Loki |
| Pod logs (Kubernetes) | `kubectl logs <pod-name>` or via Loki |
| Loki (aggregated) | Query via LogQL in Grafana or Loki API; all services ship structured logs via OTEL Collector |
| Jaeger (distributed traces) | Use `trace_id` from a log line to jump to the correlated trace in Jaeger UI |

For structured log fields and per-component event reference, see [logging.md](logging.md).

Agent execution guardrail event taxonomy, required fields, and sensitive-data exclusions are defined in [logging.md](logging.md) under Agent Execution Guardrail Events.

Boundary event catalog and required fields for allowlist enforcement are defined in [logging.md](logging.md) under Internal API Boundary Log Events.

---

## Production Health Check Targets

The following endpoints must be included in production readiness checklists and uptime monitoring:

| Target | URL | Expected Response |
|--------|-----|-------------------|
| Platform API | `http://<backend-host>:8000/health` | `200 OK` |
| OTEL Collector | `http://otel-collector:13133/` | `200 OK` — any non-200 means telemetry data is being dropped |
| MCP Demo App | `http://mcp-demo-app:9000/health` | `{"status": "ok", "slug": "demo"}` with HTTP 200 |
| Certificate Authority | `http://<backend-host>:8000/api/v1/certificates/ca` | `200 OK` with `expires_at` field — any non-200 means CA is not initialized |
| Control Center health | `http://<cc-host>:8000/health` | `200 OK` — must be healthy before AR and CH can validate against it |
| Agent Runtime health | `http://<ar-host>:8001/health` | `200 OK` — only after CC is healthy |
| Communication Hub health | `http://<ch-host>:8002/health` | `200 OK` — only after CC and Redis are healthy |

---

## Setup Tool

The consolidated `setup` command bootstraps all infrastructure dependencies before any service is started. It is idempotent — safe to run repeatedly on an already-provisioned environment.

### Running the Setup Tool

```bash
# Identity provider (Keycloak realm, clients, admin user)
setup identity

# Database schema verification and default data seeding
setup database

# Certificate authority bootstrapping
setup certificates

# Development environment (combines all of the above)
setup dev

# Verify all components are in expected state
setup verify
```

The setup tool uses its own environment variables for Keycloak administration (`KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD`), which must not be set on the runtime services. All sub-commands are idempotent — running `setup identity` on an already-provisioned realm will log `setup.identity.realm_exists` and skip creation.

### Expected Output

Each operation logs structured events to stdout (see [logging.md](logging.md) for the full event reference). On success, `setup verify` emits `setup.verify.all_ok`. On partial failure, it emits `setup.verify.issues_found` with a list of specific issues.

---

## Runbooks

| Runbook | Trigger Symptoms |
|---------|-----------------|
| [oidc-token-failure.md](runbooks/oidc-token-failure.md) | All API endpoints return 401; logs show `JWT validation error` or `JWKS fetch failed` |
| [mcp-credential-error.md](runbooks/mcp-credential-error.md) | MCP tool calls fail with auth errors; logs show `credential decryption failed` or `session not found` |
| [passthrough-session.md](runbooks/passthrough-session.md) | Passthrough tool calls fail with 401; logs show `No agent JWT available for passthrough session`; JWT validation failure alert firing; agent identity list empty |
| [agent-instance-limit.md](runbooks/agent-instance-limit.md) | New requests rejected with 429; logs show `max_instances reached for agent_type_id=<id>` |
| [scheduling-job-stuck.md](runbooks/scheduling-job-stuck.md) | Scheduled job triggered but never completes; scheduler queue depth growing |
| [communication-hub-disconnect.md](runbooks/communication-hub-disconnect.md) | Web UI shows disconnected state; agent responses stop; repeated `WebSocket disconnect` in logs |
| [telemetry.md](runbooks/telemetry.md) | Telemetry init failure at startup; no spans in Jaeger; frontend OTEL not initialising; file exporter disk pressure; Logfire or custom exporter credential errors; log level not applying |
| [agent-runtime.md](runbooks/agent-runtime.md) | Resolving stuck sessions, permission failures, OAuth expiry, timeouts, and queue backlogs in the Agent Runtime with LangGraph |
| [agent-execution-guardrails.md](runbooks/agent-execution-guardrails.md) | Triage for cycle blocks, iteration/timeout/delegation budget stops, conversational token continuation behavior, token fallback activation, and stop metadata integrity |
| [certificate-security.md](runbooks/certificate-security.md) | CA initialization failures, certificate expiry and renewal failures, certificate compromise response, agent identity token refresh failures, and token leakage investigation |
| [api-key-auth.md](runbooks/api-key-auth.md) | External agents receive auth errors after key provisioning; `api_key.auth_failed` WARN entries in CH logs; `ApiKeyAuthFailureSpike` alert firing; revoked key still works; `load_skills` returns empty; identity token refresh failures cause proxy errors |
| [service-segregation-boundary-enforcement.md](runbooks/service-segregation-boundary-enforcement.md) | Internal API deny spikes, unknown caller denials, certificate mismatch denials, allowlist contract drift, and revocation check failures |
| [super-admin-lockout.md](runbooks/super-admin-lockout.md) | Cannot log in with super admin; OIDC also unavailable; need emergency access |
| [setup-tool.md](runbooks/setup-tool.md) | CC fails to start with Keycloak config not found; Keycloak admin credentials detected in runtime log; setup command fails with Keycloak admin API unreachable |
| [startup-validation-failure.md](runbooks/startup-validation-failure.md) | Any service fails to start with a `startup.validation.*_failed` log event; service restart loop detected |

For boundary incidents that involve certificate class or identity problems, use [service-segregation-boundary-enforcement.md](runbooks/service-segregation-boundary-enforcement.md) for initial triage and [certificate-security.md](runbooks/certificate-security.md) for certificate lifecycle remediation.
