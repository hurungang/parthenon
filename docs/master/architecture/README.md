# Architecture Documentation — Parthenon Enterprise AI Harness

Entry point for the master architecture set. Start with the
[System Overview](system-overview.md) — it holds the cross-cutting properties
(service segregation, tenant isolation, authentication paths, turn ownership)
and links into the module-level diagrams. Module pages carry the diagrams and
integration detail; they never repeat the system-level narrative.

## System Level

| Document | Covers |
|---|---|
| [System Overview](system-overview.md) | End-to-end topology, service boundaries, startup validation, multi-tenancy, authentication paths, permission authorization, conversational turn ownership, decision pathways, token expiry alerting |

## Platform Modules

| Document | Covers |
|---|---|
| [Multi-Tenancy](modules/multi-tenancy.md) | Tenancy switch, tenant resolution, root-tenant model, isolation invariants |
| [IAM](modules/iam.md) | Roles → policy statements → resource types, wildcard evaluation, permission containment |
| [Identity](modules/identity.md) | Identity providers, principals, RBAC entities and bootstrap |
| [Control Center](modules/control-center/architecture.md) | Security authority, internal data plane, certificate and permission resolution |
| [Control Center — Conversations](modules/control-center/conversations.md) | Turn ownership, persisted activity state, durable pause/resume |
| [Control Center — Optimization & Plans](modules/control-center/optimization-and-plans.md) | Authoring models, plan generation, optimization lifecycle |
| [Control Center — Runtime Monitoring](modules/control-center/runtime-monitoring.md) | Topology projection, live stream, polling fallback |
| [Control Center Assistant](security/control-center-assistant.md) | Assistant management tools, confirm-before-write, preview/approval contract |
| [Agent Runtime](modules/agent-runtime/architecture.md) | Execution-time certificate handling, tenant binding, checkpoint courier, live-test endpoint |
| [Communication Hub](modules/communication-hub/architecture.md) | Broker, WebSocket surface, tool routing, MCP serving, forward-only tenant relay |
| [Communication Hub (index)](modules/communication.md) | Short index page for the hub module (points to the authoritative architecture) |
| [Agent Lifecycle](modules/agent-lifecycle.md) | Submission → execution → intervention → completion, delegation |
| [Agent Types](modules/agent-types.md) | Configuration model, completeness expectations, model binding |
| [Agent Roles](modules/agent-roles.md) | Role/permission vs agent-type visibility split |
| [Agent Management Panel](modules/agent-management-panel.md) | Draft composition, resource pickers, shared topology canvas |
| [Agent Instance Dashboard](modules/agent-instance-dashboard.md) | Live instance inventory and controls |
| [Tool Execution](modules/tool-execution.md) | Tool routing, permission filtering, system/decision/MCP tool families |
| [MCP Hub](modules/mcp-hub/architecture.md) | Server registry, slug namespacing, sessions, tool-call proxy |
| [Decision Models](modules/decision-models/architecture.md) | Vendor catalogue, encrypted credentials, model enablement, guardrails |
| [Decision Tools](modules/decision-tools/architecture.md) | Typed question derivation, answer gating, execution routing |
| [Sandboxed Scripting](modules/sandboxed-scripting.md) | Script-first dispatch, sandbox boundaries, fallback, LLM mock layer |
| [Sandboxed Scripts — Security](security/sandboxed-scripts.md) | Sandbox invariants and rationale |
| [Third-Party Agent Integration](modules/third-party-agent-integration/architecture.md) | Client grants, gateway, publishable-origin rules |
| [API Key Security](security/api-key-security.md) | Key classes, hashing, validation path, rate limits |
| [Certificate Management](security/certificate-management.md) | CA, certificate classes, validity and revocation |
| [Token Refresh Service](modules/token-refresh.md) | Agent identity token refresh and health |
| [Model Configuration Service](modules/model-config.md) | Provider configs, encrypted credentials, enabled models |
| [Scheduling](modules/scheduling/architecture.md) | Cron engine, job store, dispatch |
| [Execution Logs](modules/execution-logs.md) | Log capture and audit surfaces |
| [Dashboard](modules/dashboard.md) | Permission-aware operational metrics aggregation |
| [Runtime Control Dashboard](modules/runtime-control-dashboard.md) | Runtime inventory and control surface |
| [Observability](modules/observability.md) | OTEL instrumentation, collector, exporters |
| [MCP Demo App](modules/mcp-demo-app/architecture.md) | Dual-identity demo server and airline booking scenario |

## Conventions

- Mermaid only, at most 15 nodes per diagram.
- Service level only — no class listings, method signatures, or code.
- Cross-cutting property belongs in the System Overview; module detail belongs in the module page (link, don't duplicate).
