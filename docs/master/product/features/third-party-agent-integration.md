# Third-Party Agent Integration

## Overview
Third-Party Agent Integration lets a third-party system use a Parthenon agent *as an agent* — to chat with a conversational agent or submit a request to a typed agent — through a governed, tenant-managed access grant called a **client**. A client is bound to exactly one agent type and grants access only to that type's **input interface** (a conversation turn or a typed submit). A client is deliberately *not* an agent identity: it cannot call tools, reach the MCP hub, or impersonate an agent. Clients come in two forms the tenant chooses: a **secret** credential for server-to-server use, and a **publishable** credential that is safe to embed in a browser, powering a white-label chat widget with no Parthenon branding. Access is tenant-scoped, rate-limited, and fully audited, and ships with JavaScript/Python SDKs plus a runnable local example.

## Who Uses It
- **Platform / Tenant Administrators**: Create clients for agent types, choose secret vs publishable, configure white-label theming and rate limits, and revoke access
- **Third-Party Developers / Integrators**: Use the SDKs and guidance to embed a chat widget (publishable client) or wire a server-side flow (secret client)
- **End Users (the third party's customers)**: Chat with the embedded assistant or submit requests, with no awareness of Parthenon behind the scenes
- **Security / Compliance Officers**: Review audit logs and verify tenant isolation
- **Platform Operators**: Monitor per-client usage and rate limits

## What It Does
- Lets a tenant administrator add a **client** bound to exactly one agent type, choosing a **secret** (server-side) or **publishable** (browser-safe) credential; clients are managed and revoked independently
- Grants access **only** to the target agent type's input interface — never to tools, the MCP hub, or any agent identity; the invoked agent type runs with its own identity and role exactly as configured
- Powers an **embeddable white-label chatbot** for conversational agent types via a publishable client: configurable name, avatar, and colors, zero Parthenon branding, and anonymous end-user chat
- Supports **stateful conversations**: a client starts a conversation session, sends multiple messages that share the same conversation context, and ends the session — matching the platform's in-product chat experience
- Provides a **request/response flow** for typed (non-conversational) agent types: submit input → receive a validated, typed response with validation status and raw-output fallback
- Enables **server-to-server integration** with a secret client that never leaves the third party's servers; when the third party and tenant share an identity provider, the backend may optionally pass its end user's identity (dual identity, server-to-server only, validated and tenant-matched)
- Requires every **publishable** client to declare at least one allowed serving origin (wildcards supported); requests from non-allowlisted origins are rejected
- Enforces **per-client rate limits**, rejecting excess requests with a clear rate-limit error
- Records **all client invocations** (success and failure) in the audit log — including client, agent type, operation, and outcome, but never the credential value
- Ships **consumer guidance, JavaScript and Python SDKs, and a runnable local example** so integrators can validate the full flow end-to-end

## Key Concepts
- **Client**: A tenant-managed grant bound to exactly one agent type, allowing a third party to invoke that type's input interface. Not an identity — no tool access, no impersonation.
- **Secret Client**: A server-to-server credential for trusted backends; the third party controls input and the credential never reaches a browser.
- **Publishable Client**: A browser-safe credential for embedding; protected by a required origin allowlist. Creating one shows a warning that it exposes the agent type's full behavior publicly — the tenant owns the decision.
- **Input-Interface-Only Access**: A client can only start/message/end conversations or submit typed requests. Nothing more.
- **White-Label Theming**: Configurable name, avatar, and colors so the embedded chatbot presents as the third party's own.
- **Dual Identity**: Optional end-user identity passthrough for secret clients, server-to-server only; never issued to or stored by the browser.

## Acceptance Criteria
### Client Management
- A tenant administrator can create a client bound to one agent type (searchable dropdown) with a secret or publishable credential
- Clients appear in the agent type's clients list and the list reflects changes without a manual page reload
- Allowed origins and rate limit are editable; name, credential type, and target agent type are fixed
- A client can be deactivated (immediately unusable) and reactivated, or removed permanently with confirmation
- Duplicate client names within a tenant are rejected with a clear error
- Creating a publishable client shows a clear warning about public exposure (soft warning, no hard block)

### Access Scope & Security
- A client credential reaches only the agent type's input interface; it cannot list or call tools, reach the MCP hub, or authenticate as an agent identity
- Missing, invalid, or revoked credentials are rejected with a clear error
- Every client is tenant-scoped: it can never reach another tenant's agents, data, or resources
- A publishable client must have at least one allowed origin; requests from non-allowlisted origins (or with no origin) are rejected
- Per-client rate limits are enforced with a clear rate-limit error

### Conversational & Typed Invocation
- End users can hold multi-turn conversations through the embedded widget without any Parthenon account; the widget honors the white-label theme with no Parthenon branding
- Conversations are stateful: start, multiple context-sharing messages, and end; failures surface as clear error turns, not endless spinners
- Typed agents follow submit-input → typed-response, with validation status and raw-output fallback; invalid submissions are rejected with a clear description of the expected input shape

### Audit & SDKs
- All client invocations (success and failure) are audited with client, agent type, operation, and outcome — never the credential value
- JavaScript SDK supports widget embedding and conversational/request-response calls; Python SDK supports request-response and server-side conversational usage
- A runnable local example exercises the integration end-to-end without external dependencies

## Out of Scope
- Granting clients any tool, MCP-hub, or identity access — input interface only
- Identity token issuance, storage, or forwarding to the browser — dual identity is server-to-server only
- Hard-blocking specific agent types from being exposed (soft warning only)
- Exposing raw database access or backend credentials to third parties
- Billing/metering dashboards for third-party consumption (rate limiting only)
- Mobile-native SDKs; the widget targets web embedding
- SDK languages beyond JavaScript and Python
- Any change to internal (first-party) agents, skills, SOPs, or MCP servers — and no change to API keys (identity credentials)

## Dependencies & Constraints
- Builds on existing revocable credentials, agent identities and roles, agent types, conversational sessions, and the validated typed-response model
- Respects platform top-priority rules: segregated backend services, agent execution only in the agent runtime, all data access through the single governed path, and no identity tokens, database credentials, or decrypted secrets reaching agents or third parties
- All third-party traffic enters through the platform's single governed access path with centrally resolved permissions — no bypass of the permission model
- Allowed serving origins are a branding/UX control, not an authentication boundary
- All third-party activity is instrumented and auditable per platform observability conventions

## Multi-Tenancy Note

When multi-tenancy is enabled (see [Multi-Tenancy](multi-tenancy.md) and [Strict Tenant Isolation](strict-tenant-isolation.md)), every client and its credential are tenant-owned: a client resolves and invokes only its own tenant's agent types and can never reach another tenant. With multi-tenancy disabled (the default), behavior is unchanged — the deployment operates as the root tenant's workspace.
