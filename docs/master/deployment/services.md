# Services — Master Inventory

All containers and pods that make up a complete Parthenon deployment. Update this file whenever a service is added, removed, or renamed.

This inventory applies to both deployment targets:
- **Docker Compose** (self-hosted / development): container names match the `Container / Pod Name` column
- **Kubernetes / Helm** (production): pod names are derived from the Helm release name and the service name using the `_helpers.tpl` `fullname` helper

---

## Service Inventory

| Service | Container / Pod Name | Role |
|---------|----------------------|------|
| API Gateway | `nginx` | Reverse proxy routing all inbound HTTP and WebSocket traffic to the appropriate backend services; TLS termination in production |
| Platform API | `platform-api` | Central FastAPI application hosting all REST endpoints for identity, MCP Hub, skills, agents, scheduling, conversations, results, and notifications; delegates JWT validation to the OIDC provider |
| Keycloak | `parthenon-keycloak` | Bundled OpenID Connect identity provider; manages the Parthenon realm, clients, and user accounts; Admin REST API used by the Bootstrap Service during automated provisioning. Only deployed when `IDENTITY_PROVIDER_TYPE=keycloak_bundled`. |
| Communication Hub | `communication-hub` | Redis-backed WebSocket broker for Web UI ↔ Agent bidirectional messaging and Agent ↔ Agent inter-service messaging |
| Agent Gateway | `agent-gateway` | External-facing lifecycle protocol endpoint (init/request/question/answer/close) for agent interactions over HTTP and MCP transports |
| Agent Engine | `agent-engine` | Agent type registry, instance lifecycle management with max-instance enforcement, LLM model binding, and dispatch to SOP or Skillful executors |
| Skill Engine | `skill-engine` | Skill and SOP resolution; dispatches MCP tool calls via the MCP Hub proxy; orchestrates multi-step SOP execution |
| MCP Hub | `mcp-hub` | External MCP tool server registry, periodic tool catalogue sync, encrypted session credential management, and tool-call proxy |
| Scheduling Engine | `scheduling-engine` | APScheduler-based cron trigger service backed by the PostgreSQL job store; fires agent prompts and SOP runs on schedule |
| Notification Engine | `notification-engine` | Outbound notification dispatcher for email, Slack, Teams, and generic webhook channels; registers each channel as an invocable MCP tool |
| Web UI | `web-ui` | React/Vite SPA providing admin configuration modules, real-time operations dashboards, observability panels, and user-to-agent chat |
| OTEL Collector | `otel-collector` | Receives OTLP telemetry (traces, metrics, logs) from all backend and frontend services; fans out to Prometheus, Jaeger, and Loki backends |
| PostgreSQL | `postgres` | Primary relational data store for all platform configuration, conversation history, result records, scheduled job state, and identity data |
| Redis | `redis` | In-memory data store serving as the cache layer, pub/sub backbone for the Communication Hub, and session context store |

---

## Service Dependencies

```
postgres ──┐
           ├──► keycloak (bundled only)
redis ─────┤         │
           │         ▼
           └──► platform-api ──┬──► mcp-hub
                               ├──► skill-engine
                               ├──► agent-engine
                               ├──► scheduling-engine
                               ├──► notification-engine
                               ├──► communication-hub
                               └──► agent-gateway
                                         │
nginx ◄───────────────────────────────────┘
web-ui ◄──── nginx
otel-collector ◄──── (all services emit OTLP)
```

All backend services depend on `postgres` and `redis` being healthy. When `IDENTITY_PROVIDER_TYPE=keycloak_bundled`, `platform-api` also depends on `keycloak` being healthy before it starts. `platform-api` must be running before the domain services listed above start. `nginx` must be deployed after all backend services are healthy. `web-ui` requires `nginx` (the API Gateway) to be reachable.
