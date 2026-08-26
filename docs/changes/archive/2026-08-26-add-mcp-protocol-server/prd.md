# MCP Protocol Server — PRD

## Epic Overview

Parthenon's Communication Hub already authenticates external third-party AI agents via API keys, but today it exposes only a single REST endpoint (`/mcp/tools/load_skills`) for skill discovery. Because it does not speak the Model Context Protocol, standard MCP clients — GitHub Copilot, Claude Desktop, Cursor, and custom agents — cannot treat Parthenon as a native MCP server. This epic adds a first-class MCP protocol server to the Communication Hub so those clients can connect over the standard MCP protocol (initialize, list tools, and invoke tools) using the API keys administrators already manage, while reusing the existing role-based permission resolution and MCP proxy engine unchanged. This opens Parthenon's managed skills, SOPs, and proxied MCP tools to the broader AI-agent ecosystem without introducing a new security model.

## Business Goals

- **Become a first-class MCP server** — External AI agents (Copilot, Claude, Cursor, custom agents) can connect to Parthenon over the standard MCP protocol and invoke its managed tools natively, with no custom REST integration.
- **Reuse existing security, not rebuild it** — Authentication uses the existing Parthenon API keys (already bound to an agent identity + role), and authorization reuses the existing permission resolution path. No new credential or permission system is introduced.
- **Preserve the security posture** — External clients never receive identity tokens or credentials; only Control Center connects to the database; and the existing internal mTLS certificate path for Agent Runtime remains unchanged.
- **Zero regression** — Internal Agent Runtime agents and the existing REST skill-discovery endpoint continue to work exactly as they do today.

## Users & Personas

- **External AI Agent / MCP Client** — GitHub Copilot, Claude Desktop, Cursor, or a custom agent that connects to Parthenon as an MCP server to discover and invoke permitted tools.
- **Third-party Agent Developer** — Configures an MCP client to point at Parthenon's endpoint using an API key obtained from a Platform Administrator; wants a standard, zero-integration connection experience.
- **Platform Administrator** — Manages the API keys that now also grant MCP protocol access; expects external access to stay governed by the roles and permissions already assigned.
- **Security / Compliance Officer** — Requires that MCP protocol access inherits the same role-based permissions, token isolation, and audit logging as the existing API-key path.

## User Stories

- As an external AI agent, I want to connect to Parthenon using the standard MCP protocol so that I can discover and invoke tools without writing custom REST code.
- As a third-party agent developer, I want to point my MCP client (Copilot, Claude Desktop, Cursor) at Parthenon's endpoint with my existing API key so that I can start using Parthenon's tools immediately.
- As a Platform Administrator, I want external MCP clients to authenticate with the API keys I already manage so that I do not need to provision a separate access mechanism.
- As a Platform Administrator, I want external MCP access to honor the bound role's permission set so that clients only ever see and call tools they are authorized to use.
- As a Platform Administrator, I want to optionally set an expiration date on an API key (or choose no expiration) so that I can time-limit external access and revoke it automatically.
- As a Security Officer, I want external MCP sessions to keep identity tokens and credentials inside the protected boundary so that sensitive material is never exposed to a client.
- As an internal Agent Runtime agent, I want my existing mTLS certificate connection path to remain unchanged so that my current workflows are unaffected.

## Acceptance Criteria

### MCP Protocol Connection

- An external MCP client can connect to the Communication Hub's MCP endpoint and complete a standard MCP handshake (initialize) using an existing API key.
- After a successful handshake, the client can list the tools it is permitted to use (tools/list), including system tools (such as `load_skills`) and MCP tools proxied from registered MCP servers.
- The client can invoke a permitted tool (tools/call) and receive the tool's result.

### Authentication & Authorization

- Only valid, active API keys authenticate successfully; invalid, expired, or revoked keys receive a clear authentication error.
- The permission set applied to an MCP protocol session is resolved from the API key's bound agent identity and role, enforced identically to internal agents.
- An external client only ever sees and calls the tools its bound role permits; unauthorized tool calls are rejected.
- The underlying identity token is never returned to the external client — only the Communication Hub holds it for proxying.

### API Key Expiration

- When creating an API key, an administrator may optionally set an expiration timestamp; omitting it means the key never expires.
- A key whose expiration timestamp has passed is rejected at authentication with a clear error, exactly like a revoked key.
- The Web UI shows each key's expiration date (or "No expiration") in the key list and lets the administrator set or omit the expiration when creating a key.

### Skill Discovery via MCP Protocol

- The `load_skills` system tool is available through the MCP protocol and returns all skills and SOPs the client is permitted to access, with full tool definitions, input/output schemas, and `updated_at` timestamps.
- Incremental sync via the `since` parameter behaves the same as the existing REST endpoint, returning only skills updated after the given timestamp.

### No Regression

- The existing internal mTLS certificate authentication path for Agent Runtime is unchanged.
- The existing REST `/mcp/tools/load_skills` endpoint continues to work for current consumers.
- Existing API key management, role management, and MCP server management flows in the Web UI are unaffected.

### Security & Audit

- Successful and failed MCP protocol authentication events are logged with the key identifier and bound identity — never the key value.
- Tool invocations through the MCP protocol are auditable and traceable like existing tool calls.

## Out of Scope

- New authentication mechanisms beyond the existing Parthenon API keys (e.g., OAuth/OIDC-based MCP authorization flows).
- Changes to the internal Agent Runtime mTLS certificate authentication path.
- Client SDKs, libraries, or helper tools for third-party MCP clients (they connect via the standard MCP protocol).
- Reimplementation of the permission resolution or MCP proxy engine — existing logic is reused as-is.
- Removal or deprecation of the existing REST skill-discovery endpoint.
- Automatic revocation/status-change of expired keys — an expired key remains "active" in the database and is rejected at authentication time rather than flipped to a distinct status.

## Dependencies & Constraints

- Depends on the existing API key authentication path (API keys bound to agent identity + role, validated against Control Center).
- Depends on the existing permission resolution and MCP proxy engine — this epic reuses them rather than reimplementing.
- External clients must support the standard MCP protocol (initialize / tools/list / tools/call) with API-key authentication.
- Constraint: only Control Center may connect to the database; the Communication Hub must route all data access through Control Center.
- Constraint: external agents must never receive identity tokens, database credentials, or other sensitive data.
- Constraint: agents may only run in Agent Runtime; this epic does not change where agent execution occurs.
