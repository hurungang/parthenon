# Third-Party Agent Integration — Reference

A quick business-language summary of how third parties use Parthenon agents. Full details: [Third-Party Agent Integration](../product/features/third-party-agent-integration.md).

## Clients

A **client** is a tenant-managed access grant bound to exactly one agent type. It lets a third party use that agent — nothing else. Two credential types:

- **Secret client** — a server-to-server credential for the third party's backend; it never reaches a browser, and the third party fully controls the input.
- **Publishable client** — a browser-safe credential for embedding, e.g. a white-label chat widget. It **must** declare at least one allowed serving origin (wildcards supported); requests from any other origin are rejected, so the key cannot be used from arbitrary sites.

## Agent-Type Binding & Input-Interface-Only Access

Every client is bound to exactly one agent type and grants access **only** to that type's input interface:

- A client can start conversations or submit requests to the bound agent type — nothing more.
- It **cannot** call tools, reach the MCP hub, or impersonate an agent identity. It is not an identity credential.
- The invoked agent type always runs with its own configured identity and role; the client does not alter its behavior.

## Stateful Conversations (Conversational Agent Types)

A conversational agent type exposed through a client supports a full stateful conversation lifecycle: **start** a session, send **multiple messages** sharing the same conversation context, and **end** the session — matching the in-product chat experience. Replies stream in real time; failures surface as clear error turns.

## White-Label Chat Widget (Publishable Client)

Publishable clients let a third party embed a conversational Parthenon agent as **their own chatbot**: configurable name, avatar, and colors, zero Parthenon branding, and end users chat anonymously with no Parthenon account.

## Request / Response (Typed Agent Types)

A typed (non-conversational) agent type is invoked as a simple "submit input → receive typed response" flow. The response is the platform's validated typed result, including validation status and a raw-output fallback. Invalid submissions are rejected with a clear description of the expected input.

## Server-to-Server & Dual Identity (Secret Client)

A secret client powers backend-to-backend integration. When the third party and the tenant share an identity provider, the backend may optionally pass its end user's identity so the agent acts on that user's behalf — **server-to-server only**: identity tokens are validated, tenant-matched, and never issued to or stored by a browser.

## Rate Limiting & Audit

- Per-client **rate limits** are enforced; excess requests receive a clear rate-limit error.
- Every client invocation — success **and** failure — is written to the audit log with the client, agent type, operation, and outcome (never the credential value).
- Clients are tenant-scoped: a client can never reach another tenant's agents, data, or resources.

## SDKs & Local Example

- **JavaScript SDK** — embed the chat widget and drive conversational and/or request-response calls.
- **Python SDK** — request-response flows and server-side conversational usage.
- A **runnable local example** lets an integrator exercise the full flow end-to-end against a local Parthenon instance with no external dependencies.

## What a Client Is Not

A client is **not** an API key. API keys remain identity credentials (bound to an agent identity + role, authenticating full MCP sessions) and are unchanged. Clients are a separate, non-identity credential class — see [API Key Security](../architecture/security/api-key-security.md).
