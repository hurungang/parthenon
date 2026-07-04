# Parthenon Enterprise AI Harness — Product Documentation

Welcome to the master product documentation for the Parthenon Enterprise AI Harness. This index provides an overview of all core platform features, each with a dedicated specification document.


## Feature Index

- **Foundation Platform** — Roles, permissions, OIDC integration, setup wizard, and Web UI shell
- **MCP Hub** — Server registration, tool sync, session management, credential binding, and proxy
- **MCP Demo App** — Minimal MCP application for validating agent identity authentication and tool registration (reference implementation)
- **Skill Management** — Skill definition, MCP tool wrapping, and permission assignment
- **SOP Management** — SOP composition, step sequencing, and agent-to-agent delegation
- **SOPs** — Guardrailed delegated workflow behavior for predictable enterprise execution
- **Agent Management** — Agent types, identity, instance lifecycle, and max-instance enforcement
- **Agent Types** — Per-Agent-Type execution guardrail profiles and bounded policy controls
- **Agent A2A Communication and Slug Enforcement** — Dynamic agent-to-agent continuity, delegation governance, and slug-safe naming for routing-critical entities
- **Agent Data Types** — Centralized registry of reusable typed output schemas; administrators define flat-typed fields (string, number, boolean, date, enum) and assign data types to non-conversational agent types for schema-validated outputs
- **Agent Gateway** — Lifecycle protocol, HTTP and MCP transports
- **Agent Outputs** — Schema-validated typed agent results with dedicated admin page (filtering by data type, date range, agent type, CSV export), `query_result` system tool for cross-session result analysis, and structured field-by-field rendering in execution logs
- **Control Center** — Governance management for agent policies, guardrail profiles, and operational oversight
- **Communication Hub** — Message broker, WebSocket, session context, and agent-to-agent routing
- **Human-in-the-Loop Intervention** — Agents can pause execution and request human input (approval, choice, or free-form text) via the `system____human_intervene` tool; operators respond through the UI and execution resumes automatically
- **Schedule Management** — Cron scheduling, job management, and execution history
- **Conversation Management** — Conversation persistence, all turn types, audit, and replay
- **Result Management** — save_data and get_data/get_output tools, result repository, and UI access
- **Agent Save Data and Historical Retrieval** — Separate intermediate data saves from final outputs; agents can save and query historical data and outputs across sessions
- **Notification Integration** — Channel types (email, Slack, Teams, webhook), MCP tool exposure, and event history
- **Observability** — OTEL instrumentation, Collector, exporters (Prometheus, Jaeger, Loki), and admin dashboard
- **Project Showcase** — Public-facing static website on GitHub Pages presenting Parthenon's architecture, security model, and guided workflow walkthroughs for evaluators and contributors
