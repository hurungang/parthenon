# Service Decomposition — Deployment Notes

## Environment Variables

### Control Center

**Required (existing)**:
- `DATABASE_URL` — PostgreSQL connection string
- `REDIS_URL` — Redis connection string for caching
- `OIDC_AUTHORITY` — Identity provider authority URL
- `OIDC_CLIENT_ID` — Platform API client ID
- `OIDC_CLIENT_SECRET` — Platform API client secret
- `TELEMETRY_*` — OpenTelemetry configuration (existing pattern)

**New**:
- `AGENT_RUNTIME_URL` — Agent Runtime service base URL (e.g., `http://agent-runtime:8001`)
- `COMMUNICATION_HUB_URL` — Communication Hub service base URL (e.g., `http://communication-hub:8002`)
- `SERVICE_CERT_VALIDITY_DAYS` — Service certificate validity period (default: 30)
- `AGENT_INSTANCE_CERT_VALIDITY_HOURS` — Agent-instance certificate validity period (default: 24)
- `AGENT_RUNTIME_BOOTSTRAP_KEY` — Unique bootstrap secret for Agent Runtime (random, min 32 chars)
- `COMM_HUB_BOOTSTRAP_KEY` — Unique bootstrap secret for Communication Hub (random, min 32 chars)

### Agent Runtime

**Required (existing)**:
- `LLM_PROVIDER_API_KEYS` — LLM provider API keys (OpenAI, Anthropic, etc.)
- `TELEMETRY_*` — OpenTelemetry configuration

**New**:
- `CONTROL_CENTER_URL` — Control Center service base URL (e.g., `http://control-center:8000`)
- `SERVICE_IDENTITY` — Agent Runtime service identity for certificate bootstrap (default: `agent-runtime`)
- `SERVICE_BOOTSTRAP_KEY` — Bootstrap secret for authenticating to Control Center (must match `AGENT_RUNTIME_BOOTSTRAP_KEY` in Control Center)
- `CERT_RENEWAL_THRESHOLD_HOURS` — Hours before expiry to trigger renewal (default: 1)

**Removed**:
- `DATABASE_URL` — Agent Runtime no longer accesses database
- `REDIS_URL` — Agent Runtime does not need Redis

### Communication Hub

**Required (existing)**:
- `REDIS_URL` — Redis connection string for pub/sub
- `TELEMETRY_*` — OpenTelemetry configuration

**New**:
- `CONTROL_CENTER_URL` — Control Center service base URL (e.g., `http://control-center:8000`)
- `SERVICE_IDENTITY` — Communication Hub service identity for certificate bootstrap (default: `communication-hub`)
- `SERVICE_BOOTSTRAP_KEY` — Bootstrap secret for authenticating to Control Center (must match `COMM_HUB_BOOTSTRAP_KEY` in Control Center)
- `CERT_RENEWAL_THRESHOLD_HOURS` — Hours before expiry to trigger renewal (default: 1)
- `TOKEN_RESOLUTION_CACHE_TTL_SECONDS` — Permission cache TTL (default: 60)

**Removed**:
- `DATABASE_URL` — Communication Hub no longer accesses database

---

## Infrastructure Changes

### Docker Compose (Development / Self-Hosted)

**Changes to `docker-compose.yml`**:

1. Split `backend` service into three services:
   - `control-center` (port 8000)
   - `agent-runtime` (port 8001)
   - `communication-hub` (port 8002)

2. Add service dependencies:
   - `agent-runtime` depends on `control-center`
   - `communication-hub` depends on `control-center`

3. Add health checks for all three services:
   - Health check URL: `http://localhost:<port>/health`
   - Interval: 10s
   - Timeout: 5s
   - Retries: 3

4. Update nginx reverse proxy configuration:
   - Route `/api/v1/*` → `control-center:8000`
   - Route `/ws/*` → `communication-hub:8002`
   - Route `/internal/*` → `control-center:8000` (internal only, not exposed to public)

5. Network configuration:
   - All three services on same internal network
   - Only nginx exposed on host ports (80/443)

**Example snippet**:
```yaml
services:
  control-center:
    image: parthenon-control-center:latest
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - AGENT_RUNTIME_URL=http://agent-runtime:8001
      - COMMUNICATION_HUB_URL=http://communication-hub:8002
      - AGENT_RUNTIME_BOOTSTRAP_KEY=${AGENT_RUNTIME_BOOTSTRAP_KEY}
      - COMM_HUB_BOOTSTRAP_KEY=${COMM_HUB_BOOTSTRAP_KEY}
    depends_on:
      - postgres
      - redis
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 3

  agent-runtime:
    image: parthenon-agent-runtime:latest
    environment:
      - CONTROL_CENTER_URL=http://control-center:8000
      - SERVICE_BOOTSTRAP_KEY=${AGENT_RUNTIME_BOOTSTRAP_KEY}
    depends_on:
      - control-center
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 10s
      timeout: 5s
      retries: 3

  communication-hub:
    image: parthenon-communication-hub:latest
    environment:
      - CONTROL_CENTER_URL=http://control-center:8000
      - SERVICE_BOOTSTRAP_KEY=${COMM_HUB_BOOTSTRAP_KEY}
      - REDIS_URL=${REDIS_URL}
    depends_on:
      - control-center
      - redis
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8002/health"]
      interval: 10s
      timeout: 5s
      retries: 3
```

### Kubernetes / Helm (Production)

**Changes to Helm charts** (`infra/helm/parthenon/`):

1. Create three separate Deployment manifests:
   - `templates/control-center-deployment.yaml`
   - `templates/agent-runtime-deployment.yaml`
   - `templates/communication-hub-deployment.yaml`

2. Create three separate Service manifests:
   - `templates/control-center-service.yaml` (ClusterIP, port 8000)
   - `templates/agent-runtime-service.yaml` (ClusterIP, port 8001)
   - `templates/communication-hub-service.yaml` (ClusterIP, port 8002)

3. Update Ingress manifest:
   - Route `/api/v1/*` → `control-center-service:8000`
   - Route `/ws/*` → `communication-hub-service:8002`

4. Add Pod Disruption Budgets for each service:
   - Control Center: minAvailable 1 (critical service)
   - Agent Runtime: minAvailable 50% (scalable)
   - Communication Hub: minAvailable 1 (WebSocket state)

5. Add HorizontalPodAutoscaler for scalable services:
   - Agent Runtime: scale based on CPU (target 70%)
   - Communication Hub: scale based on active WebSocket connections

6. Update resource requests/limits:
   - Control Center: 1 CPU, 2 Gi memory (database queries)
   - Agent Runtime: 2 CPU, 4 Gi memory (LLM calls)
   - Communication Hub: 0.5 CPU, 1 Gi memory (message routing)

7. Add init containers to verify Control Center availability:
   - Agent Runtime and Communication Hub wait for Control Center `/health` before starting

---

## Migration Steps

### Pre-Deployment Checklist
- [ ] Backup PostgreSQL database
- [ ] Review and update environment variables for all three services
- [ ] Build and tag Docker images for all three services
- [ ] Update nginx or Ingress configuration for new routing rules
- [ ] Verify certificate authority is initialized in Control Center (existing CA can be reused)

### Deployment Sequence

**Step 1: Deploy Control Center**
1. Deploy Control Center service with updated environment variables
2. Wait for health check to pass
3. Verify database migrations applied: `kubectl exec control-center-pod -- alembic current`
4. Verify certificate authority is initialized: check logs for "CA initialized"

**Step 2: Deploy Agent Runtime**
1. Deploy Agent Runtime service
2. Verify bootstrap succeeds: check logs for "certificate loaded"
3. Verify health check passes
4. Test agent execution: trigger a simple agent via Web UI

**Step 3: Deploy Communication Hub**
1. Deploy Communication Hub service
2. Verify bootstrap succeeds: check logs for "certificate loaded"
3. Verify health check passes
4. Test WebSocket connection: open Web UI and verify connection established

**Step 4: Update API Gateway / Ingress**
1. Update nginx or Ingress routing rules
2. Reload nginx configuration or apply Ingress changes
3. Verify routing: `curl https://<domain>/api/v1/health` should reach Control Center

**Step 5: Verify Full Workflow**
1. Log in to Web UI
2. Create agent session
3. Send message to agent
4. Verify agent executes and returns result
5. Check logs in all three services for correct flow

### Downtime Considerations

**Docker Compose (Development / Self-Hosted)**:
- Expected downtime: ~30 seconds (stop monolith, start three services)
- WebSocket connections will be dropped and must reconnect

**Kubernetes (Production)**:
- Zero-downtime deployment possible with rolling updates
- Deploy Control Center first with backward-compatible changes
- Deploy Agent Runtime and Communication Hub in parallel
- Update Ingress last to route to new services
- Old monolith pods can coexist briefly during transition

---

## Rollback Procedure

### Docker Compose
1. Stop all three services: `docker-compose stop control-center agent-runtime communication-hub`
2. Start monolithic backend: `docker-compose up -d backend` (using previous image tag)
3. Revert nginx configuration to route all traffic to monolith
4. Verify monolith health check passes
5. Test agent execution via Web UI

### Kubernetes
1. Revert Helm chart to previous version: `helm rollback parthenon <previous-revision>`
2. Verify monolith pods are running: `kubectl get pods`
3. Verify Ingress routes to monolith: `kubectl describe ingress parthenon`
4. Test agent execution via Web UI
5. Investigate rollback reason and address before re-attempting deployment

### Rollback Triggers
- Any service fails health checks after 5 minutes
- Agent execution fails with "service unavailable" errors
- WebSocket connections fail to establish
- Certificate bootstrap fails repeatedly
- Database connection errors in logs (should only be Control Center)

---

## Master Deployment Update Instructions

### Update `docs/master/deployment/README.md`
- Replace single backend deployment section with three-service deployment architecture
- Add section "Service Decomposition Overview" with diagram showing Control Center, Agent Runtime, Communication Hub
- Update environment variable tables to show service-specific variables
- Add section "Service Startup Order" explaining dependency chain

### Update `docs/master/deployment/docker-compose.md`
- Replace monolithic backend service definition with three-service definitions
- Add health check configuration for all three services
- Update nginx routing configuration examples
- Add troubleshooting section for certificate bootstrap failures

### Update `docs/master/deployment/kubernetes.md`
- Replace single backend Deployment with three Deployment manifests
- Add Service definitions for all three services
- Update Ingress configuration examples
- Add HorizontalPodAutoscaler and Pod Disruption Budget examples
- Add init container examples for service dependency management

### Create `docs/master/deployment/certificate-management.md` (new file)
- Document certificate lifecycle: bootstrap, renewal, revocation
- Explain certificate types: agent-instance (24 h), service (30 d)
- Document certificate validation process
- Add troubleshooting guide for certificate issues
- Document certificate rotation procedures

### Update `docs/master/deployment/environment-variables.md`
- Split environment variables by service (Control Center, Agent Runtime, Communication Hub)
- Mark removed variables (DATABASE_URL from Agent Runtime and Communication Hub)
- Add new variables (CONTROL_CENTER_URL, service identity, certificate validity, per-service bootstrap keys)
- Add validation rules for each variable (bootstrap keys must be min 32 chars, cryptographically random)
- Document bootstrap key security: never commit to git, use secrets management (K8s Secrets, Docker Secrets, Vault)
