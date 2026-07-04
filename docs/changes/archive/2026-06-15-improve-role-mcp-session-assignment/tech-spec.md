# Technical Specification: Improve Role MCP Session Assignment

## 1. Technical Overview

The `AgentRoleDialog` is refactored to compute required MCP servers client-side from selected SOPs/Skills, render inline session dropdowns per required server, and integrate session assignment into the role save flow (create and edit). The separate `AssignMcpSessionsToRoleDialog` popup is removed entirely. No backend API changes are required — all needed endpoints already exist. The frontend orchestrates session assignment after role persistence in create mode (role must exist before sessions can be assigned), and performs diff-based add/remove in edit mode.

The dependency chain is: **selected SOP → required skills → skill tool_ids → McpTool records → server slug** (extracted from tool name via `server____tool` convention). System tools (`system____*`) are excluded. Server slugs are deduplicated into a set of required MCP servers, each rendered as an inline labeled section with a dropdown populated from `GET /mcp/servers/{serverId}/sessions`.

---

## 2. Component Breakdown

### 2.1 Removed Components

| Component | Reason |
|-----------|--------|
| `AssignMcpSessionsToRoleDialog` | Replaced by inline dropdowns in `AgentRoleDialog` |
| `AssignMcpSessionsToRoleDialog.test.tsx` | Component no longer exists |

### 2.2 Modified Components

**`AgentRoleDialog`** (`frontend/src/pages/agents/AgentRoleDialog.tsx`)
- **Responsibility:** Full lifecycle of role create/edit including inline MCP session assignment
- **Removed:** Assign MCP Sessions button, assigned MCP sessions table, `assignedMcpSessions` query, `refetchMcpSessions`, `handleRemoveMcpSession`, `assignMcpDialogOpen` state, `AssignMcpSessionsToRoleDialog` import and JSX
- **Added:**
  - `requiredMcpServers: string[]` — computed via `useMemo` from selected SOPs/Skills, resolved through skill tool_ids → McpTool → server slug
  - `selectedMcpSessions: Record<string, string>` — maps `server_slug → session_id`
  - `useQueries` batch to fetch `useServerSessions(serverId)` per required server
  - Inline MCP session dropdown sections (one per required server) with Refresh button
  - Pre-save validation: Save disabled when any required server lacks a session
  - Save integration: create mode (save role → assign sessions); edit mode (save role → diff sessions)
  - Dialog Error Handling Standard compliance: `dialogError` state, `PermissionDeniedAlert` rendering

### 2.3 New Internal Logic (no new files)

No new component files are created. The inline dropdown rendering and server computation logic live within `AgentRoleDialog.tsx` to keep the implementation contained and avoid premature abstraction. If complexity warrants, the server-computation utility or the inline dropdown could be extracted later, but for this change the logic stays inline.

---

## 3. API Changes

No new endpoints. No backend changes. All APIs already exist.

### 3.1 Existing Endpoints Used (Read)

| Method | Path | Used For | Called By |
|--------|------|----------|-----------|
| `GET` | `/mcp/servers` | List all MCP servers (slug→id mapping) | `useMcpServers()` (new call in dialog) |
| `GET` | `/mcp/servers/{serverId}/sessions` | Available sessions per required server | `useServerSessions(serverId)` (via `useQueries` batch) |
| `GET` | `/mcp/tools` | All MCP tools (tool ID → server_id/name mapping) | `useAllTools()` (already called in dialog) |
| `GET` | `/agents/roles/{roleId}/mcp-sessions` | Currently assigned sessions (edit mode pre-population) | `useQuery` (replaces old assigned query) |

### 3.2 Existing Endpoints Used (Write)

| Method | Path | Used For | Called By |
|--------|------|----------|-----------|
| `POST` | `/agents/roles` | Create new role | `handleSave` (create mode) |
| `PUT` | `/agents/roles/{roleId}` | Update existing role | `handleSave` (edit mode) |
| `POST` | `/agents/roles/{roleId}/mcp-sessions` | Assign session to role | `handleSave` (after role create/update) |
| `DELETE` | `/agents/roles/{roleId}/mcp-sessions/{sessionId}` | Remove session from role | `handleSave` (edit mode diff remove) |

### 3.3 Endpoints No Longer Called

| Method | Path | Reason |
|--------|------|--------|
| `GET` | `/agents/roles/{roleId}/available-mcp-sessions` | Replaced by client-side computation + per-server session fetch |

The `available-mcp-sessions` endpoint remains on the backend but is no longer called from the frontend. It can be deprecated in a future cleanup if no other consumers exist.

---

## 4. State Management

### 4.1 Component State (`AgentRoleDialog`)

| State Variable | Type | Purpose |
|---------------|------|---------|
| `selectedMcpSessions` | `Record<string, string>` | Maps `server_slug → mcp_session_id` for currently selected sessions |
| `[existing] selectedSopIds` | `string[]` | Selected SOP IDs (existing state, triggers recomputation) |
| `[existing] selectedSkillIds` | `string[]` | Selected Skill IDs (existing state, triggers recomputation) |
| `[existing] lockedSkills` | `Set<string>` | Auto-selected skills from SOP requirements (triggers recomputation) |
| `[existing] dialogError` | `unknown` | Per Dialog Error Handling Standard |

### 4.2 Derived State (useMemo)

| Derived Value | Computation | Dependencies |
|--------------|-------------|-------------|
| `requiredMcpServers` | Collect all effective skill IDs (direct + locked) → skill tool_ids → `McpTool` lookup in `allTools` → extract server slug from tool name (split on `____`, exclude `"system"`) → deduplicate | `selectedSopIds`, `selectedSkillIds`, `lockedSkills`, `skills`, `allTools`, `sops` |
| `isSaveDisabled` | `!name.trim() \|\| requiredMcpServers.some(s => !selectedMcpSessions[s])` | `name`, `requiredMcpServers`, `selectedMcpSessions` |
| `missingServers` | `requiredMcpServers.filter(s => !selectedMcpSessions[s])` — used for inline validation message | `requiredMcpServers`, `selectedMcpSessions` |

### 4.3 Server State (React Query)

| Query | Key Pattern | Data | Enabled Condition |
|-------|------------|------|-------------------|
| `useMcpServers()` | `['mcp', 'servers', 0, 0]` | `McpServer[]` (id, slug, name) | `open` (dialog is open) |
| `useAllTools()` | `['mcp', 'tools', ...]` | `McpTool[]` (id, name, server_id) | `open` (already exists in dialog) |
| `useQueries(useServerSessions)` | `['mcp', 'servers', serverId, 'sessions']` × N | `McpSession[]` per server | Derived from `requiredMcpServers`, only for servers that are currently required |
| `useQuery(get assigned sessions)` | `['agents', 'roles', roleId, 'mcp-sessions']` | Currently assigned `McpSessionInfo[]` | `open && !!editRole?.id` (edit mode only) |

### 4.4 Data Flow

```
User selects/deselects SOP/Skill checkboxes
  → selectedSopIds / selectedSkillIds / lockedSkills update
  → requiredMcpServers recomputes
  → new servers trigger useQueries for session data
  → inline dropdowns appear/disappear
  → selectedMcpSessions may lose entries for removed servers
  → isSaveDisabled recomputes

User clicks Save:
  → Pre-check: all required servers have sessions (Save disabled if not)
  → Create: POST /agents/roles → POST per-session assignments
  → Edit: PUT /agents/roles/{id} → diff POST/DELETE per-session assignments
  → On success: call onSaved() → parent invalidates queries → dialog closes
  → On error: setDialogError(err) → PermissionDeniedAlert renders
```

---

## 5. Data Access Patterns

### 5.1 MCP Server Requirement Computation

**Pattern:** Pure client-side graph traversal

**Input types:** `Sop[]`, `Skill[]`, `McpTool[]`, selected IDs, locked skill IDs

The computation is idempotent and deterministic. It uses no network calls — all data (`sops`, `skills`, `allTools`) is already loaded via React Query at dialog open.

The effective skill ID set = `selectedSkillIds ∪ lockedSkills`. For each skill, `Skill.tool_ids` identifies tools. Each `McpTool` has a `name` following the `slug____tool_name` convention (or legacy `slug/tool_name`). The slug segment is extracted, "system" slugs are excluded, and the result is deduplicated.

### 5.2 Session Data Fetching

**Pattern:** Conditional parallel queries via `useQueries`

For each slug in `requiredMcpServers`:
1. Resolve slug → `server_id` using `McpServer[]` from `useMcpServers()`
2. Execute `useServerSessions(serverId)` only when `serverId` is resolved
3. Combine results into a map: `sessionsBySlug: Record<string, McpSession[]>`

`useQueries` accepts a list of query options built from the computed server list. Each query is independently loading/error/success.

### 5.3 Save-Time Session Diff (Edit Mode)

**Pattern:** Compare pre-edit assignments vs. post-edit selections

Pre-edit assigned sessions are loaded at dialog open via `GET /agents/roles/{roleId}/mcp-sessions`. This returns `McpSessionInfo[]` with `id`, `server_slug`, etc. A snapshot is taken on open.

On save:
- `toAdd = selectedMcpSessions values not in pre-edit assigned session IDs`
- `toRemove = pre-edit assigned session IDs not in selectedMcpSessions values`
- Sequential `POST` for each `toAdd`, sequential `DELETE` for each `toRemove`

### 5.4 Save-Time Session Assignment (Create Mode)

**Pattern:** Two-phase: create role, then assign sessions

1. `POST /agents/roles` → returns new role with `id`
2. For each entry in `selectedMcpSessions`: `POST /agents/roles/{id}/mcp-sessions`
3. All requests in step 2 are sequential to avoid race conditions on the backend unique constraint

### 5.5 Refresh Pattern

**Pattern:** Per-server query invalidation

Refresh button calls `queryClient.invalidateQueries({ queryKey: ['mcp', 'servers', serverId, 'sessions'] })` for the specific server. On refetch completion, the `useEffect` or a callback checks if the previously selected session still exists in the new data. If not, the selection for that server is cleared.

### 5.6 Error Pattern

**Pattern:** Dialog Error Handling Standard

All async operations in `handleSave` and the session refresh flow are wrapped in try-catch. Errors are set via `setDialogError(err)`. The existing `PermissionDeniedAlert` component renders at the top of `DialogContent` when `dialogError` is non-null. Individual server session fetch errors are handled per-server with inline error messages and retry buttons.

---

## 6. Code Reference Map

### 6.1 Frontend — Pages

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `AgentRoleDialog` | component | **MODIFIED**: Inline MCP session dropdowns replace separate popup; session assignment integrated into save flow; pre-save validation blocks incomplete configurations; passthrough badge displayed on server labels; `extractServerSlug` helper extracts server slug from tool names via `slug____tool` convention, excluding system tools | `frontend/src/pages/agents/AgentRoleDialog.tsx` |
| `AgentRoleListPage` | component | Unchanged: passes `onSaved` that invalidates roles query | `frontend/src/pages/agents/AgentRoleListPage.tsx` |
| `AssignMcpSessionsToRoleDialog` | component | **REMOVED** — replaced by inline dropdowns in `AgentRoleDialog` | `frontend/src/pages/agents/AssignMcpSessionsToRoleDialog.tsx` (deleted) |

### 6.2 Frontend — Hooks

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `useMcpServers` | hook | Fetches `McpServer[]`; used to resolve slug→server_id mapping | `frontend/src/hooks/useMcpServers.ts` |
| `useAllTools` | hook | Fetches all `McpTool[]`; used to resolve tool_id→tool name for slug extraction | `frontend/src/hooks/useMcpServers.ts` |
| `useServerSessions` | hook | Fetches `McpSession[]` for a single server; called via `useQueries` per required server | `frontend/src/hooks/useMcpServers.ts` |
| `useDialogErrorHandler` | hook | Standard dialog error state management (already in use or pattern followed) | `frontend/src/hooks/useDialogErrorHandler.ts` |

### 6.3 Frontend — Types

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `AgentRole` | interface | `id`, `name`, `description`, `sop_ids`, `skill_ids` | `frontend/src/types/index.ts` |
| `Sop` | interface | `id`, `name`, `required_skill_ids?` | `frontend/src/types/index.ts` |
| `Skill` | interface | `id`, `name`, `tool_ids` | `frontend/src/types/index.ts` |
| `McpTool` | interface | `id`, `server_id`, `name`, `original_name`, `description`, `input_schema` | `frontend/src/types/index.ts` |
| `McpSession` | interface | `id`, `server_id`, `name`, `auth_type: McpSessionAuthType` | `frontend/src/types/index.ts` |
| `McpSessionAuthType` | type | `'api_key' \| 'bearer_token' \| 'basic_auth' \| 'oauth2' \| 'none' \| 'passthrough'` | `frontend/src/types/index.ts` |
| `McpServer` | interface | `id`, `slug`, `name` | `frontend/src/types/index.ts` |
| `McpSessionInfo` (local) | interface | `id`, `name`, `server_id`, `server_name`, `server_slug`, `auth_type` | Defined locally in dialog |

### 6.4 Frontend — Utilities

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `canonicalizeToolName` | function | Normalizes tool name to `slug____tool` format; reference for slug extraction pattern | `frontend/src/utils/toolNaming.ts` |
| `extractServerSlug` | function | **NEW**: Extracts MCP server slug from tool name; excludes system tools (`system____*`); handles legacy slash format; defined in `AgentRoleDialog.tsx` | `frontend/src/pages/agents/AgentRoleDialog.tsx` |

### 6.5 Frontend — Components

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `PermissionDeniedAlert` | component | Renders permission-denied and generic API error alerts; used for save-time error display | `frontend/src/components/permissions/PermissionDeniedAlert.tsx` |

### 6.6 Frontend — API Client

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `apiClient` | AxiosInstance | Configured axios client with auth token injection and 401/403 interceptors | `frontend/src/api/apiClient.ts` |
| `API_CONFIG` | constant | `BASE_URL`, `TIMEOUT_MS` | `frontend/src/api/API_CONFIG.ts` |

### 6.7 Frontend — i18n

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `agents.roles.mcpSessionAssignment` | key | Section title: "MCP Session Assignment" | `frontend/src/i18n/locales/en.json` |
| `agents.roles.mcpSessionAssignmentHint` | key | Helper text explaining the assignment requirement | `frontend/src/i18n/locales/en.json` |
| `agents.roles.mcpSessionRequired` | key | "Session required" label | `frontend/src/i18n/locales/en.json` |
| `agents.roles.mcpSessionMissing` | key | "Missing session assignment for:" prefix | `frontend/src/i18n/locales/en.json` |
| `agents.roles.mcpSessionRefresh` | key | Refresh button aria-label: "Refresh sessions" | `frontend/src/i18n/locales/en.json` |
| `agents.roles.mcpSessionLoadError` | key | "Failed to load sessions" error message | `frontend/src/i18n/locales/en.json` |
| `agents.roles.mcpSessionRetry` | key | "Retry" button label | `frontend/src/i18n/locales/en.json` |
| `agents.roles.mcpSessionNoSessions` | key | "No sessions available for this server" empty state | `frontend/src/i18n/locales/en.json` |
| `agents.roles.mcpSessionLoading` | key | "Loading sessions..." | `frontend/src/i18n/locales/en.json` |
| `mcp.sessions.passthrough` | key | (Reused) "Passthrough" chip label | `frontend/src/i18n/locales/en.json` |
| `app.refresh` | key | (Reused) "Refresh" button label | `frontend/src/i18n/locales/en.json` |

**Removed i18n keys:** `agents.roles.assignedMcpSessions`, `agents.roles.assignMcpSessions`, `agents.roles.assignMcpSessionsTitle`, `agents.roles.assignMcpSessionsHint`, `agents.roles.noAssignedMcpSessions`, `agents.roles.noAvailableMcpSessions`, `agents.roles.removeMcpSession`, `agents.roles.selectedForServer`

### 6.8 Backend — API Endpoints

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `AgentRoleRouter` | APIRouter | Mounts all `/agents/roles` endpoints | `backend/app/api/v1/agents.py` |
| `create_agent_role` | endpoint | `POST /agents/roles` — creates role with SOP/Skill assignments atomically | `backend/app/api/v1/agents.py` |
| `update_agent_role` | endpoint | `PUT /agents/roles/{id}` — replaces SOP/Skill assignments; invalidates permission cache | `backend/app/api/v1/agents.py` |
| `assign_mcp_session_to_role` | endpoint | `POST /agents/roles/{role_id}/mcp-sessions` — one-session-per-server enforced | `backend/app/api/v1/agents.py` |
| `remove_mcp_session_from_role` | endpoint | `DELETE /agents/roles/{role_id}/mcp-sessions/{session_id}` | `backend/app/api/v1/agents.py` |
| `list_role_mcp_sessions` | endpoint | `GET /agents/roles/{role_id}/mcp-sessions` — lists assigned sessions | `backend/app/api/v1/agents.py` |
| `list_available_mcp_sessions_for_role` | endpoint | `GET /agents/roles/{role_id}/available-mcp-sessions` — **no longer called from frontend** (replaced by client-side computation) | `backend/app/api/v1/agents.py` |
| `MCPRouter` (servers) | APIRouter | Mounts `/mcp/servers` and `/mcp/tools` endpoints | `backend/app/api/v1/mcp.py` |

### 6.9 Backend — Services

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `AgentRoleService` | class | `assign_mcp_session()`, `remove_mcp_session()`, `list_mcp_sessions()`, `get_available_mcp_sessions()` | `backend/app/services/agents/role_service.py` |
| `AgentRoleService._set_assignments` | method | Atomically replaces SOP/Skill join records for a role | `backend/app/services/agents/role_service.py` |
| `AgentRoleService.validate_mcp_session_coverage` | method | Checks if all required servers have sessions; returns `{covered, missing_servers}` | `backend/app/services/agents/role_service.py` |

### 6.10 Backend — Models

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `AgentRole` | model | Permission role entity with `sop_assignments` and `skill_assignments` relationships | `backend/app/db/models/agents.py` |
| `AgentRoleSOP` | model | Join: role ↔ SOP | `backend/app/db/models/agents.py` |
| `AgentRoleSkill` | model | Join: role ↔ Skill | `backend/app/db/models/agents.py` |
| `AgentRoleMcpSession` | model | Join: role ↔ MCP session; unique constraint on `(role_id, server_id)` — one session per server per role | `backend/app/db/models/agents.py` |
| `McpServer` | model | MCP server; `slug`, `name` | `backend/app/db/models/mcp_hub.py` |
| `McpSession` | model | MCP session; `server_id`, `name`, `auth_type` (includes `passthrough`) | `backend/app/db/models/mcp_hub.py` |
| `McpTool` | model | MCP tool; `server_id`, `name` in `slug____tool` format | `backend/app/db/models/mcp_hub.py` |
| `Skill` | model | Skill; `tool_ids` via `SkillToolBinding` join | `backend/app/db/models/skills.py` |
| `SkillToolBinding` | model | Join: skill ↔ tool | `backend/app/db/models/skills.py` |

### 6.11 Backend — Utilities

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `parse_tool_name` | function | Parses `slug____tool` names; used server-side in role service for slug extraction | `backend/app/mcp/utils.py` |

### 6.12 Test Files

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `AgentRoleDialog.test` | test | **UPDATED**: Tests for inline dropdowns, pre-save validation, save integration, passthrough display, system tool exclusion, create/assign flow. All 18 tests passing. | `frontend/src/__tests__/AgentRoleDialog.test.tsx` |
| `AssignMcpSessionsToRoleDialog.test` | test | **REMOVED** | `frontend/src/__tests__/AssignMcpSessionsToRoleDialog.test.tsx` (deleted) |

### 6.13 Spec Documents (Master — to be updated post-implementation)

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| Agent Management feature spec | doc | Update "What It Does" and "Acceptance Criteria" to describe inline MCP session assignment | `docs/master/product/features/agent-management.md` |
| MCP Hub feature spec | doc | Add cross-reference noting session assignment is inline in role edit dialog | `docs/master/product/features/mcp-hub.md` |
| Agents tech spec | doc | Mark `AssignMcpSessionsToRoleDialog` REMOVED; update `AgentRoleDialog` description | `docs/master/technology/modules/agents/tech-spec.md` |
| Agents UI test plan | doc | Remove popup test scenarios; add inline dropdown test scenarios | `docs/master/qa/test-plans/agents-ui-test-plan.md` |
| Frontend test plan | doc | Remove `AssignMcpSessionsToRoleDialog.test.tsx` reference | `docs/master/qa/test-plans/frontend-test-plan.md` |
