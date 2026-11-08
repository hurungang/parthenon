# PRD: Third-Party Agent Integration

## Epic Overview

Parthenon already lets external agents authenticate *as* an agent identity through revocable credentials, and agent *invocation* is reachable as a tool. What is missing is a first-class way for a third-party system to use an agent *as an agent* — to talk to a conversational agent or submit a request to a typed agent — through a governed, tenant-managed access grant. This change introduces the **client**: a tenant-managed grant bound to a single agent type that allows a third party to invoke that agent type's input interface (a conversation, or a request/response). A client is deliberately *not* an agent identity — it cannot access tools or impersonate an agent. Clients come in two forms the tenant chooses: a **secret** credential for server-to-server use (the third party's backend controls input), and a **publishable** credential that is safe to embed in a browser, powering a white-label chat widget. Access is tenant-scoped, rate-limited, and fully audited, and ships with JavaScript/Python SDKs plus a runnable local example.

## Business Goals

- Let third parties embed Parthenon conversational agents as their own chatbot (transparent branding, configurable name/avatar/theme) with zero Parthenon branding leak.
- Give non-conversational agents a first-class typed request/response path that returns a validated, typed response.
- Clearly separate two primitives: an **agent identity credential** (what an agent *is*) from a **client** (who may *use* an agent type) — so integration access is decoupled from agent identity and cannot abuse it.
- Give tenants control over exposure: a **secret** client for trusted server-side use, and a **publishable** client for browser-facing use, each managed and revocable independently.
- Cut integrator onboarding time with consumer SDKs (JavaScript and Python) and a runnable local example alongside written guidance.

## Users & Personas

- **Platform / Tenant Administrator** — Creates clients for agent types, chooses secret vs publishable, configures white-label theming and rate limits, and revokes access.
- **Third-Party Developer / Integrator** — Consumes the SDKs and guidance to embed a chat widget (publishable client) or wire a server-side flow (secret client); runs the local example to validate end-to-end.
- **End User (third party's customer)** — Chats with the embedded assistant or submits a request and receives a typed answer, with no awareness of Parthenon behind the scenes.
- **Security / Compliance Officer** — Reviews audit logs and verifies tenant isolation and that no sensitive data is exposed to third parties.
- **Platform Operator** — Monitors per-client usage and rate limits and triages integration incidents.

## User Stories

- As a tenant administrator, I want to add a client for an agent type, so that I can expose that agent to a third party without exposing an agent identity.
- As a tenant administrator, I want to choose between a secret client (server-side) and a publishable client (browser-safe) per client, so that I control how the agent is exposed.
- As a tenant administrator, I want the client to grant access only to the agent's input interface — never to tools or to any identity — so that integration cannot be abused.
- As a tenant administrator, I want to configure white-label theming (name, avatar, colors) and a rate limit per client, so that a public agent appears as the third party's own and one noisy consumer cannot degrade the platform.
- As a tenant administrator, I want to deactivate or remove a client at any time, so that I can cut off a third party's access immediately.
- As a third-party developer, I want a secret client credential, so that my backend can invoke an agent without any secret reaching the browser.
- As a third-party developer, I want a publishable client credential and a JavaScript SDK, so that I can drop a conversational agent into my product as a chat widget my end users simply use.
- As a third-party developer, I want a Python SDK, so that I can integrate from my backend or server-side product.
- As a third-party developer, I want to invoke a non-conversational agent as a simple "submit input → receive typed response" flow, so that I get a validated, typed answer I can act on programmatically.
- As a third-party developer, I want the typed response to follow the platform's validated, typed response model, so that the output shape is predictable and validated.
- As a third-party developer, I want a runnable local example with integration guidance, so that I can test the full flow end-to-end before production.
- As a security officer, I want every client invocation (success and failure) written to the audit log, so that I can trace exactly what a third party did.
- As an end user, I want the embedded chat and form experiences to work without me needing any Parthenon account or credentials, so that the integration is transparent.

## Acceptance Criteria

### Client management

- A tenant administrator can create a client bound to exactly one agent type, choosing the agent type from a **searchable dropdown** and picking a **secret** or **publishable** credential.
- A client appears in the agent type's clients list with its name, credential type, theming, origins, rate limit, and status, and the list reflects changes without a manual page reload.
- A tenant administrator can **edit** a client's allowed origins and rate limit (only these fields are mutable; name, key type, and target agent type are fixed).
- A tenant administrator can **deactivate** a client (reversible — the credential is immediately unusable) and **reactivate** it later.
- A tenant administrator can **remove** a client permanently (the credential and its audit trail are deleted).
- Allowed origins support **wildcards** (e.g. `https://*.acme.com`), with helper text and a placeholder in the editor.
- The system rejects duplicate client names within a tenant with a clear error.
- When creating a **publishable** client, the platform shows a clear **warning** that this exposes the agent type's full behavior publicly, but does not hard-block it (the tenant owns the decision).

### Client access scope (critical)

- A client credential grants access **only** to the target agent type's input interface — a conversation turn (conversational type) or a typed submit (typed type).
- A client credential cannot list or call tools, cannot access the MCP hub, and cannot authenticate as an agent identity — integration access is fully decoupled from identity.
- The invoked agent type runs with its own identity and role exactly as configured; the client does not alter its behavior.

### Conversational agent → embeddable white-label chatbot (publishable client)

- A third-party developer can embed a conversational Parthenon agent as a chat widget that presents itself as the third party's own chatbot.
- The widget honors the configured white-label theme and leaks no Parthenon branding in the visible user experience.
- End users can hold a multi-turn conversation without any Parthenon account or credentials.
- A client can **start** a conversation session, **send multiple messages** that share the same conversation context (stateful — matching the Control Center chat experience), and **end** the session.
- Conversational turns behave like platform conversations: replies stream or deliver in real time, and guardrail/timeout failures surface as a clear error turn rather than an endless spinner.

### Non-conversational agent → form / request-response

- A third-party developer can invoke a typed agent as a "submit input → receive typed response" flow. There is **no chat surface** for non-conversational types: the input form is **auto-generated from the agent type's declared input schema**, and the one-shot conversational chat API is retired (conversational agents use the stateful conversation flow only).
- The typed response conforms to the agent type's declared output type and is delivered as a validated, typed result, including validation status and, where applicable, a fallback to the raw output.
- Invalid or schema-inconsistent submissions are rejected with a clear, actionable error describing the expected input shape.

### App-to-app (secret client)

- A third-party backend can invoke an agent server-side with a secret client credential that never leaves their servers; the third party controls the input.
- When the third party and the tenant share an identity provider, the backend may optionally pass its end user's identity so the agent can act on behalf of that user — server-to-server only, validated and tenant-matched before use.

### Security, scoping & isolation

- Client access is credential-based and is rejected with a clear error when the credential is missing, invalid, or revoked.
- Every client is tenant-scoped under strict tenant isolation: a client can never reach another tenant's agents, data, or resources.
- A client is not an identity and cannot impersonate one — no agent identity is granted to, or abusable by, the third party.
- A **publishable** client MUST have at least one allowed origin; requests from a non-allowlisted origin (or with no `Origin`) are rejected, so a publishable key cannot be called from an arbitrary site.
- Per-client rate limits are enforced; requests beyond the limit are rejected with a clear rate-limit error rather than silently dropped.
- All client invocations — success and failure — are recorded in the platform audit log, including the client, the agent type, the operation, and the outcome (never the credential value itself).

### Consumer guidance & SDKs

- Integration guidance for consumers covers the conversational (widget, publishable client) and non-conversational (request/response) paths, plus the server-to-server (secret client) path, with worked examples.
- A JavaScript SDK ships that supports embedding the chat widget and driving conversational and/or request-response calls.
- A Python SDK ships that supports the request-response flow and server-side conversational usage.
- A runnable local example is shipped so an integrator can exercise the integration end-to-end against a local Parthenon instance without external dependencies.

## Out of Scope

- Re-specifying existing capabilities — agent-identity credentials, the existing governed integration surface, conversational agent sessions, typed agent outputs, roles, and multi-tenant isolation are assumed present and unchanged.
- Granting clients any tool/identity access — a client only ever reaches the agent type's input interface.
- Hard-blocking specific agent types from being exposed — the tenant owns the decision to expose an agent type (a soft warning is shown for publishable clients).
- Exposing raw database access or any backend credentials to third parties.
- Identity token issuance, storage, or forwarding to the browser — dual identity is server-to-server only.
- A plugin/extension marketplace or third-party upload of custom agent code.
- Additional languages for consumer SDKs beyond JavaScript and Python.
- Any change to how internal (first-party) agents, skills, SOPs, or MCP servers operate.
- Billing/metering dashboards for third-party consumption (rate limiting is enforced, but no cost-reporting UI is added).
- Mobile-native SDKs (iOS/Android); the widget targets web embedding.

## Dependencies & Constraints

- Builds on the platform's existing revocable credentials, agent identities and roles, agent types, conversational agent sessions, and the validated, typed response model.
- Must respect platform top-priority rules: backend services remain fully segregated; agents run only in their isolated runtime; all data access flows through a single governed path; agents never receive identity tokens, database credentials, or decrypted secrets.
- A client is a new credential class, separate from agent-identity credentials; it grants input-interface access only and never an identity.
- Third-party traffic enters through the platform's single governed access path and resolves permissions centrally — no parallel ingestion path and no bypass of the permission model.
- Allowed serving origins are a secondary UX/branding control, not an authentication boundary; integrators provide their serving origin(s) for the widget.
- Aligns with the platform's strict tenant-isolation and observability conventions; all third-party activity is instrumented and auditable.
