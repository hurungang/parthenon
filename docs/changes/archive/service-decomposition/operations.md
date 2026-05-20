# Service Decomposition — Operations Notes

## Monitoring

### New Metrics

**Control Center**:
- `parthenon_cc_certificate_issued_total` — Counter: Total certificates issued (labels: `service_type` = `agent-instance` | `service`)
- `parthenon_cc_certificate_renewed_total` — Counter: Total certificates renewed
- `parthenon_cc_certificate_revoked_total` — Counter: Total certificates revoked
- `parthenon_cc_certificate_validation_failures_total` — Counter: Failed certificate validations (labels: `reason` = `expired` | `invalid_signature` | `revoked`)
- `parthenon_cc_data_api_requests_total` — Counter: Internal data API requests (labels: `endpoint`, `service`)
- `parthenon_cc_trigger_requests_total` — Counter: Agent Runtime trigger requests (labels: `status` = `success` | `failure`)
- `parthenon_cc_dispatch_requests_total` — Counter: Communication Hub dispatch requests (labels: `status` = `success` | `failure`)
- `parthenon_cc_db_connections_active` — Gauge: Active PostgreSQL connections (should be Control Center only)

**Agent Runtime**:
- `parthenon_ar_certificate_bootstrap_total` — Counter: Bootstrap attempts (labels: `status` = `success` | `failure`)
- `parthenon_ar_certificate_renewal_total` — Counter: Renewal attempts (labels: `status` = `success` | `failure`)
- `parthenon_ar_certificate_expiry_seconds` — Gauge: Seconds until certificate expiry
- `parthenon_ar_control_center_api_requests_total` — Counter: Control Center API calls (labels: `endpoint`, `status`)
- `parthenon_ar_agent_executions_total` — Counter: Agent execution requests (labels: `status` = `success` | `failure`)
- `parthenon_ar_agent_execution_duration_seconds` — Histogram: Agent execution duration

**Communication Hub**:
- `parthenon_ch_certificate_bootstrap_total` — Counter: Bootstrap attempts (labels: `status` = `success` | `failure`)
- `parthenon_ch_certificate_renewal_total` — Counter: Renewal attempts (labels: `status` = `success` | `failure`)
- `parthenon_ch_certificate_expiry_seconds` — Gauge: Seconds until certificate expiry
- `parthenon_ch_control_center_api_requests_total` — Counter: Control Center API calls (labels: `endpoint`, `status`)
- `parthenon_ch_token_resolution_total` — Counter: Token resolution requests (labels: `status` = `success` | `failure`)
- `parthenon_ch_websocket_connections_active` — Gauge: Active WebSocket connections
- `parthenon_ch_message_dispatch_total` — Counter: Message dispatch requests (labels: `status` = `success` | `failure`)

### Alerting Rules

**Critical Alerts**:
- `ControlCenterDown` — Control Center health check fails for 2 minutes (impact: all services unavailable)
- `AgentRuntimeDown` — Agent Runtime health check fails for 2 minutes (impact: no agent execution)
- `CommunicationHubDown` — Communication Hub health check fails for 2 minutes (impact: no WebSocket connections)
- `CertificateBootstrapFailing` — Certificate bootstrap failure rate > 50% over 5 minutes (impact: services cannot authenticate)
- `CertificateRenewalFailing` — Certificate renewal failure rate > 50% over 10 minutes (impact: services will lose authentication)
- `CertificateExpiringSoon` — Certificate expiry < 2 hours (impact: service authentication will fail)
- `UnauthorizedDatabaseAccess` — Database connections from non-Control Center pods (impact: security violation)

**Warning Alerts**:
- `HighControlCenterLatency` — Control Center internal API p95 latency > 500ms (impact: slow agent execution)
- `HighTokenResolutionFailureRate` — Token resolution failure rate > 10% over 5 minutes (impact: some tool calls fail)
- `HighCertificateValidationFailureRate` — Certificate validation failure rate > 5% over 5 minutes (impact: some service calls fail)
- `AgentRuntimeMemoryHigh` — Agent Runtime memory usage > 80% (impact: potential OOM)

### Dashboards

**Service Health Dashboard**:
- Service status (Control Center, Agent Runtime, Communication Hub)
- Health check success rate per service
- Certificate expiry time per service
- Service-to-service request rate and latency

**Certificate Management Dashboard**:
- Certificates issued (count, rate)
- Certificates renewed (count, rate)
- Certificates revoked (count, rate)
- Certificate validation failures (count, rate, breakdown by reason)
- Certificate expiry timeline (time series showing all service cert expiry times)

**Data Access Dashboard**:
- Control Center internal API request rate (per endpoint)
- Control Center internal API latency (p50, p95, p99)
- Agent Runtime → Control Center API calls (rate, latency)
- Communication Hub → Control Center API calls (rate, latency)
- Database connections by service (should be Control Center only)

**Agent Execution Dashboard** (existing, update data sources):
- Agent execution rate
- Agent execution duration (existing)
- Agent execution success rate (existing)
- Agent Runtime service health (new)
- Control Center trigger success rate (new)

---

## Logging

### Structured Log Fields

All services emit OpenTelemetry structured logs with standard fields:

**Common fields** (all services):
- `service.name` — Service name (`control-center`, `agent-runtime`, `communication-hub`)
- `service.version` — Service version (from image tag)
- `trace_id` — OpenTelemetry trace ID
- `span_id` — OpenTelemetry span ID
- `timestamp` — ISO 8601 timestamp

**Certificate-related logs**:
- `certificate.cn` — Certificate Common Name
- `certificate.expiry` — Certificate expiry timestamp
- `certificate.type` — Certificate type (`agent-instance`, `service`)
- `certificate.issuer` — Issuer service (`control-center`)
- `certificate.validation_result` — Validation result (`valid`, `expired`, `invalid_signature`, `revoked`)

**Service-to-service call logs**:
- `http.method` — HTTP method
- `http.url` — Request URL
- `http.status_code` — Response status code
- `http.request_duration_ms` — Request duration in milliseconds
- `client_cert.cn` — Client certificate CN (for inbound calls)
- `upstream_service` — Upstream service name (for outbound calls)

**Token resolution logs**:
- `agent_instance.id` — Agent instance ID
- `agent_instance.cert_cn` — Agent instance certificate CN
- `identity_token.expiry` — Identity token expiry timestamp
- `permissions.tools_allowed` — Count of allowed tools
- `permissions.cache_hit` — Whether permissions were cached

### Log Queries

**Certificate bootstrap failures**:
```
service.name="agent-runtime" OR service.name="communication-hub"
AND message CONTAINS "bootstrap failed"
```

**Certificate validation failures**:
```
service.name="control-center"
AND certificate.validation_result IN ("expired", "invalid_signature", "revoked")
```

**Unauthorized database access attempts** (should never happen):
```
service.name IN ("agent-runtime", "communication-hub")
AND message CONTAINS "database" OR message CONTAINS "sqlalchemy"
```

**Token resolution failures**:
```
service.name="communication-hub"
AND message CONTAINS "token resolution failed"
```

**Service-to-service call failures**:
```
http.status_code >= 500
AND (upstream_service="control-center" OR upstream_service="agent-runtime" OR upstream_service="communication-hub")
```

---

## Common Issues

### Issue: Agent Runtime fails to start with "bootstrap failed"

**Symptoms**: Agent Runtime health check fails; logs show "certificate bootstrap failed"

**Causes**:
- Control Center not reachable at `CONTROL_CENTER_URL`
- Control Center `/internal/bootstrap` endpoint not responding
- Service identity not recognized by Control Center
- Bootstrap key mismatch (Agent Runtime `SERVICE_BOOTSTRAP_KEY` doesn't match Control Center `AGENT_RUNTIME_BOOTSTRAP_KEY`)

**Resolution**:
1. Verify Control Center is running: `curl http://control-center:8000/health`
2. Verify Agent Runtime can reach Control Center: `kubectl exec agent-runtime-pod -- curl http://control-center:8000/health`
3. Check Agent Runtime logs for bootstrap request details
4. Check Control Center logs for bootstrap request and rejection reason (look for "invalid bootstrap key" or "unauthorized service")
5. Verify `SERVICE_IDENTITY` environment variable is correct in Agent Runtime
6. Verify `SERVICE_BOOTSTRAP_KEY` in Agent Runtime matches `AGENT_RUNTIME_BOOTSTRAP_KEY` in Control Center
7. Restart Agent Runtime after Control Center is healthy and keys match

---

### Issue: Communication Hub fails to start with "bootstrap failed"

**Symptoms**: Communication Hub health check fails; logs show "certificate bootstrap failed"

**Causes**: Same as Agent Runtime bootstrap failure

**Resolution**: Same as Agent Runtime bootstrap failure, but check Communication Hub logs and configuration

---

### Issue: Agent execution fails with "503 Service Unavailable"

**Symptoms**: Agent execution triggered from Web UI fails; Communication Hub logs show "Control Center unreachable"

**Causes**:
- Control Center is down or unhealthy
- Control Center internal API endpoints not responding
- Network connectivity issue between Communication Hub and Control Center

**Resolution**:
1. Verify Control Center is running: `curl http://control-center:8000/health`
2. Check Control Center logs for errors
3. Verify Communication Hub can reach Control Center: `kubectl exec comm-hub-pod -- curl http://control-center:8000/health`
4. Check network policies or firewall rules blocking traffic
5. Restart Communication Hub if certificate or connection pool is stale

---

### Issue: "Certificate validation failed: expired"

**Symptoms**: Service-to-service calls fail with 401; logs show "certificate expired"

**Causes**:
- Certificate renewal failed
- Clock skew between services
- Service was offline during renewal window

**Resolution**:
1. Check certificate expiry time in service `/health` endpoint
2. Verify certificate renewal background task is running (check logs)
3. Check Control Center logs for renewal requests and failures
4. Verify clocks are synchronized across all services (NTP)
5. Restart affected service to trigger immediate bootstrap with new certificate

---

### Issue: "Certificate validation failed: revoked"

**Symptoms**: Service-to-service calls fail with 401; logs show "certificate revoked"

**Causes**:
- Certificate was explicitly revoked by administrator
- Service identity was deactivated

**Resolution**:
1. Check Control Center database for revoked certificates: `SELECT * FROM certificates WHERE revoked = true`
2. Verify revocation was intentional (check admin actions)
3. If accidental: un-revoke certificate in database and restart service
4. If intentional: update service identity and restart to get new certificate

---

### Issue: Agent Runtime or Communication Hub accessing database directly

**Symptoms**: PostgreSQL logs show connections from `agent-runtime` or `communication-hub` pods; monitoring alert fires

**Causes**: Code regression — direct database access not fully removed

**Resolution**:
1. Immediately kill unauthorized connections: `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name IN ('agent-runtime', 'communication-hub')`
2. Check affected service code for `AsyncSession`, `get_db`, or SQLAlchemy imports
3. Verify environment variables — `DATABASE_URL` should NOT be set in Agent Runtime or Communication Hub
4. Redeploy affected service with corrected code
5. Add database connection monitoring to prevent regression

---

### Issue: "Permission denied: agent-instance certificate not allowed"

**Symptoms**: Agent Runtime calls to Control Center `/internal/*` endpoints fail with 403

**Causes**:
- Agent Runtime using agent-instance certificate instead of service certificate
- Service identity misconfigured

**Resolution**:
1. Check Agent Runtime certificate CN: should be `service:agent-runtime`, NOT `agent-type:instance-id`
2. Verify `SERVICE_IDENTITY` environment variable is `agent-runtime` (not an agent type)
3. Check Control Center bootstrap endpoint — verify it issues service cert for `agent-runtime` identity
4. Restart Agent Runtime to get correct certificate type

---

### Issue: Token resolution fails in Communication Hub

**Symptoms**: MCP tool calls fail; Communication Hub logs show "token resolution failed"

**Causes**:
- Control Center `/internal/tokens/resolve` endpoint not responding
- Agent-instance certificate invalid or expired
- Network connectivity issue

**Resolution**:
1. Verify Control Center is healthy: `curl http://control-center:8000/health`
2. Check Communication Hub logs for token resolution request details
3. Check Control Center logs for token resolution endpoint errors
4. Verify agent-instance certificate in request is valid (not expired, not revoked)
5. Verify Communication Hub can reach Control Center: `kubectl exec comm-hub-pod -- curl http://control-center:8000/internal/tokens/resolve`

---

### Issue: High Control Center latency

**Symptoms**: Agent execution slow; Control Center internal API p95 latency > 500ms

**Causes**:
- Database query performance degradation
- High request volume from Agent Runtime or Communication Hub
- Resource contention (CPU, memory)

**Resolution**:
1. Check database query performance: analyze slow query log
2. Check Control Center resource usage (CPU, memory)
3. Scale Control Center horizontally (add more replicas)
4. Optimize database indexes for frequently queried tables
5. Implement caching for frequently accessed data (agent plans, permissions)

---

## Runbooks

### Runbook: Certificate Renewal Failure

**Trigger**: `CertificateRenewalFailing` alert fires

**Steps**:
1. Identify affected service from alert labels
2. Check service logs for renewal failure reason
3. Verify Control Center is healthy: `curl http://control-center:8000/health`
4. Verify network connectivity: `kubectl exec <service-pod> -- curl http://control-center:8000/health`
5. Check Control Center logs for renewal request errors
6. If Control Center issue: resolve Control Center problem first
7. If network issue: check network policies and firewall rules
8. Restart affected service to trigger immediate renewal
9. Verify certificate renewed: check `/health` endpoint for new expiry time
10. Monitor for recurring failures

---

### Runbook: Service Bootstrap Failure

**Trigger**: Service health check fails on startup; logs show "bootstrap failed"

**Steps**:
1. Verify Control Center is running and healthy
2. Check service logs for bootstrap request details
3. Check Control Center logs for bootstrap endpoint errors
4. Verify service identity is correct in environment variables
5. Verify network connectivity between service and Control Center
6. If Control Center issue: resolve Control Center problem first
7. If network issue: check DNS resolution and network policies
8. Restart service after resolving underlying issue
9. Verify bootstrap succeeds: check logs for "certificate loaded"
10. Verify health check passes

---

### Runbook: Database Connection from Unauthorized Service

**Trigger**: `UnauthorizedDatabaseAccess` alert fires

**Steps**:
1. Identify unauthorized service from alert labels
2. Immediately kill unauthorized connections: `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name = '<service-name>'`
3. Check affected service code for direct database access
4. Verify `DATABASE_URL` is not set in affected service environment
5. Redeploy affected service with corrected code and configuration
6. Monitor database connections to verify issue resolved
7. Conduct incident post-mortem to identify root cause
8. Update CI/CD pipeline to prevent regression (automated checks)

---

## Master Operations Update Instructions

### Update `docs/master/operations/README.md`
- Add section "Service Decomposition Overview" explaining the three-service architecture
- Update "Monitoring Architecture" to describe metrics from all three services
- Add "Certificate Management" section linking to detailed runbooks

### Create `docs/master/operations/service-health-monitoring.md` (new file)
- Document health check endpoints for all three services
- Explain service dependency chain (Agent Runtime → Control Center, Communication Hub → Control Center)
- Document alert rules for service health
- Add troubleshooting guide for service unavailability

### Create `docs/master/operations/certificate-lifecycle.md` (new file)
- Document certificate types (agent-instance, service)
- Explain certificate lifecycle (bootstrap, renewal, revocation)
- Document certificate monitoring and alerting
- Add runbooks for certificate issues (expiry, renewal failure, validation failure)

### Update `docs/master/operations/alerting.md`
- Add new alert rules for service decomposition (see Alerting Rules section above)
- Update alert severity levels
- Document alert response procedures for new alerts

### Update `docs/master/operations/logging.md`
- Add structured log fields for certificate and service-to-service calls
- Document log queries for service decomposition (see Log Queries section above)
- Add examples of log correlation across three services using trace_id

### Update `docs/master/operations/troubleshooting.md`
- Add "Service Decomposition Issues" section with common issues and resolutions (see Common Issues section above)
- Add cross-service troubleshooting guide (how to trace requests across Control Center → Agent Runtime → Communication Hub)
