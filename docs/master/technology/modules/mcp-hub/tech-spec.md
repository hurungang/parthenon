# Module: mcp-hub — Tech Spec

## Overview

The MCP Hub module is the canonical integration boundary between the Parthenon platform and all external MCP (Model Context Protocol) tool servers. It handles registration and configuration of MCP servers, periodic synchronisation of each server's tool catalogue into the platform database under a unique server slug namespace, management of named sessions with encrypted credential storage and per-session identity binding and credential configuration (including an explicit `is_default` flag for default session resolution), permission granting at the tool level, proxying of tool-call invocations from agents to the correct external server with automatic credential injection, and a cross-server Tool Repository view with skill association mapping.

A built-in **System** MCP server (reserved slug `system`) is seeded in the database at startup and surfaced as a virtual entry in the server list. The System server carries the platform-native **general** tools (`save_data`, `get_data`, `get_output`, `query_result`, notification tools, `human_intervene`, optimization/script tools); management-category tools moved to a separate per-tenant **Control Center** entity (reserved slug `cc`, see below). The virtual `decision` entity appears alongside it. The server list deduplicates the DB-seeded System entry so that exactly one System entry appears.

Synchronisation (`POST /mcp/servers/{id}/sync`) is hardened: non-fatal initialise-handshake failures are captured as warnings (partial success returns 200 with warnings), session-gating returns 422 when a server has zero sessions, and complete failure returns 502 only when tools/list is unreachable. Default session resolution uses the explicit `is_default` flag (with sole-active-session auto-fallback) across sync, tool test, and proxy call paths.

**OAuth session health.** Token-refresh failures are classified. An *unrecoverable* failure — the provider reports the refresh token is invalid, revoked, or gone (`invalid_grant`, "no such refresh token", etc.) — sets `requires_reauth` and stores a truncated `last_refresh_error` on the session instead of silently deactivating it. Transient failures keep the existing retry/health-state path. A successful refresh clears both fields, and re-authenticating a session in place (the existing session row is updated, not replaced) clears them as well.

---

## Key Components

### Backend

| Component | Description |
|-----------|-------------|
| `McpServerRouter` | FastAPI router for full CRUD operations on registered MCP servers (excluding the reserved `system` slug) and the manual tool sync trigger endpoint |
| `McpSessionRouter` | FastAPI router for creating, updating, and deleting named sessions on an MCP server; handles encrypted credential storage via the Credential Vault; persists and returns `identity_binding`, `credential_config`, and `is_default` |
| `McpToolRouter` | FastAPI router for per-server tool listing and role-based permission grants; also exposes global all-tools listing (`GET /mcp/tools`), tool-to-skill reverse mapping (`GET /mcp/tools/{id}/skills`), and tool test endpoint with default-session resolution |
| `ToolSyncService` | Service class that connects to a registered MCP server's HTTP endpoint, retrieves its tool manifest, and upserts tool records into the database namespaced under the server's unique slug; captures non-fatal initialise warnings for surfacing in API responses |
| `McpProxyEngine` | Service class that resolves a tool-call invocation to the correct server session (using `is_default` when no explicit `session_id` is provided), decrypts and injects the scoped credentials at call time (or forwards the caller's agent JWT for passthrough sessions), dispatches the call to the external MCP server, and returns the structured result |
| `OAuthRefreshService` | Service class that manages OAuth2 token refresh lifecycle for MCP sessions with `oauth2` auth type; checks token expiry and performs refresh callbacks; classifies refresh failures — unrecoverable ones set `requires_reauth` + truncated `last_refresh_error`, success clears both; persists `McpSession` health fields and logs via `mcp_session_id` |
| `McpServerRead` | Pydantic read schema for MCP server responses; includes `session_count: int` for sync-gating UI without N+1 session queries |
| `SyncResult` | Pydantic schema returned by the sync endpoint; includes `warnings: list[str]` to surface non-fatal initialise-handshake warnings alongside tool counts |
| `McpServer` | SQLAlchemy model for a registered external MCP tool server; holds the server URL, slug, and connection configuration; the reserved `system` slug server is seeded at startup |
| `McpSession` | SQLAlchemy model for a named session on an MCP server; stores the encrypted credential blob, `identity_binding` (JSON), `credential_config` (JSON), and `is_default` boolean flag for explicit default session resolution; maps the session to an agent identity or role; gains `last_token_refresh_at`, `last_token_refresh_outcome`, `token_health_state`, and the OAuth re-auth state pair `requires_reauth` (bool, default false) + `last_refresh_error` (text, nullable) |
| `McpTool` | SQLAlchemy model for a synced tool; namespaced under the owning server's slug; includes the tool schema and metadata from the last sync |
| `ToolPermission` | SQLAlchemy model granting a specific Role access to a specific MCP tool; the permission-grantable unit for agents |

### Frontend

| Component | Description |
|-----------|-------------|
| `useMcpServers` | React Query hook that fetches and caches the MCP server list |
| `useServerSessions` | React Query hook that fetches sessions for a specific MCP server; returns updated `McpSession` type including `identity_binding`, `credential_config`, and `is_default` |
| `useAllTools` | React Query hook that fetches all active MCP tools across all servers (`GET /mcp/tools`); cache key `['mcp', 'tools']` |
| `useToolSkills` | React Query hook that fetches skills bound to a specific tool (`GET /mcp/tools/{toolId}/skills`); cache key `['mcp', 'tools', toolId, 'skills']` |
| `useServerTools` | React Query hook that fetches tools for a specific server (`GET /mcp/servers/{id}/tools`) |
| `useSyncServer` | Mutation hook for triggering manual tool sync for a server (`POST /mcp/servers/{id}/sync`) |
| `McpHubPage` | Tabbed MCP Hub page: Servers tab (server list with status indicators) and Tool Repository tab; detects System entry with distinct "Built-in" chip and disabled actions; shows session count column; conditional sync button (disabled with tooltip when `session_count === 0`); hosts per-server Sessions dialog |
| `McpServerForm` | Create and edit form for MCP server registration including URL, slug, and connection settings; guards against reserved `system` slug |
| `McpSessionManager` | Named session CRUD UI; fields include auth type, write-only credentials, `identity_binding`, and `credential_config`; displays default session indicator ("Default" chip), radio-button style selection UI for setting default, auto-default info alert for sole sessions, and delete-blocking logic when removing the current default; for `oauth2` sessions with `requires_reauth`, the token status shows the `mcp.sessions.needsReauth` error label with the stored `last_refresh_error` as a tooltip and the re-authenticate action is rendered as a red (error) button; follows Dialog Error Handling Standard |
| `McpToolBrowser` | Tool Repository view: all active tools across all servers grouped by server, with assigned skill chips, search filter, server filter, and active toggle |
| `TestMcpToolDialog` | Dialog for testing tool invocation; shows session selection (or agent identity picker for passthrough sessions); uses `is_default` for default session resolution when no explicit `session_id` is provided |

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/mcp/servers` | List all registered MCP servers; deduplicates System entry (filters DB copy, prepends virtual entry when `offset=0`); eager-loads sessions to compute `session_count` |
| `POST` | `/api/v1/mcp/servers` | Register a new MCP server; guards against reserved `system` slug |
| `GET` | `/api/v1/mcp/servers/{server_id}` | Get MCP server detail |
| `PUT` | `/api/v1/mcp/servers/{server_id}` | Update MCP server configuration |
| `DELETE` | `/api/v1/mcp/servers/{server_id}` | Delete an MCP server |
| `POST` | `/api/v1/mcp/servers/{server_id}/sync` | Trigger manual tool sync; returns **422** when server has zero sessions; resolves default session by `is_default` flag (with sole-active-session auto-fallback); returns **200** with `SyncResult` containing `warnings: [...]` on partial success; returns **502** only on complete failure |
| `GET` | `/api/v1/mcp/servers/{server_id}/tools` | List synced tools for a server |
| `GET` | `/api/v1/mcp/servers/{server_id}/sessions` | List sessions for a server; includes `identity_binding`, `credential_config`, `is_default`, `requires_reauth`, `last_refresh_error` |
| `POST` | `/api/v1/mcp/servers/{server_id}/sessions` | Create a named session; auto-sets `is_default = True` for the server's first session; if `is_default` is explicitly `True`, clears `is_default` on all sibling sessions (at-most-one-default); accepts `identity_binding`, `credential_config`; passthrough auth type skips credential encryption and live test, activates immediately |
| `PUT` | `/api/v1/mcp/servers/{server_id}/sessions/{session_id}` | Update a session; enforces at-most-one-default constraint when `is_default` is set to `True`; accepts `identity_binding`, `credential_config` |
| `DELETE` | `/api/v1/mcp/servers/{server_id}/sessions/{session_id}` | Delete a session; returns **409** if the session is the default and other sessions exist; allows deletion when it is the last session |
| `GET` | `/api/v1/mcp/tools` | List all active tools across all servers, ordered by server name then tool name |
| `GET` | `/api/v1/mcp/tools/{tool_id}/skills` | List all skills bound to a specific tool via `skill_tool_bindings` |
| `GET` | `/api/v1/mcp/tools/{tool_id}/permissions` | List permissions for a tool |
| `POST` | `/api/v1/mcp/tools/{tool_id}/permissions` | Grant tool access to a role |
| `DELETE` | `/api/v1/mcp/tools/{tool_id}/permissions/{permission_id}` | Revoke tool access |
| `POST` | `/api/v1/mcp/tools/{tool_id}/test` | Test a tool call; resolves default session by `is_default` when no explicit `session_id` is provided (supports both passthrough and non-passthrough sessions); `agent_subject` field for passthrough identity resolution (UUID or realm_username); returns `TestToolResponse` with success/error |

---

## Code Reference Map

### Backend — API Layer

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `SYSTEM_SERVER_ID` | constant | UUID of the built-in System MCP server (`00000000-0000-0000-0000-000000000001`) | `backend/app/api/v1/mcp_hub.py` |
| `seed_system_tools` | function | Idempotently seeds System server and platform-native tools into DB at startup | `backend/app/api/v1/mcp_hub.py` |
| `_system_server_read` | function | Returns virtual System server entry (hardcoded `session_count = 0`) | `backend/app/api/v1/mcp_hub.py` |
| `_resolve_default_session` | function | Resolves default session for a server by `is_default` flag (with sole-active-session auto-fallback) | `backend/app/api/v1/mcp_hub.py` |
| `_clear_other_defaults` | function | Clears `is_default` on all sibling sessions for at-most-one-default enforcement | `backend/app/api/v1/mcp_hub.py` |
| `list_mcp_servers` | endpoint | Server list API; filters DB-seeded System entry, prepends virtual entry at `offset=0`, eager-loads sessions for `session_count` | `backend/app/api/v1/mcp_hub.py` |
| `create_mcp_server` | endpoint | Server create endpoint; guards against reserved `system` slug | `backend/app/api/v1/mcp_hub.py` |
| `sync_mcp_server` | endpoint | Sync trigger; session-gating (422), default-session resolution, warning capture on partial success (200), 502 on complete failure | `backend/app/api/v1/mcp_hub.py` |
| `create_mcp_session` | endpoint | Session create; auto-sets `is_default` for first session; enforces at-most-one-default; accepts `identity_binding`, `credential_config` | `backend/app/api/v1/mcp_hub.py` |
| `update_mcp_session` | endpoint | Session update; enforces at-most-one-default; accepts `identity_binding`, `credential_config`, `is_default` | `backend/app/api/v1/mcp_hub.py` |
| `delete_mcp_session` | endpoint | Session delete; returns 409 when deleting default session with siblings; allows last-session deletion | `backend/app/api/v1/mcp_hub.py` |
| `test_mcp_tool` | endpoint | Tool test; resolves default session via `is_default` when no `session_id`; detects passthrough sessions; extracts `request.state.raw_token` for passthrough JWT forwarding; accepts `agent_subject` for passthrough identity resolution | `backend/app/api/v1/mcp_hub.py` |
| `list_all_tools` | endpoint function | Returns all active `McpTool` records across all servers, ordered by server name then tool name | `backend/app/api/v1/mcp_hub.py` |
| `list_tool_skills` | endpoint function | Returns all `Skill` records bound to a given tool via `skill_tool_bindings` | `backend/app/api/v1/mcp_hub.py` |

### Backend — Schemas

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `McpServerRead` | Pydantic schema | Server response schema; includes `session_count: int` for sync-gating UI | `backend/app/schemas/mcp_hub.py` |
| `McpSessionRead` | Pydantic schema | Session response schema; exposes `identity_binding`, `credential_config`, `is_default: bool`, `requires_reauth: bool`, `last_refresh_error: str \| None`; never exposes `encrypted_credentials` | `backend/app/schemas/mcp_hub.py` |
| `McpSessionCreate` | Pydantic schema | Session creation payload; includes `identity_binding`, `credential_config`; optional `is_default: bool`; `@model_validator` rejects credentials when `auth_type` is `passthrough` | `backend/app/schemas/mcp_hub.py` |
| `McpSessionUpdate` | Pydantic schema | Session partial update payload; includes `identity_binding`, `credential_config`; optional `is_default: bool` | `backend/app/schemas/mcp_hub.py` |
| `SyncResult` | Pydantic schema | Sync result response; includes `warnings: list[str]` for non-fatal initialise-handshake warnings | `backend/app/schemas/mcp_hub.py` |
| `TestToolRequest` | Pydantic schema | Tool test request; `session_id` optional (resolved via `is_default` when omitted); `agent_subject` field for passthrough identity resolution (UUID or realm_username) | `backend/app/schemas/mcp_hub.py` |

### Backend — Services

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ToolSyncService` | class | Fetches tool manifest from a registered MCP server and upserts tools under the server slug namespace | `backend/app/services/mcp/tool_sync.py` |
| `ToolSyncService.sync` | method | Main sync method; captures non-fatal initialise warnings for surfacing in API responses | `backend/app/services/mcp/tool_sync.py` |
| `ToolSyncService._initialize_mcp_session` | method | MCP initialise handshake; returns session ID or `None` on failure | `backend/app/services/mcp/tool_sync.py` |
| `McpProxyEngine` | class | Routes tool-call invocations to the correct server session with credential injection; passthrough branch forwards caller JWT instead of decrypting stored credentials | `backend/app/services/mcp/proxy.py` |
| `McpProxyEngine._resolve_session` | method | Resolves session for a tool call; uses `is_default` when no explicit `session_id` is provided | `backend/app/services/mcp/proxy.py` |
| `McpProxyEngine.call_tool` | method | Invokes a tool via JSON-RPC with decrypted credentials; accepts optional `agent_jwt` parameter; raises `McpProxyError` if passthrough session selected but no JWT available | `backend/app/services/mcp/proxy.py` |
| `McpProxyEngine._build_auth_headers` | method | Builds auth headers from decrypted session credentials; passthrough branch injects `agent_jwt` as `Authorization: Bearer` header | `backend/app/services/mcp/proxy.py` |
| `McpProxyError` | exception | Raised when an MCP tool call fails (e.g. missing JWT for passthrough, unreachable server) | `backend/app/services/mcp/proxy.py` |
| `OAuthRefreshService` | class | Manages OAuth2 token refresh lifecycle for MCP sessions; checks token expiry and performs refresh callbacks | `backend/app/services/mcp/oauth_refresh.py` |
| `OAuthRefreshService.refresh_access_token` | method | Refresh call with failure classification: 400/401 responses matching unrecoverable indicators (`invalid_grant`, "no such refresh token", revoked/invalid token) set `requires_reauth` + `last_refresh_error` (truncated to 500 chars); other 400/401 failures keep the deactivation path; success clears both flags | `backend/app/services/mcp/oauth_refresh.py` |
| `handle_oauth_callback` | function | OAuth callback / re-authentication: updates the SAME existing session row in place (credentials, expiry, metadata, `is_active`) and clears `requires_reauth` + `last_refresh_error` | `backend/app/services/mcp_oauth_service.py` |
| `test_mcp_session_connection` | function | Tests connectivity to a session's MCP server; returns immediate success for passthrough auth type without performing a live connection test | `backend/app/services/mcp_session_test.py` |

### Backend — Models & Migrations

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `McpServer` | model | SQLAlchemy model for a registered external MCP tool server; `sessions` relationship used for server list session count | `backend/app/db/models/mcp_hub.py` |
| `McpSession` | model | SQLAlchemy model for a named MCP session; stores encrypted credentials, `identity_binding` (JSON), `credential_config` (JSON), `is_default` boolean flag for explicit default session resolution, and the OAuth re-auth pair `requires_reauth` (bool, default false) + `last_refresh_error` (text, nullable) | `backend/app/db/models/mcp_hub.py` |
| `McpSessionAuthType` | enum | `str` enum — `api_key`, `bearer_token`, `basic_auth`, `oauth2`, `none`, `passthrough` | `backend/app/db/models/mcp_hub.py` |
| `McpTool` | model | SQLAlchemy model for a synced tool namespaced under a server slug | `backend/app/db/models/mcp_hub.py` |
| `ToolPermission` | model | SQLAlchemy model granting a role access to a specific tool | `backend/app/db/models/mcp_hub.py` |
| `add_passthrough_to_mcp_session_auth_type` | migration | Adds `passthrough` to `mcp_session_auth_type_enum`; downgrade is no-op | `backend/alembic/versions/5c2910c238a8_add_passthrough_to_mcp_session_auth_type.py` |
| `add_is_default_to_mcp_sessions` | migration | Adds `is_default` boolean column to `mcp_sessions` table | `backend/alembic/versions/6beca08c57cf_add_is_default_to_mcp_sessions.py` |
| `add_requires_reauth_to_mcp_sessions` | migration | Adds `requires_reauth` (bool, not null, default false) and `last_refresh_error` (text, nullable) to `mcp_sessions`; reversible | `backend/alembic/versions/903e79b3fac9_add_requires_reauth_to_mcp_sessions.py` |

### Frontend — Types

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `McpServer` (TypeScript) | interface | Frontend type for MCP server; includes `session_count: number` for sync gating | `frontend/src/types/index.ts` |
| `McpSession` (TypeScript) | interface | Frontend type for MCP session; includes `is_default: boolean`, `identity_binding`, `credential_config`, `requires_reauth: boolean`, `last_refresh_error: string \| null` | `frontend/src/types/index.ts` |

### Frontend — Hooks

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `useMcpServers` | hook | React Query hook for fetching and caching the paginated MCP server list | `frontend/src/hooks/useMcpServers.ts` |
| `useSyncServer` | hook | Mutation hook for triggering manual tool sync for a server | `frontend/src/hooks/useMcpServers.ts` |
| `useServerSessions` | hook | React Query hook for fetching sessions for a specific MCP server; includes `is_default`, `identity_binding`, `credential_config` | `frontend/src/hooks/useMcpServers.ts` |
| `useServerTools` | hook | React Query hook for fetching synced tools for a specific server | `frontend/src/hooks/useMcpServers.ts` |
| `useAllTools` | hook | React Query hook fetching all active tools across all servers; cache key `['mcp', 'tools']` | `frontend/src/hooks/useMcpServers.ts` |
| `useToolSkills` | hook | React Query hook fetching skills bound to a specific tool; cache key `['mcp', 'tools', toolId, 'skills']` | `frontend/src/hooks/useMcpServers.ts` |

### Frontend — Components

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `McpHubPage` | component | Tabbed MCP Hub: Servers tab + Tool Repository tab; System entry detection with "Built-in" chip and disabled actions; session count column; conditional sync button (disabled with tooltip when `session_count === 0`); hosts per-server Sessions dialog | `frontend/src/pages/mcp/McpHubPage.tsx` |
| `McpServerForm` | component | Create/edit form for MCP server registration; guards against reserved `system` slug | `frontend/src/pages/mcp/McpServerForm.tsx` |
| `McpSessionManager` | component | Session CRUD UI with auth type, write-only credentials, `identity_binding`, `credential_config`; default session indicator ("Default" chip), radio-button selection UI for setting default, auto-default info alert for sole sessions, delete-blocking when removing current default; `requires_reauth` renders the `mcp.sessions.needsReauth` token status (error colour) with `last_refresh_error` as tooltip and a red re-authenticate action; passthrough: credential fields hidden, info Alert shown, Passthrough chip in table; follows Dialog Error Handling Standard | `frontend/src/pages/mcp/McpSessionManager.tsx` |
| `TestMcpToolDialog` | component | Tool test dialog; shows session selection resolved via `is_default`; shows agent identity picker instead of session picker for passthrough sessions; sends `agent_subject` in payload for passthrough; agent identities fetched from `/agents/identities` | `frontend/src/pages/mcp/TestMcpToolDialog.tsx` |
| `McpToolBrowser` | component | Tool Repository: all tools grouped by server with skill chips, search filter, server filter, active toggle | `frontend/src/pages/mcp/McpToolBrowser.tsx` |

### Test Files

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_mcp_hub_api.py` | test module | API integration tests for MCP Hub endpoints | `backend/tests/api/v1/test_mcp_hub_api.py` |
| `test_mcp_hub.py` (unit) | test module | Unit tests for MCP Hub services including sync resilience scenarios | `backend/tests/unit/test_mcp_hub.py` |
| `test_mcp_session.py` | test module | Unit tests for MCP session schemas (`is_default`, `session_count` validation) | `backend/tests/unit/test_mcp_session.py` |
| `test_mcp_proxy.py` | test module | Unit tests for `McpProxyEngine`; includes session resolution and passthrough auth scenarios | `backend/tests/unit/test_mcp_proxy.py` |
| `test_mcp_hub.py` (integration) | test module | Integration tests for MCP Hub business logic | `backend/tests/integration/test_mcp_hub.py` |
| `test_oauth_refresh_classification` | test module | Refresh-failure classification: unrecoverable indicator sets `requires_reauth` + `last_refresh_error`, transient failure leaves both unset, successful refresh clears both | `backend/tests/services/test_oauth_refresh_classification.py` |
| `McpSessionManager.test` | test module | Component tests for `McpSessionManager`; includes passthrough UI, default session selection, and the red re-authenticate action for expired/unrecoverable OAuth refresh tokens | `frontend/src/__tests__/McpSessionManager.test.tsx` |
| `TestMcpToolDialog.test` | test module | Component tests for `TestMcpToolDialog`; includes identity picker for passthrough, session picker for standard sessions | `frontend/src/__tests__/TestMcpToolDialog.test.tsx` |
| `mcp-hub.spec.ts` | test module | E2E tests for MCP Hub UI flows | `e2e/tests/mcp-hub.spec.ts` |
| `mcp-tool-validation.spec.ts` | test module | E2E tests for MCP tool validation | `e2e/tests/mcp-tool-validation.spec.ts` |

### i18n

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `mcp.sessions.passthrough` | i18n key | Display label for passthrough auth type chip in session table | `frontend/src/i18n/locales/en.json` |
| `mcp.sessions.passthroughInfo` | i18n key | Informational Alert text shown when passthrough auth type is selected | `frontend/src/i18n/locales/en.json` |
| `mcp.sessions.needsReauth` | i18n key | Token-status label ("Needs re-authentication") for sessions whose refresh token is unrecoverable | `frontend/src/i18n/locales/en.json` |

## Strict Tenant Isolation (as-built — strict-tenant-isolation change)

MCP hub identity is per-tenant `(tenant, slug)`, not platform-wide:

- `McpServer.slug` is unique **per tenant** (business identity `(tenant_id, slug)`); the platform-wide slug constraint was dropped by migration `b8c9d0e1f2a3`.
- `McpTool` carries a denormalized `tenant_id` stamped from its owning server at sync time; `ToolSyncService` upserts are tenant-bound.
- `ToolPermission` grants and skill bindings enforce same-tenant containment: a grant in tenant A never authorizes tenant B's same-named tool. The `server____tool` wire format is unchanged — tenant qualification happens at resolution time only.
- Resolution of `server____tool` names at runtime is tenant-filtered and fails closed (see the [multi-tenancy spec](../multi-tenancy/tech-spec.md) and [agent-runtime spec](../agent-runtime/tech-spec.md)).

### As-built Code Reference Map additions

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `McpServer.slug` per-tenant uniqueness | model behaviour | Slug unique per tenant; tenant mandatory | `backend/app/db/models/mcp_hub.py` |
| `McpTool.tenant_id` | column | Denormalized tenant binding stamped at sync time | `backend/app/db/models/mcp_hub.py` |
| `ToolSyncService` (tenant-bound) | class behaviour | Tool sync upserts stamp the server's tenant on every tool row | `backend/app/services/mcp/tool_sync.py` |
| `ToolRegistryBridge.build_catalog` | method | Per-tenant tool catalogue: caller's tenant MCP tools + tenant decision tools, no cross-tenant names | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `ToolRegistryBridge.dispatch` | method | Tenant-contained dispatch: the tool must exist in the caller's tenant before forwarding | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `AgentPermissionManager` | class | Role→tool resolution with same-tenant containment — a binding resolved for a role only surfaces tools of the role's own tenant | `backend/app/services/agents/permission_manager.py` |
| `build_langchain_tools_for_ar_path` | function | Builds the AR tool set with tenant-aware `server____tool` / `agent____<slug>` resolution | `backend/app/services/agents/langchain_tool_wrapper.py` |
| `_extract_delegation_target_slug` | function | Parses `agent____<slug>`; wire format unchanged, resolution `(tenant, slug)` | `backend/app/services/agents/langchain_tool_wrapper.py` |
| `build_tool_name` / `parse_tool_name` / `RESERVED_SERVER_NAMES` | functions + constant | `server____tool` wire format unchanged; call sites tenant-qualified | `backend/app/services/agents/tool_naming.py` |
| Adoption migration (MCP part) | migration | Drops the platform-wide `McpServer.slug` constraint; adopts MCP rows into root; realigns `McpTool.tenant_id` with its server | `backend/alembic/versions/b8c9d0e1f2a3_per_tenant_entity_adoption_and_mcp_slug_scoping.py` |

---

## Control Center MCP entity (`cc`) — lifecycle, permission gating and catalog contract (control-center-chatbot change)

Every tenant owns a platform-provisioned **Control Center** MCP entity (slug `cc`) hosting that tenant's `cc____<bare>` management tools. It is the grant anchor for the Control Center Assistant's management surface (agent-side details: [agents module](../agents/tech-spec.md); OAuth plane: [comm-hub module](../comm-hub/tech-spec.md)).

**Platform-provisioned and idempotent.** `AssistantSeeder` is the only writer: name, description, base URL and status drift are refreshed at seed time. The slug can never drift because the router reserves it.

**Two distinct controls, never conflated.**
- **Immutability** (`_reject_cc_mutation`) is not a permission question: update / delete / sync / OAuth authorize return a structured `403 {"code": "system_managed_integration"}` for everyone — including `integration::control_center:manage` holders and `integration::*` wildcards.
- **Entity-view permission** governs who can *see* and *configure around* it: `integration::control_center` with actions `read` (see the entity and its tools) and `manage` (grants, sessions, rebinding, configuration). Deny-by-default; existing `integration::*` / `*::*` wildcards cover admins because the type is registered in `MODULE_GROUPS["integration"]`.
- **Tool grants on `cc` tools are exempt** from immutability — they stay governed solely by the read/manage gate.

**Sessionless.** MCP sessions do not apply to `cc` (access flows through role/skill grants): session create/update/delete/refresh-token return a structured 403; session LIST stays allowed (harmless).

### Models, gating and API surface

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `SYSTEM_MANAGED_SERVER_SLUGS` | constant (new) | `{"system", "decision", "cc"}` — the marking convention for platform-provisioned entities (no new DB column) | `backend/app/db/models/mcp_hub.py` |
| `McpServerRead.is_system_managed` | schema field (new) | Derived from the slug and exposed on every server read so the UI needs no slug logic | `backend/app/schemas/mcp_hub.py` |
| `_require_cc_permission` / `_cc_visible` | functions (new) | Non-raising and raising variants of the entity-view gate using `identity_has_permission` | `backend/app/api/v1/mcp_hub.py` |
| `_gate_cc_server` | function (new) | **404-without-leak** for `cc` detail/tools reads without `read`; structured 403 for `cc` mutations without `manage` | `backend/app/api/v1/mcp_hub.py` |
| `_reject_cc_mutation` | function (new) | Unconditional immutability guard for update/delete/sync/OAuth-authorize (and `sessions=True` for session mutations); runs BEFORE the manage gate | `backend/app/api/v1/mcp_hub.py` |
| `_cc_tool_gate` | function (new) | Tool-grant surface gate on `cc` tools: `GET .../permissions` needs `read`, `POST`/`DELETE` grants need `manage` | `backend/app/api/v1/mcp_hub.py` |
| `identity_has_permission` | dependency helper (new) | Non-raising permission probe used for filtering (list endpoints) instead of raising per row | `backend/app/api/deps.py` |
| `seed_system_tools` (retirement) | function (modified) | Also retires the System entity's legacy `system____<mgmt>` rows idempotently (pure SQL — reserved all-digit UUIDs coerce under SQLite's NUMERIC affinity) | `backend/app/api/v1/mcp_hub.py` |
| `McpHubPage` (gating) | component (modified) | API-filtered list hides `cc` entirely without `read`; when visible the row carries a "Control Center" protected chip and, for system-managed entities, a "System-managed" chip with edit/delete/sync/session controls hidden while grant controls stay for `manage` holders; row-level 403s surface via `PermissionDeniedAlert` | `frontend/src/pages/mcp/McpHubPage.tsx` |
| `mcp.controlCenter.*` | i18n keys | Protected / system-managed chip labels | `frontend/src/i18n/locales/en.json` |

### Catalog listing contract

`GET /mcp/tools` and `GET /mcp/servers` are complete and stable: no item can be lost or duplicated across pages, and ordering never depends on DB/insertion order.

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `list_all_tools` | endpoint (modified) | Assembles system + decision (tenant) + DB tools, applies the `cc` permission filter, dedupes by id, sorts the **full** set by `(server_slug, name, id)`, then slices `[offset:offset+limit]` (default/cap 200); `X-Total-Count` = deduped total | `backend/app/api/v1/mcp_hub.py` |
| `list_mcp_servers` | endpoint (modified) | Virtual `system`/`decision` exclusion and the `cc` filter are applied **in the query** (never after pagination), DB rows ordered `(name, id)`; the requested window maps onto the DB offset/limit because virtual servers occupy slots 0–1; `X-Total-Count` = DB total + 2 | `backend/app/api/v1/mcp_hub.py` |
| `get_mcp_tool` | endpoint (new) | `GET /mcp/tools/{tool_id}`: resolves DB tools plus virtual system/decision ids. A `cc` tool is visible WITHOUT `integration::control_center:read` only when a skill binding of the caller's tenant references that exact tool; otherwise 404-without-leak. Never exposes the `cc` catalogue | `backend/app/api/v1/mcp_hub.py` |
| `_tool_referenced_by_skill` | function (new) | Tenant-scoped existence check backing the single-tool visibility rule | `backend/app/api/v1/mcp_hub.py` |
| CORS `expose_headers` | config (modified) | Exposes `X-Total-Count` so the browser can page on the true total | `backend/app/main.py` |
| `useAllTools()` / `useMcpServers()` (no-arg) | hooks (modified) | Page the complete set in 200-item pages until a short page (safety cap 50 pages); the `(limit, offset)` overloads keep their single-request semantics for `McpToolBrowser` | `frontend/src/hooks/useMcpServers.ts` |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_cc_integration_permission` | test | `integration::control_center` gating: 404-without-leak reads, structured 403 writes, wildcard coverage, unconditional immutability, sessionless refusals, `is_system_managed` derivation | `backend/tests/unit/test_cc_integration_permission.py` |
| `useMcpServers.pagination` | frontend test | Multi-page completion, ordering stability, short-page termination | `frontend/src/__tests__/useMcpServers.pagination.test.tsx` |
| `McpHubPage.test` | frontend test | `cc` hiding/showing, protected + system-managed chips, disabled controls for manage holders | `frontend/src/__tests__/McpHubPage.test.tsx` |
