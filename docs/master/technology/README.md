# Technology Documentation — Parthenon Enterprise AI Harness

This section contains per-module technology specifications for every backend, frontend, and infrastructure component in the Parthenon platform. Each module spec provides an overview, key components, API endpoints (where applicable), and a Code Reference Map for developer navigation.

---

## Modules

| Module | Description |
|--------|-------------|
| [foundation](modules/foundation/tech-spec.md) | Core infrastructure: application settings, async database session, OIDC JWT validation, auth middleware, AES-256 credential vault, and OpenTelemetry setup |
| [identity](modules/identity/tech-spec.md) | RBAC layer (Roles, Permissions, Identities); identity provider bootstrap for bundled Keycloak, external Keycloak, and Azure EntraID; setup wizard and first-run redirect guard |
| [mcp-hub](modules/mcp-hub/tech-spec.md) | External MCP server registration, tool catalogue sync under slug namespaces, encrypted session management, and tool-call proxy engine |
| [skills](modules/skills/tech-spec.md) | Skill and SOP definition management; Skill Executor for MCP tool invocation; SOP Orchestrator for ordered multi-step execution |
| [agents](modules/agents/tech-spec.md) | Agent type definitions, instance lifecycle management with max-instance enforcement, LLM model binding, and SOP/Skillful agent executors |
| [gateway](modules/gateway/tech-spec.md) | External-facing agent lifecycle protocol (init/request/question/answer/close) over HTTP and MCP transports; endpoint registry |
| [comm-hub](modules/comm-hub/tech-spec.md) | Redis-backed message broker, WebSocket server bridging browser clients, inter-agent routing, and session context management |
| [scheduling](modules/scheduling/tech-spec.md) | APScheduler cron engine with PostgreSQL job store; scheduled job CRUD, pause/resume, and execution history |
| [conversations](modules/conversations/tech-spec.md) | Persistent conversation session, turn, and tool call record store for complete audit trails and replay |
| [results](modules/results/tech-spec.md) | Structured agent and SOP result persistence; `save_result` MCP tool registration and result query endpoints |
| [notifications](modules/notifications/tech-spec.md) | Outbound notification dispatcher for email, Slack, Teams, and webhook channels; channel-as-MCP-tool registration and event history |
| [observability](modules/observability/tech-spec.md) | OTEL telemetry initialisation for backend and frontend; OTEL Collector pipeline configuration; Helm chart for production Kubernetes deployment |

---

## Technology Stack Summary

| Layer | Technologies |
|-------|-------------|
| **Backend** | Python 3.11+, FastAPI, SQLAlchemy 2 (async), Pydantic v2, Alembic, Redis, OpenTelemetry |
| **Frontend** | React 19, TypeScript, Material-UI (MUI 7), React Router 7, Vite, i18next, OpenTelemetry |
| **Database** | PostgreSQL 16 |
| **Auth** | OIDC/OAuth2 (Keycloak, Azure EntraID), JWT validation via python-jose |
| **Infrastructure** | Docker Compose (dev/self-hosted), Kubernetes/Helm (production), nginx, OTEL Collector |

---

## Conventions

- All frontend data access is via REST API through `apiClient` — no direct database access from the browser
- All backend endpoints require JWT bearer authentication unless explicitly marked public
- Database schema is managed via SQLAlchemy declarative models; never write raw DDL — generate Alembic migrations with `alembic revision --autogenerate`
- MCP credentials are encrypted at rest (AES-256) and decrypted only at call time; never logged or returned in responses
- All inter-service communication is instrumented with OpenTelemetry traces, metrics, and structured logs
- All UI text is internationalised via i18next `t()` — no hardcoded strings in components
- **Configuration**: all backend configuration is consumed via `get_settings()` from `backend/app/core/config.py`. The system resolves values in priority order: environment variable → `config/<domain>.yaml` → hard-coded default. New modules add fields to `Settings` and, if file-based config is needed, a `YamlSettingsSource` subclass for their domain YAML file. No module reads env vars, files, or secrets directly. See the [foundation tech-spec](modules/foundation/tech-spec.md#configuration-system) for the full design.
