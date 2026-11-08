# Spec Delta: Third-Party Agent Integration

## Affected Spec Areas

- `docs/master/product/features/agent-types.md` — Agent types; a type may be exposed to third parties through one or more clients
- `docs/master/product/features/communication-hub.md` — Communication Hub governed surface; extended with a public client-invocation gateway
- `docs/master/product/features/agent-gateway.md` — Agent gateway; extended for third-party client invocations
- `docs/master/product/features/agent-outputs.md` — Agent Outputs; validated typed responses surfaced to third-party consumers
- `docs/master/product/features/strict-tenant-isolation.md` — Strict tenant isolation; clients are tenant-scoped
- `docs/master/product/features/observability.md` — Observability; client-invocation instrumentation and audit logging
- `docs/master/product/features/api-key-management.md` — API keys; explicitly clarified as unchanged (identity credentials), distinct from the new client credential
- `docs/master/architecture/security/api-key-security.md` — Credential-class documentation; clients vs API keys

## New Capabilities

- **Client (agent-type access grant)**
  - A tenant administrator adds a **client** bound to exactly one agent type; a client grants access to that type's *input interface* only.
  - A client carries a credential of type **secret** (server-to-server) or **publishable** (browser-safe), and is managed and revoked independently.
  - A client is **not** an agent identity — it cannot list/call tools, reach the MCP hub, or impersonate an agent.

- **Conversational agent → embeddable white-label chatbot (publishable client)**
  - A conversational agent type exposed through a publishable client can be embedded as a chat widget that acts as the third party's own chatbot.
  - White-label theming (name, avatar, colors) with zero Parthenon branding; end users chat anonymously.

- **Non-conversational agent → form / request-response**
  - A typed agent type exposed through a client can be invoked as "submit input → receive typed response", as a generated form or a request/response interface, returning a validated typed result with validation status and raw-output fallback.

- **App-to-app (secret client) with optional dual identity**
  - A third-party backend invokes an agent type server-side with a secret client credential that never leaves their servers.
  - When sharing an identity provider, the backend may optionally pass its end user's identity (server-to-server only); the identity is validated and tenant-matched.

- **Consumer guidance & SDKs**
  - Integration guidance, JavaScript + Python SDKs, and a runnable local example.

## Modified Capabilities

- **Agent Types**
  - Before: define agent configuration (identity, role, model, instructions, I/O) and are the execution unit for first-party and MCP use.
  - After: an agent type may additionally be exposed to third parties through one or more clients; its `input_type` selects the integration surface (conversation → widget, typed → request/response). No change to the type's identity/role behavior.

- **Communication Hub / Agent Gateway**
  - Before: exposes the MCP tool hub to external clients authenticated by API keys (identity credentials).
  - After: additionally exposes a client-invocation gateway (`/integrate/*`) authenticated by client credentials, routing conversational turns and typed submissions to the target agent type.

- **Observability / Audit Logging**
  - Before: OTEL traces, metrics, and logs for internal and existing MCP traffic.
  - After: client invocations are additionally instrumented with per-client usage, rate-limit events, and full success/failure audit logging.

## Removed Capabilities

- None.

## Spec Update Instructions

- Update **Agent Types** spec: document that a type may be exposed to third parties through clients (one-to-many), and that the type's input/output type selects the integration surface.
- Update **Communication Hub / Agent Gateway** spec: document the client-invocation gateway and the `secret`/`publishable` credential classes; note clients cannot impersonate an identity.
- Update **Agent Outputs** spec: note validated typed outputs are delivered to third-party consumers with validation status and raw-output fallback.
- Update **Strict Tenant Isolation** spec: add that clients and their credentials are tenant-scoped — never reaching another tenant.
- Update **Observability** spec: document per-client usage/rate-limit metrics and full client-invocation audit logging.
- Update **API Key Management** spec: explicitly note API keys remain identity credentials for local agents and are unchanged; clients are a separate, non-identity credential class.
- Update `docs/master/architecture/security/api-key-security.md`: document the two credential classes (API keys = identity; clients = agent-type input-interface access).
- Add a reference doc in `docs/master/reference/`: third-party agent integration summary — clients (secret/publishable), agent-type binding, input-interface-only access, embeddable white-label widget, request/response, dual identity (server-to-server), rate limiting, and the JS/Python SDKs plus runnable local example.
- Explicitly do NOT modify the Agent Identity, Agent Roles, Skills, SOPs, MCP Hub, or sandboxed-scripting specs — first-party agent behavior and identity credentials are unchanged.
