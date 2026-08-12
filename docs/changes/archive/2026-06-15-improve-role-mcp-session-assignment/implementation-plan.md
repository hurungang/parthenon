# Implementation Plan: Improve Role MCP Session Assignment

## Overview

Replace the disconnected `AssignMcpSessionsToRoleDialog` popup with inline MCP session dropdowns inside `AgentRoleDialog`. Required MCP servers are computed client-side from selected SOPs/Skills, displayed as labeled sections each with a dropdown of available sessions. The Save action is blocked until every required server has a session selected, ensuring every saved role is execution-ready.

---

## Task Checklist

### Phase 1 — Remove Legacy Popup
- [x] 1.1 — Remove `AssignMcpSessionsToRoleDialog` component and its import from `AgentRoleDialog`
- [x] 1.2 — Remove the "Assign MCP Sessions" button and assigned MCP sessions table from `AgentRoleDialog`
- [x] 1.3 — Remove `assignMcpDialogOpen` state, `refetchMcpSessions` query, `handleRemoveMcpSession`, and unused imports

### Phase 2 — Client-Side MCP Server Requirement Computation
- [x] 2.1 — Implement a utility function that, given selected SOP/Skill IDs, resolves to a deduplicated set of required MCP server slugs
- [x] 2.2 — Wire the computation into `AgentRoleDialog` so it re-evaluates whenever `selectedSopIds` or `selectedSkillIds` changes

### Phase 3 — Inline Session Dropdown
- [x] 3.1 — Create an `InlineMcpSessionDropdown` component (or embed logic directly in `AgentRoleDialog`) rendering a labeled dropdown per required server with a Refresh button
- [x] 3.2 — Populate each dropdown with available sessions for its server, fetched via `useServerSessions`
- [x] 3.3 — Bind a `selectedMcpSessions: Record<server_slug, session_id>` state to the dropdowns

### Phase 4 — Pre-Save Validation
- [x] 4.1 — Disable the Save button when any required server has no session selected
- [x] 4.2 — Display an inline validation message listing servers missing session assignments
- [x] 4.3 — On newly-added servers (from SOP/Skill change), prompt the user to assign sessions

### Phase 5 — Save Integration
- [x] 5.1 — In create mode: create role first via `POST /agents/roles`, then assign selected sessions via `POST /agents/roles/{id}/mcp-sessions`
- [x] 5.2 — In edit mode: save role via `PUT`, then diff-assign sessions (add new, remove stale)
- [x] 5.3 — After successful save, invalidate the parent Agent Roles table query and close the dialog

### Phase 6 — Refresh & Error Handling
- [x] 6.1 — Add a Refresh button next to each server's dropdown to refetch sessions via `queryClient.invalidateQueries`
- [x] 6.2 — Preserve current selection if the selected session still exists after refresh; reset if no longer available
- [x] 6.3 — Display inline loading spinner while session data is fetching per server
- [x] 6.4 — Display inline error state with retry option if session fetch fails per server
- [x] 6.5 — Surface save-time backend validation errors via the existing `dialogError` / `PermissionDeniedAlert` pattern

### Phase 7 — Passthrough Sessions
- [x] 7.1 — Identify passthrough sessions by `auth_type === 'passthrough'` and render a "Passthrough" badge/chip next to the server label
- [x] 7.2 — Ensure passthrough sessions remain selectable in the inline dropdown (one-session-per-server constraint does not apply to passthrough)

### Phase 8 — i18n Keys
- [x] 8.1 — Add or reuse i18n keys for: server label with passthrough badge, "Session required" validation, refresh button aria-label, session loading/error states

### Phase 9 — Unit Tests
- [x] 9.1 — Remove `frontend/src/__tests__/AssignMcpSessionsToRoleDialog.test.tsx`
- [x] 9.2 — Update `frontend/src/__tests__/AgentRoleDialog.test.tsx` to reflect the new inline dropdowns
- [x] 9.3 — Add test cases for: MCP server requirement computation, inline dropdown population, pre-save validation blocking save, refresh behaviour, passthrough badge display

### Phase 10 — Cleanup
- [x] 10.1 — Remove unused i18n keys from `en.json` (`agents.roles.assignMcpSessions`, `agents.roles.assignMcpSessionsTitle`, `agents.roles.assignMcpSessionsHint`, `agents.roles.noAvailableMcpSessions`, `agents.roles.selectedForServer`, `agents.roles.removeMcpSession`)
- [x] 10.2 — Verify all TypeScript compilation succeeds with `npx tsc --noEmit`

---

## Phase 1 — Remove Legacy Popup

### 1.1 — Remove `AssignMcpSessionsToRoleDialog` component
Delete `frontend/src/pages/agents/AssignMcpSessionsToRoleDialog.tsx`. Remove the import of `{ AssignMcpSessionsToRoleDialog }` from `AgentRoleDialog.tsx` (line 38). Remove the `<AssignMcpSessionsToRoleDialog ... />` JSX block from the return (lines 637–646). Remove the `assignMcpDialogOpen` state declaration (line 79).

**Done when:** `AssignMcpSessionsToRoleDialog.tsx` file is deleted, no import references remain in `AgentRoleDialog.tsx`, TypeScript compilation succeeds.

### 1.2 — Remove assigned MCP sessions table and "Assign MCP Sessions" button
From `AgentRoleDialog.tsx`, remove the entire "Assigned MCP Sessions table" section (lines 463–519) including the `Divider` above it (line 461). Remove the `assignedMcpSessions` query definition (lines 112–119) and its `refetchMcpSessions` destructuring. Remove `handleRemoveMcpSession` function (lines 240–248).

**Done when:** The MCP sessions table and "Assign MCP Sessions" button are no longer rendered in the dialog; no references to `assignedMcpSessions`, `refetchMcpSessions`, or `handleRemoveMcpSession` remain.

### 1.3 — Remove unused imports and state
Remove unused MUI icon imports: `CloudQueueIcon` (line 28) and `RemoveCircleOutlineIcon` (line 29). Remove `useQueryClient` from React Query imports if it's no longer needed for MCP session queries (verify it's still used for identity refetch — it is, on line 634).

**Done when:** No unused variable warnings, TypeScript compiles clean.

---

## Phase 2 — Client-Side MCP Server Requirement Computation

### 2.1 — Implement utility to compute required MCP servers
Create a pure function in `AgentRoleDialog.tsx` (module scope or inline via `useMemo`):

**Input:** `selectedSopIds: string[]`, `selectedSkillIds: string[]`, `sops: Sop[] | undefined`, `skills: Skill[] | undefined`, `allTools: McpTool[] | undefined`, `lockedSkills: Set<string>`

**Logic:**
1. Collect all effective skill IDs: direct `selectedSkillIds` + skills required by selected SOPs (already tracked in `lockedSkills`).
2. For each skill ID, look up the `Skill` object and collect its `tool_ids`.
3. For each tool ID, find the `McpTool` in `allTools` by matching `tool.id`.
4. Extract the server slug from each tool name using the pattern: split on `____` and take the first segment; exclude `"system"` slugs. For legacy slash-format names, split on `/`.
5. Deduplicate the set of server slugs.

**Output:** `Set<string>` of required server slugs (or `string[]`).

**Done when:** The function correctly maps: selected SOPs → required skills → skill tool_ids → McpTool records → server slugs; system tools are excluded; duplicate slugs are deduplicated; results update correctly when SOP/Skill selection changes.

### 2.2 — Wire computation into `AgentRoleDialog`
Add a `useMemo` that calls the computation whenever `selectedSopIds`, `selectedSkillIds`, `sops`, `skills`, `allTools`, or `lockedSkills` change. Store the result as `requiredMcpServers: string[]`.

**Done when:** Changing SOP/Skill checkboxes causes the computed server list to update; no servers appear when no SOPs/Skills are selected; selecting a SOP that requires skills automatically includes those skills' server dependencies.

---

## Phase 3 — Inline Session Dropdown

### 3.1 — Render inline dropdowns per required server
Below the Skill multi-select section and above the Assigned Identities section, add a new section titled "MCP Session Assignment" (i18n key `agents.roles.mcpSessionAssignment`). For each slug in `requiredMcpServers`:

- Render a labeled section: server display name (from `mcpServers` data) + server slug, with a "Passthrough" chip if any passthrough session exists for that server.
- Render a MUI `Select` dropdown listing available sessions for that server.
- Render a MUI `IconButton` with a Refresh icon next to the dropdown.
- If no sessions are available, show a message: "No sessions available for this server" (with a retry/refresh option).

**Done when:** The dropdown list dynamically appears/disappears when SOPs/Skills are added/removed; each dropdown is labeled with the server name and slug; refresh button is visible.

### 3.2 — Populate dropdowns with available sessions
Load all MCP servers via `useMcpServers()` (or reuse existing server data). For each required server slug, resolve to `server_id` from the servers list. Use `useQueries` from React Query to batch-fetch sessions for all required servers via individual `useServerSessions(serverId)` calls.

Each session option in the dropdown displays: session name + auth type indicator if passthrough.

**Done when:** Each dropdown is populated with sessions from the correct MCP server; session names are displayed; loading state shows while session data fetches.

### 3.3 — Bind selection state
Add state: `const [selectedMcpSessions, setSelectedMcpSessions] = useState<Record<string, string>>({})` — maps `server_slug → session_id`. Wire each dropdown's `value` and `onChange` to this state. For edit mode, pre-populate from existing assignments when the dialog opens (fetch assigned sessions if role exists).

**Done when:** Selecting a session updates the state; reopening an existing role shows previously assigned sessions pre-selected.

---

## Phase 4 — Pre-Save Validation

### 4.1 — Disable Save when sessions are incomplete
Compute `isSaveDisabled` as: `!name.trim() || requiredMcpServers.some(slug => !selectedMcpSessions[slug])`. Pass this to the Save button's `disabled` prop.

**Done when:** The Save button is disabled when any required server has no session selected; Save is enabled when all assignments are complete and name is non-empty.

### 4.2 — Display validation message
Below the session dropdowns, if `requiredMcpServers.some(slug => !selectedMcpSessions[slug])`, show an `Alert` (severity `warning`) listing the server names that need session assignments.

**Done when:** An inline warning message appears when servers are missing sessions; the message disappears once all servers have assignments; message lists specific server names.

### 4.3 — Prompt on newly-added dependencies
When `requiredMcpServers` changes (a new server appears), if the new server has no session selected and it's not the initial dialog open, optionally scroll to or highlight the new dropdown.

**Done when:** Adding a SOP that introduces a new MCP dependency shows the new dropdown prominently.

---

## Phase 5 — Save Integration

### 5.1 — Create mode session assignment
In `handleSave`, when `editRole` is null (create mode):
1. `POST /agents/roles` with `name`, `description`, `sop_ids`, `skill_ids` → receive new role with `id`
2. For each `[slug, sessionId]` in `selectedMcpSessions`: `POST /agents/roles/{newRoleId}/mcp-sessions` with body `{ mcp_session_id: sessionId }`
3. If any session assignment fails, display error via `setDialogError(err)` and do not close the dialog

**Done when:** Creating a new role with SOPs/Skills and MCP sessions saves all data in one operation; the saved role is fully configured with sessions.

### 5.2 — Edit mode session diff-assignment
In `handleSave`, when `editRole` is non-null:
1. `PUT /agents/roles/{editRole.id}` with updated `name`, `description`, `sop_ids`, `skill_ids`
2. Fetch currently assigned sessions (or track from initial state): compare against `selectedMcpSessions`
3. For sessions in `selectedMcpSessions` but not currently assigned: `POST /agents/roles/{editRole.id}/mcp-sessions`
4. For sessions currently assigned but not in `selectedMcpSessions`: `DELETE /agents/roles/{editRole.id}/mcp-sessions/{sessionId}`
5. If any assignment operation fails, display error via `setDialogError(err)`

**Done when:** Editing a role with changed SOPs/Skills and session assignments correctly adds/removes session bindings.

### 5.3 — Refresh parent table on save
The existing `onSaved` callback in `AgentRoleListPage` already calls `queryClient.invalidateQueries({ queryKey: ['agents', 'roles'] })` and closes the dialog. Ensure this flow is preserved. Add invalidation for the roles detail query if applicable.

**Done when:** After saving the dialog, the parent table shows updated data without manual page reload.

---

## Phase 6 — Refresh & Error Handling

### 6.1 — Add Refresh button per dropdown
Each server section's refresh `IconButton` calls `queryClient.invalidateQueries({ queryKey: ['mcp', 'servers', serverId, 'sessions'] })` to refetch sessions for that server.

**Done when:** Clicking refresh triggers a new API call for that server's sessions; dropdown updates with latest data.

### 6.2 — Preserve selection after refresh
On refresh success, if the currently selected `session_id` still exists in the new session list, keep it selected. If it no longer exists (session was deleted), reset selection for that server to empty and show the validation warning.

**Done when:** Refresh preserves valid selections; clears selections for deleted sessions and shows validation feedback.

### 6.3 — Inline loading state
While `useServerSessions` is loading for a given server, show a `CircularProgress` (size 16–20) in place of or next to the dropdown.

**Done when:** Each server section independently shows a loading indicator while its sessions are being fetched.

### 6.4 — Inline error state with retry
If `useServerSessions` errors for a given server, show an error message inline ("Failed to load sessions") with a "Retry" button that triggers `refetch()`.

**Done when:** Session fetch failures show inline errors with retry capability; errors are scoped per server, not blocking other servers' dropdowns.

### 6.5 — Backend save error handling
All save operations (role create/update, session assign/remove) are wrapped in try-catch. Errors are surfaced via `setDialogError(err)` and rendered by the existing `<PermissionDeniedAlert>` at the top of the dialog content, per the Dialog Error Handling Standard.

**Done when:** Backend validation errors (403, 404, 409, 500) display as inline error alerts in the dialog.

---

## Phase 7 — Passthrough Sessions

### 7.1 — Passthrough badge on server label
When a required server has one or more passthrough sessions (`auth_type === 'pasthrough'`), render a MUI `Chip` with label "Passthrough" (i18n key `mcp.sessions.passthrough`) next to the server name in the section label.

**Done when:** Servers with only passthrough sessions (or mixed) show the Passthrough badge; servers without passthrough sessions do not.

### 7.2 — Passthrough session selection
Passthrough sessions appear alongside regular sessions in the dropdown. The one-session-per-server constraint is enforced by the backend (`UniqueConstraint` on `role_id, server_id`). Multiple passthrough sessions per server are not supported by the current data model (`AgentRoleMcpSession` has one session per server), but passthrough sessions should coexist — the UI simply allows any session to be selected; the backend constraint already handles the one-per-server rule. No special frontend enforcement is needed beyond the dropdown allowing single selection per server.

**Done when:** Passthrough sessions are selectable in the dropdown; passthrough badge is clearly visible.

---

## Phase 8 — i18n Keys

### 8.1 — Add new i18n keys
Add the following keys to `frontend/src/i18n/locales/en.json`:

| Key | English Value |
|-----|--------------|
| `agents.roles.mcpSessionAssignment` | "MCP Session Assignment" |
| `agents.roles.mcpSessionAssignmentHint` | "Select a session for each required MCP server. All servers must have a session assigned before saving." |
| `agents.roles.mcpSessionRequired` | "Session required" |
| `agents.roles.mcpSessionMissing` | "Missing session assignment for:" |
| `agents.roles.mcpSessionRefresh` | "Refresh sessions" |
| `agents.roles.mcpSessionLoadError` | "Failed to load sessions" |
| `agents.roles.mcpSessionRetry` | "Retry" |
| `agents.roles.mcpSessionNoSessions` | "No sessions available for this server" |
| `agents.roles.mcpSessionLoading` | "Loading sessions..." |

Reuse existing keys: `mcp.sessions.passthrough`, `app.refresh`, `app.save`, `app.cancel`, `app.error`.

**Done when:** All new strings are in `en.json`; all displayed text uses `t()` function; no hardcoded strings remain.

---

## Phase 9 — Unit Tests

### 9.1 — Remove legacy test file
Delete `frontend/src/__tests__/AssignMcpSessionsToRoleDialog.test.tsx`.

**Done when:** File is deleted; no import references remain in any test file.

### 9.2 — Update AgentRoleDialog tests
Update `frontend/src/__tests__/AgentRoleDialog.test.tsx` to:
- Remove mock responses for the old assigned MCP sessions endpoint (`/mcp-sessions` on the get mock)
- Add mock responses for MCP server list (`/mcp/servers`) and per-server session list (`/mcp/servers/{id}/sessions`)
- Update test expectations to reference the new inline dropdowns instead of the "Assign MCP Sessions" button

**Done when:** All existing tests pass with the updated component; no references to `AssignMcpSessionsToRoleDialog` remain.

### 9.3 — Add new test scenarios
Add test cases for:
- **Server requirement computation:** Selecting a SOP with required skills shows the corresponding MCP server dropdowns; deselecting removes them.
- **Dropdown population:** Dropdown lists the correct sessions per server.
- **Pre-save validation:** Save button is disabled when a required server has no session; warning message appears.
- **Create flow with sessions:** Creating a new role with SOPs/Skills and session assignments calls both the role creation endpoint and session assignment endpoints correctly.
- **Edit flow session diff:** Editing a role correctly adds new sessions and removes stale ones.
- **Refresh behaviour:** Clicking refresh re-fetches session data; selection preserved if session still exists.
- **Passthrough badge:** Passthrough chip renders when server has passthrough sessions.
- **Error handling:** Session fetch errors show inline error with retry; save errors show via `PermissionDeniedAlert`.

**Done when:** All new test cases pass; coverage includes create mode, edit mode, error states, and edge cases.

---

## Phase 10 — Cleanup

### 10.1 — Remove unused i18n keys
Remove the following now-unused keys from `en.json`:
- `agents.roles.assignedMcpSessions`
- `agents.roles.assignMcpSessions`
- `agents.roles.assignMcpSessionsTitle`
- `agents.roles.assignMcpSessionsHint`
- `agents.roles.noAssignedMcpSessions`
- `agents.roles.noAvailableMcpSessions`
- `agents.roles.removeMcpSession`
- `agents.roles.selectedForServer`

**Done when:** No unused i18n key warnings; `grep` for removed keys returns no matches in source files.

### 10.2 — TypeScript compilation
Run `npx tsc --noEmit` in the `frontend/` directory. Fix any type errors.

**Done when:** Zero TypeScript errors.

---

## Completion Checklist

- [x] `AssignMcpSessionsToRoleDialog.tsx` deleted
- [x] `AssignMcpSessionsToRoleDialog.test.tsx` deleted
- [x] No references to `AssignMcpSessionsToRoleDialog` remain in any source or test file
- [x] Inline MCP session dropdowns render dynamically based on SOP/Skill selection
- [x] Save button disabled when required servers lack session assignments
- [x] Inline validation warning visible when sessions are missing
- [x] Create flow: role + sessions saved in one operation
- [x] Edit flow: sessions diff-assigned (add/remove)
- [x] Refresh button re-fetches sessions per server; preserves valid selections
- [x] Passthrough badge shown on servers with passthrough sessions
- [x] Inline loading and error states render per server
- [x] Save errors surfaced via `PermissionDeniedAlert`
- [x] All i18n strings in `en.json`; no hardcoded strings
- [x] Unused i18n keys removed
- [x] All existing `AgentRoleDialog` tests updated and passing
- [x] New test scenarios for inline dropdowns passing
- [x] TypeScript compilation: zero errors
- [x] Parent Agent Roles table refreshes after save
