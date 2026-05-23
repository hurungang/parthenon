# Services — Master Inventory

All containers and pods that make up a complete Parthenon deployment. Update this file whenever a service is added, removed, or renamed.

This inventory applies to both deployment targets:
- **Docker Compose** (self-hosted / development): container names match the `Container / Pod Name` column
- **Kubernetes / Helm** (production): pod names are derived from the Helm release name and the service name using the `_helpers.tpl` `fullname` helper

---

## Service Inventory

| Service | Container / Pod Name | Role |
|---------|----------------------|------|
| API Gateway | `nginx` | Reverse proxy routing all inbound HTTP and WebSocket traffic to Control Center and Communication Hub; TLS termination in production |
| Control Center | `control-center` | Sole owner of the PostgreSQL database. Hosts the Platform REST API (identity, MCP Hub, skills, agents, scheduling, notifications, conversations, results), acts as Certificate Authority (issues X.509 certs to Agent Runtime and Communication Hub), manages identity tokens, and triggers execution and message dispatch on peer services. |
| Agent Runtime | `agent-runtime` | Stateless LangChain executor. Receives execution triggers from Control Center over mTLS. Fetches all agent context (plan, skills, model config) from Control Center data APIs. Executes the observe-reason-act loop. Posts results back to Control Center. No direct database access. |
| Communication Hub | `communication-hub` | Message broker and agent gateway. Accepts Web UI WebSocket connections authenticated by JWT. Receives message dispatch commands from Control Center over mTLS. Validates agent certificates and resolves identity per tool call via Control Center. Routes all tool calls using the unified `server____tool` convention — `system____*` to internal handlers, `<server>____*` to MCP Hub. No direct database access. |
| Keycloak | `parthenon-keycloak` | Bundled OpenID Connect identity provider; manages the `parthenon` realm (human users) and `ai_agents` realm (agent identities); Admin REST API used during provisioning. Only deployed when `IDENTITY_PROVIDER_TYPE=keycloak_bundled`. |
| Web UI | `web-ui` | React/Vite SPA providing admin configuration modules, real-time operations dashboards, observability panels, and user-to-agent chat |
| OTEL Collector | `otel-collector` | Receives OTLP telemetry (traces, metrics, logs) from all services; fans out to Prometheus, Jaeger, and Loki backends |
| PostgreSQL | `postgres` | Primary relational data store — accessed only by Control Center |
| Redis | `redis` | In-memory data store for Control Center cache/pubsub, Communication Hub session context, and Agent Session Queue |
| MCP Demo App | `parthenon-mcp-demo-app` | Standalone MCP server demonstrating end-to-end agent identity propagation; authenticates with the `ai_agents` realm; registers with the MCP Hub under slug `demo`; exposes the `helloWorld` tool |

---

## Data Access Boundaries

| Service | Database | Redis |
|---------|----------|-------|
| **Control Center** | Direct read/write (sole owner) | Read/write (cache, pubsub) |
| **Agent Runtime** | None — all data via Control Center APIs | None |
| **Communication Hub** | None — all data via Control Center APIs | Read/write (session context, pubsub) |

---

## Control Center Internal API Boundary Model

The Control Center internal API is caller-scoped and deny-by-default. Access is granted only when all of the following are true:
- caller certificate is valid and maps to a known service identity
- caller type matches policy (`agent_runtime` or `communication_hub`)
- route and method are explicitly allowlisted for that caller type

### Caller-specific deployment notes

| Caller Type | Allowed Internal API Surface | Explicitly Disallowed |
|-------------|------------------------------|-----------------------|
| Agent Runtime | Runtime-essential certificate lifecycle and execution support endpoints required to run agent sessions | Communication Hub-only internal routes, administrative policy routes, and any endpoint not explicitly in the Agent Runtime allowlist |
| Communication Hub | Hub-essential certificate validation, token-resolution support, and routing support endpoints required for message and tool-call brokering | Agent Runtime-only internal routes, administrative policy routes, and any endpoint not explicitly in the Communication Hub allowlist |

### Service boundary guarantees

- Agent Runtime and Communication Hub never receive database credentials or direct database routes.
- Caller-specific policy ownership remains in Control Center and is versioned for audit and rollback.
- Unknown caller types, missing caller identity, and certificate mismatches are denied by default.

---

## Service Dependencies

```
postgres ──┐
           ├──► keycloak (bundled only)
redis ─────┤         │
           │         ▼
           └──► control-center ──┬──► agent-runtime
                                 └──► communication-hub

agent-runtime ──────────────────────► communication-hub (tool calls)

nginx ◄──── control-center, communication-hub
web-ui ◄──── nginx
otel-collector ◄──── (all services emit OTLP)
```

All services depend on `postgres` and `redis` being healthy. When `IDENTITY_PROVIDER_TYPE=keycloak_bundled`, Control Center also depends on `keycloak`. Agent Runtime and Communication Hub bootstrap by requesting certificates from Control Center — Control Center must be healthy before they start. `nginx` must be deployed after all backend services are healthy. `mcp-demo-app` depends on `keycloak` (healthy) and `control-center` (healthy).
