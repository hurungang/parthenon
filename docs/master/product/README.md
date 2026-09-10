# Parthenon Enterprise AI Harness — Product Documentation

Welcome to the master product documentation for the Parthenon Enterprise AI Harness. This index provides an overview of all core platform features, each with a dedicated specification document.


## Feature Index

- **Foundation Platform** — Roles, permissions, provider-agnostic OIDC integration (any OIDC-compliant provider), independent user and agent identity providers, built-in super admin with enable/disable lifecycle, database-backed identity configuration, OIDC provider testing, setup wizard, Web UI shell, and operational dashboard
- **Dashboard Metrics** — Real-time stat cards, time-sensitive metrics with date range picker, and permission-aware widgets for platform health overview
- **MCP Hub** — Server registration, tool sync, session management, credential binding, and proxy
- **MCP Demo App** — Minimal MCP application for validating agent identity authentication and tool registration (reference implementation)
- **Skill Management** — Skill definition, MCP tool wrapping, and permission assignment
- **SOP Management** — SOP composition, step sequencing, agent-to-agent delegation, AI-assisted workflow authoring, and bounded delegation guardrails (cyclic-delegation prevention, depth limits, Default SOP fallback)
- **Agent Management** — Agent types, identity, instance lifecycle, and max-instance enforcement
- **Agent Types** — Per-Agent-Type execution guardrail profiles and bounded policy controls
- **Agent Identity** — OIDC agent-realm sign-in, encrypted token storage and automatic refresh, and identity-to-role assignment
- **Agent Execution** — Asynchronous agent session lifecycle from submission through completion, powered by the deep agent framework
- **Agent Plan Mode** — Pre-execution plan generation and preview for agent types
- **Agent Session Logs** — Full system instruction and user prompt captured for every agent run, visible in the UI for audit and traceability
- **Agent Runtime Security** — Service-segregation boundary enforcement, internal allowlist, and API key authentication for external agents
- **Agent A2A Communication and Slug Enforcement** — Dynamic agent-to-agent continuity, delegation governance, and slug-safe naming for routing-critical entities
- **Agent Data** — Filterable operator-facing module for browsing intermediate data saved by agents during execution, with full JSON inspection in a detail drawer
- **Agent Data Types** — Centralized registry of reusable typed output schemas; administrators define flat-typed fields (string, number, boolean, date, enum) and assign data types to non-conversational agent types for schema-validated outputs
- **Agent Gateway** — Lifecycle protocol, HTTP and MCP transports
- **Agent Outputs** — Schema-validated typed agent results with dedicated admin page (filtering by data type, date range, agent type, CSV export), `query_result` system tool for cross-session result analysis, and structured field-by-field rendering in execution logs
- **Agent Save Data and Historical Retrieval** — Separate intermediate data saves from final outputs; agents can save and query historical data and outputs across sessions; read-only result repository in the UI
- **API Key Management** — API keys for third-party AI agents connecting to the MCP Hub; keys hashed at rest and bound to agent identity and role
- **Control Center** — Governance management for agent policies, guardrail profiles, and operational oversight
- **Communication Hub** — Message broker, WebSocket, session context, and agent-to-agent routing
- **Human-in-the-Loop Intervention** — Agents can pause execution and request human input (approval, choice, or free-form text) via the `system____human_intervene` tool; operators respond through the UI and execution resumes automatically
- **Schedule Management** — Cron scheduling, job management, and execution history
- **Conversation Management** — Conversation persistence, all turn types, audit, and replay
- **Notification Integration** — Channel types (email, Slack, Teams, webhook), MCP tool exposure, and event history
- **Observability** — OTEL instrumentation, Collector, exporters (Prometheus, Jaeger, Loki), and admin dashboard
- **Telemetry Configuration** — Operator-configurable telemetry export targets, signal enable/disable, and log levels without code changes
- **Model Configurations** — Centrally managed LLM provider configs across twelve providers with encrypted credentials and enabled model lists
- **Identity Provider Setup** — Automatic group membership mapper provisioning for group-based permissions during identity bootstrap
- **Keycloak Identity Bootstrap** — Bundled Keycloak identity provider with guided setup wizard, YAML-based configuration, and CLI support
- **Project Showcase** — Public-facing static website on GitHub Pages presenting Parthenon's architecture, security model, and guided workflow walkthroughs for evaluators and contributors
