# Spec Change: API Key MCP Hub

## Affected Spec Areas

- `docs/master/product/features/communication-hub.md` — API key authentication mode and `load_skills` tool
- `docs/master/product/features/mcp-hub.md` — Third-party agent access via API keys
- `docs/master/product/features/skill-management.md` — Skill version tracking with `updated_at` timestamps
- `docs/master/product/features/agent-identity.md` — API keys as an alternative authentication method for external agents
- `docs/master/product/features/agent-runtime-security.md` — API key security model (hashed storage, token isolation)

## New Capabilities

- **API Key Management (Web UI)** — A new "API Keys" management page under the Agents or Integrations section. Platform Administrators can create API keys bound to agent identity + role, view the key list with status filtering, and revoke keys. The clear-text key is shown only once at creation.

- **API Key Authentication (Communication Hub)** — Communication Hub accepts API keys via Bearer token or query parameter for MCP endpoint authentication. Validates keys by calling Control Center's internal API. Resolves the bound agent identity, role, and permissions. Injects the identity token into proxied MCP requests without exposing it to the external agent.

- **`load_skills` System Tool** — A new system tool on the Communication Hub that returns all skills (including SOPs) an agent is permitted to access, with full tool definitions, input/output schemas, and `updated_at` timestamps. Supports an optional `since` parameter for incremental sync.

- **Skill Version Tracking** — Skills carry an `updated_at` timestamp that changes whenever the skill definition is modified. This enables external agents to cache skills locally and only re-download those that have changed since their last sync.

## Modified Capabilities

- **Communication Hub Authentication** — Before: only mTLS certificate-based authentication for agent connections. After: supports both mTLS certificate authentication (for internal Agent Runtime) and API key authentication (for external third-party agents). Certificate-based auth path is unchanged.

- **Skill Model** — Before: skills have no versioning metadata. After: each skill records an `updated_at` timestamp that updates when the skill definition changes. Existing skills without timestamps will have `updated_at` backfilled to their creation time.

- **Permission Enforcement** — Before: tool access permission resolution occurs only for certificate-authenticated internal agents. After: the same permission resolution path is used for API-key-authenticated external agents, routing through Control Center identically.

## Removed Capabilities

_None._ This change is purely additive. No existing capabilities are removed or deprecated.

## Spec Update Instructions

- Update `docs/master/product/features/communication-hub.md`:
  - Add section on API key authentication mode (alongside existing certificate-based auth)
  - Document the `load_skills` system tool with its purpose and parameters
  - Note that external agents never receive identity tokens

- Update `docs/master/product/features/mcp-hub.md`:
  - Add mention that the MCP Hub now supports third-party agent connections via API keys
  - Clarify that API-key-authenticated agents use the same tool repository and permission model

- Update `docs/master/product/features/skill-management.md`:
  - Add `updated_at` timestamp to skill definition metadata
  - Document version tracking behavior: timestamps change on skill definition updates
  - Note that `load_skills` supports incremental sync via the `since` parameter

- Update `docs/master/product/features/agent-identity.md`:
  - Add API keys as an alternative authentication credential for external agents
  - Document the binding relationship: API key → agent identity → agent role → permissions

- Add new feature spec `docs/master/product/features/api-key-management.md`:
  - Describe the API key CRUD management page in the Web UI
  - Document key lifecycle: creation (one-time display), active use, revocation
  - Security model: keys are hashed at rest in Control Center's database, validated via internal API
