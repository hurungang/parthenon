# Module: control-center — Tech Spec

> Part of the [technology documentation](../../README.md).

## Overview

The Control Center is the authoritative security and identity hub for agent execution in the Parthenon platform. It implements a zero-trust PKI layer: a Certificate Authority issues X.509 certificates to agent instances, a Permission Resolution Service maps certificate serial numbers to allowed MCP tools and identity tokens, and a Token Refresh Service automatically renews agent OAuth tokens before expiry. All agent-to-platform communication uses mutual TLS authenticated by these certificates, ensuring that identity operations are centralised, audited, and never exposed to the agent execution layer.

**Security Model:** Agent instances receive certificates (not tokens). The Communication Hub asks the Control Center to authorise every tool call — the Control Center resolves the cert → agent type → roles → tools chain and returns a fresh identity token only if the tool is permitted.

Control Center is also the **sole database gateway** and the owner of the internal data plane: conversation persistence, activity/resume state, agent context, outputs, management tools, and every other internal service-to-service route. Those routes are certificate-gated and allowlisted per caller.

---

## Where the detail lives

| Page | Covers |
|------|--------|
| [security-layer.md](security-layer.md) | Certificate Authority, token refresh and token health, permission resolution, API key management, security audit models, certificate/API-key endpoints |
| [internal-data-plane.md](internal-data-plane.md) | Internal route families and caller allowlists, intervene endpoints, system-tool endpoints, conversation activity/resume data plane, tenant-aware dispatch, integration tests |
| [multi-tenancy page](../multi-tenancy/tech-spec.md) | Tenant resolution middleware, row-level scoping, tenant authority (`TenantContext`, signed headers) |
| [agents](../agents/tech-spec.md) | Agent types/roles/identities; the assistant management toolset; plans and optimization |
| [conversations](../conversations/tech-spec.md) | Session/turn persistence, activity state, resume index and checkpoints |

---

## Key Components (summary)

| Area | Responsibility | Page |
|------|----------------|------|
| Certificate Authority | Root CA lifecycle; issues/validates/revokes agent instance certificates (24 h) and service certificates (30 d) | [security-layer.md](security-layer.md) |
| Token refresh & health | On-demand OAuth refresh with backoff and audit; refresh-token-authoritative health classification | [security-layer.md](security-layer.md) |
| Permission resolution | Cert/API-key → agent type → identity → roles → tools; inline token refresh; explicit denial reasons | [security-layer.md](security-layer.md) |
| API keys | Key generation/hashing/validation, identity-role binding, usage audit, internal validation endpoint | [security-layer.md](security-layer.md) |
| Internal data plane | Certificate-gated internal routers and per-caller allowlists; agent context, session data, outputs, system tools, management tools, MCP proxy | [internal-data-plane.md](internal-data-plane.md) |
| Intervene requests | Operator approvals/choices/text for job and conversation scopes; the conversation answer path advances the resume record | [internal-data-plane.md](internal-data-plane.md) |
| Startup validation | Validates PostgreSQL/OIDC/Redis reachability, initialises the CA and OIDC registry, seeds system tools/roles, runs tenant + reaper sweeps | this page |

---

## Security invariants

- Agent instances hold certificates (24 h), service identities hold service certificates (30 d); neither carries an identity token.
- Agent-instance certificates are rejected on every `/internal/*` route; service certificates are allowlisted per caller and per route template.
- Control Center is the only component that writes PostgreSQL and the only issuer of identity tokens; CH and AR are forward-only.
- Token material is encrypted at rest (AES-256) and decrypted only at call time; it is never returned to an agent, logged, or echoed in a tool result.
- Every authorisation decision, certificate validation and token refresh is audited synchronously.
- Internal data-plane calls without a valid signed tenant context fail closed (401) when multi-tenancy is enabled.

## Recent capability highlights

- **Conversation activity + durable pause state** — CC now owns `ConversationActivity`, the resume index and the checkpoint payload; see [conversations](../conversations/tech-spec.md) and the [data plane](internal-data-plane.md).
- **Control Center Assistant management toolset** — `cc____` management tools with full UI-parity payloads and structured validation errors; see [agents — assistant](../agents/assistant.md).
- **Optimization conversation and live-test ledger** — an optimization-channel conversation plus an operator-approved, single-use live script run; see [agents — plans & optimization](../agents/plans-optimization.md).

---

## Startup and DB boundary

**Startup sequence:** Control Center no longer auto-provisions Keycloak realms at startup. It validates that external dependencies are reachable and fails fast with actionable messages; identity-provider provisioning is an operator-invoked operation handled exclusively by the [setup tool](../setup/tech-spec.md).

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `create_app` | function | CC FastAPI application factory; composes startup handlers, routers and exception handlers | `backend/app/main.py` |
| `startup_event` | coroutine | Startup sequence — validates dependencies instead of provisioning them | `backend/app/main.py` |
| `_validate_oidc_provider` / `_validate_postgresql_reachable` / `_validate_redis_reachable` | coroutines | Reachability validation (OIDC discovery, lightweight SQL, Redis PING) | `backend/app/main.py` |
| `_initialize_certificate_authority` | function | Loads or generates the root CA and encrypted private key | `backend/app/main.py` |
| `_initialize_oidc_provider_registry` | function | Loads OIDC provider configs into the in-memory registry | `backend/app/main.py` |
| `_run_bootstrap` | function | Seeds system roles and permissions at startup | `backend/app/main.py` |
| `_seed_system_tools` | function | Seeds system MCP server/tool rows | `backend/app/main.py` |
| `_sweep_root_tenant` / `_sweep_default_tenant_roles` | functions | Startup tenant self-healing sweeps (root identity, preset roles) | `backend/app/main.py` |
| `_cleanup_stale_sessions_on_startup` | function | Closes non-terminal sessions at startup | `backend/app/main.py` |
| Live-test expiry sweep hook | startup hook | Starts the periodic live-test approval sweep next to the activity reaper | `backend/app/main.py` |
| `engine` / `AsyncSessionLocal` / `get_db` | engine / factory / dependency | CC-owned database boundary; every persisted read/write in the platform goes through it | `backend/app/db/session.py` |
| `_validate_oidc_provider` | coroutine | Startup validation of OIDC provider reachability; realm provisioning lives in the setup tool | `backend/app/main.py` |

---

## Code Reference Map — cross-cutting

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `create_app` | function | Application composition entry point (public + internal routers, exception handlers) | `backend/app/main.py` |
| `_register_routers` | function | Registers internal route groups under `/api/v1/internal` and the public API routers | `backend/app/main.py` |
| `router` (internal includes) | router module | Internal router registration (agent data, session data, authorization, certificates, system tools, management tools, mcp proxy, scripts) | `backend/app/api/v1/__init__.py` |
| `get_settings` | function | Configuration accessor for all CC services (per-component env vars, YAML, defaults) | `backend/app/core/config.py` |
| `engine` | SQLAlchemy engine | CC-owned database engine | `backend/app/db/session.py` |
| `AsyncSessionLocal` | session factory | Async session factory for all persisted state | `backend/app/db/session.py` |
| `get_db` | dependency | DB session dependency (applies tenant scope at the gateway) | `backend/app/db/session.py` |
| `TenantResolutionMiddleware` | middleware | Resolves/binds the tenant once per request (see the [multi-tenancy page](../multi-tenancy/tech-spec.md)) | `backend/app/middleware/tenant_resolution.py` |
| `apply_tenant_scope` | function | Row-level tenant scoping choke point on `get_db` | `backend/app/db/tenant_scoping.py` |
| `set_tenant_span_attributes` | function | Tenant attribution on spans/logs | `backend/app/core/tenant_context.py` |
