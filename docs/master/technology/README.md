# Technology Documentation — Parthenon Enterprise AI Harness

This section contains per-module technology specifications for every backend, frontend, and infrastructure component in the Parthenon platform. Each module spec provides an overview, key components, API endpoints (where applicable), and a Code Reference Map for developer navigation.

---

## Modules

| Module | Description |
|--------|-------------|
| [frontend](modules/frontend/tech-spec.md) | Global MUI theming infrastructure (palette, typography, shadows, component overrides), app bootstrap (ThemeProvider, CssBaseline), and top-level layout shell (AppShell, sidebar, AppBar) |
| [foundation](modules/foundation/tech-spec.md) | Core infrastructure: application settings, async database session, OIDC JWT validation, auth middleware, AES-256 credential vault, and OpenTelemetry setup |
| [identity](modules/identity/tech-spec.md) | RBAC layer (Roles, Permissions, Identities); identity provider bootstrap for bundled Keycloak, external Keycloak, and Azure EntraID; setup wizard and first-run redirect guard |
| [mcp-hub](modules/mcp-hub/tech-spec.md) | External MCP server registration, tool catalogue sync under slug namespaces, encrypted session management with explicit default-session selection, and tool-call proxy engine |
| [skills](modules/skills/tech-spec.md) | Skill and SOP definition management; Skill Executor for MCP tool invocation; SOP Orchestrator for ordered multi-step execution |
| [agents](modules/agents/tech-spec.md) | Agent type definitions, role-governed permissions, first-class OIDC agent identities, asynchronous session queue (AgentJob), LangChain deep agent runtime executor (observe-reason-act loop with LangChainModelFactory, GuardrailCallback, ExecutionLoggingCallback), model configuration management, structured output integration (data type assignment, output validation, query_result system tool), and background session dispatcher |
| [data-types](modules/data-types/tech-spec.md) | Centralized agent Data Type Registry: reusable typed schemas (string, number, boolean, date, enum fields), schema-aware validation (SchemaValidationService), typed output persistence (AgentOutput → AgentJob linkup), admin CRUD UI (DataTypesPage, DataTypeFormDialog), output querying and CSV export (AgentOutputsPage), and LangChain structured output enforcement via ToolStrategy |
| [auth](modules/auth/tech-spec.md) | JWT authentication and group claim processing pipeline: Keycloak group membership mapper provisioning, IdP group claim extraction, fire-and-log user/group sync in the auth middleware, and automatic UserGroup assignment via the GroupClaimMapper |
| [control-center](modules/control-center/tech-spec.md) | Zero-trust PKI security layer: Certificate Authority for agent instance X.509 certificates, Permission Resolution Service (cert → roles → tools), and on-demand OAuth Token Refresh Service; issues identity tokens to the Communication Hub at tool call time |
| [agent-runtime](modules/agent-runtime/tech-spec.md) | Agent execution-time certificate management: loads and validates mTLS certificates issued by the Control Center CA, configures HTTP clients for mutual TLS, monitors certificate expiry and triggers atomic renewal; enforces zero-token metadata contract with the Control Center |
| [gateway](modules/gateway/tech-spec.md) | External-facing agent lifecycle protocol (init/request/question/answer/close) over HTTP and MCP transports; endpoint registry |
| [comm-hub](modules/comm-hub/tech-spec.md) | Redis-backed message broker, WebSocket server bridging browser clients, inter-agent routing, and session context management |
| [scheduling](modules/scheduling/tech-spec.md) | APScheduler cron engine with PostgreSQL job store; scheduled job CRUD, pause/resume, and execution history |
| [conversations](modules/conversations/tech-spec.md) | Persistent conversation session, turn, and tool call record store for complete audit trails and replay |
| [results](modules/results/tech-spec.md) | Structured agent result persistence (legacy `save_result` decoupled from active agent tool path); results are now saved via `save_data` (intermediate) and runtime executor (final output) |
| [notifications](modules/notifications/tech-spec.md) | Outbound notification dispatcher for email, Slack, Teams, and webhook channels; channel-as-MCP-tool registration and event history |
| [observability](modules/observability/tech-spec.md) | OTEL telemetry initialisation for backend and frontend; OTEL Collector pipeline configuration; Helm chart for production Kubernetes deployment |
| [mcp-demo-app](modules/mcp-demo-app/tech-spec.md) | Standalone Python FastAPI MCP server demonstrating end-to-end dual-identity propagation; exposes three tools (`helloWorld`, `helloAgent`, `helloUser`) that validate agent and user JWTs against separate Keycloak realms and enforce `mcp_role`-based access control; registers with the MCP Hub under the `demo` slug; supported by backend pipeline changes in the Communication Hub, Control Center, and frontend WebSocket layer |
| [showcase](modules/showcase/tech-spec.md) | Fully static Vite + TypeScript site served via GitHub Pages presenting Parthenon's architecture, security model, and UI screenshots in a single scrollable page with tabbed demo panels and interactive Mermaid diagram; CI/CD pipeline deploys on push to `main` (`site/**` path filter); no backend dependencies

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
