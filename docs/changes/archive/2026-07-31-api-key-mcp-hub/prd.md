# API Key MCP Hub — PRD

## Epic Overview

Parthenon's Communication Hub today only accepts connections from internal Agent Runtime instances authenticated via mTLS certificates. This precludes third-party AI agents — such as Claude Code, Cursor, or custom-built agents — from accessing Parthenon's tools, skills, and SOPs through the standard MCP protocol. This change introduces API key authentication to the Communication Hub, enabling external agents to connect as an MCP Hub client, discover and load accessible skills (including SOPs), and invoke tools — all governed by the same role-based permission model used for internal agents.

## Business Goals

- **Open the platform to third-party agents** — External AI coding assistants and custom agents can use Parthenon's managed tools, skills, and SOPs via standard MCP protocol
- **Maintain security posture** — API keys are hashed at rest, access is governed by existing roles/permissions, external agents never receive identity tokens, and all inter-service calls remain mTLS-secured
- **Enable skill versioning** — Skills gain `updated_at` timestamps so external agents can cache locally and only re-download changed skills, reducing bandwidth and latency
- **Zero regression for internal agents** — Existing certificate-based agent authentication continues unchanged; all current workflows function identically

## Users & Personas

- **Platform Administrator** — Creates and manages API keys for third-party integrations. Binds keys to existing agent identities with a specific agent role. Views and revokes keys as needed.
- **Third-party Agent Developer** — Obtains an API key from the Platform Administrator. Configures their agent to connect to Parthenon's MCP Hub endpoint. Wants seamless skill discovery and tool execution.
- **External AI Agent** — Connects via MCP protocol using an API key. Calls `load_skills` to discover accessible skills and tools with their full schemas. Caches skills locally and re-downloads only when `updated_at` changes.

## User Stories

- As a Platform Administrator, I want to create an API key bound to an existing agent identity and role so that a third-party agent can securely connect to Parthenon
- As a Platform Administrator, I want to see all active API keys with their bound identities and roles so that I can audit which external agents have access
- As a Platform Administrator, I want to revoke an API key so that I can immediately terminate access for a compromised or decommissioned integration
- As a third-party agent developer, I want to configure my agent with an API key so that it can authenticate to Parthenon's MCP Hub and access assigned tools
- As an external AI agent, I want to call `load_skills` to discover all skills and SOPs I am permitted to use so that I can understand what tools are available
- As an external AI agent, I want each skill to include an `updated_at` timestamp so that I can cache skills locally and only re-download changed ones

## Acceptance Criteria

### API Key CRUD Management

- Platform Administrator can create a new API key by selecting an existing agent identity and an agent role from dropdowns
- Created API key is displayed once at creation time (for copy); the key value is never shown again
- API keys are stored hashed; the clear-text key is never retrievable after creation
- Platform Administrator can view a list of all API keys with columns: name/label, bound agent identity, bound agent role, creation date, last used date, status (active/revoked)
- Platform Administrator can revoke an API key with a confirmation dialog
- Revoked API key immediately becomes unusable for authentication
- After revocation, the key remains in the list with status "revoked" and cannot be re-activated
- The API key list automatically refreshes after create or revoke operations — no manual page reload required
- Platform Administrator can filter the API key list by status (active/revoked)

### API Key Authentication on Communication Hub

- External agent can authenticate to the Communication Hub MCP endpoint using a Bearer token (`Authorization: Bearer <api_key>`) or query parameter (`?apiKey=<api_key>`)
- Invalid or revoked API keys receive a clear authentication error response
- Successful authentication resolves the bound agent identity, role, and permitted skills/tools
- External agents only have access to the skills and tools granted by the bound role — enforced identically to internal agents
- External agents NEVER receive the underlying identity token; only the Communication Hub holds it for proxying

### Skill Loading and Version Tracking

- External agents can call the `load_skills` tool to retrieve all skills they are permitted to access, with full tool definitions and input/output schemas
- Each skill in the response includes an `updated_at` timestamp reflecting when the skill definition last changed
- External agents can call a `get_skill_updates` tool (or pass `since` parameter to `load_skills`) to retrieve only skills updated after a given timestamp
- Skills without changes since the provided timestamp are excluded from the response, enabling efficient incremental sync

### Security and Audit

- API key creation and revocation events are recorded in the audit log
- API key usage (authentication events) is logged with the key identifier (not the key value) and the bound identity
- All Communication Hub to Control Center calls for key validation and token resolution are mTLS-secured with service certificates
- Failed authentication attempts with invalid/expired/revoked keys are logged for security monitoring
- Rate limiting is applied to authentication attempts to prevent brute-force attacks

### No Regression

- Existing certificate-based agent authentication continues to work without any changes
- Internal Agent Runtime agents can still connect, discover skills, and invoke tools exactly as they do today
- The Web UI's existing agent management, role management, and MCP server management pages are unaffected

## Out of Scope

- API key scoping beyond role-based permissions (e.g., per-tool or per-SOP key restrictions) — keys inherit the full permission set of the bound role
- API key expiration dates or automatic rotation — keys are valid until manually revoked
- Multiple API keys per agent identity — one active key per identity-role pair
- Self-service API key generation by external developers — keys can only be created by Platform Administrators
- Client SDKs or libraries for third-party agent developers — they interact via standard MCP protocol
- Modifying existing agent identity or role management flows
- Rate limiting or quota enforcement on tool calls made via API keys (beyond basic auth rate limiting)

## Dependencies & Constraints

- Requires existing agent identities to be provisioned before an API key can be created for them
- Requires existing agent roles with permission sets to be defined before binding
- API key validation requires Communication Hub to call Control Center's internal API (mTLS-secured)
- Identity token resolution and injection follow the same pattern as existing agent flow — Control Center decrypts the token and passes it to Communication Hub, which injects it into proxied MCP requests
- Skill `updated_at` timestamps require skills to record their last modification time — existing skills without timestamps will need a one-time backfill
- External agents must support MCP protocol with Bearer token or query parameter authentication
