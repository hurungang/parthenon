# Test Plan: Improve Role MCP Session Assignment

## Scope

Frontend-only change (no DB/backend API changes). Refactors `AgentRoleDialog` to compute required MCP servers client-side, render inline session dropdowns per server, enforce pre-save validation, and remove the separate `AssignMcpSessionsToRoleDialog` popup.

---

## 1. Test Strategy

| Layer | Technology | Focus | Execution |
|-------|-----------|-------|-----------|
| **Component Tests** | Vitest + React Testing Library | `AgentRoleDialog` — inline dropdown rendering, server computation, pre-save validation blocking, refresh behavior, save flow integration, error states | `npx vitest run` |
| **Hook Tests** | Vitest | `useMcpServers`, `useServerSessions`, `useAllTools` — query enable/disable conditions, cache invalidation on refresh, loading/error states | `npx vitest run` |
| **E2E Tests** | Playwright | Full role CRUD lifecycle with MCP session assignment from user perspective: create role → assign sessions inline → save → verify parent table refresh → edit → change sessions → delete | `npx playwright test` |
| **Manual QA** | Browser | Visual verification of inline dropdown layout, passthrough badge rendering, dialog resize behavior, i18n completeness, accessibility (aria-labels, keyboard nav) | Ad hoc |

**No backend testing needed** — all APIs already exist and are covered by existing backend tests (`backend/tests/`). The `available-mcp-sessions` endpoint remains on the backend but is no longer called; no regression risk.

---

## 2. Coverage Areas

### 2.1 Dynamic MCP Server Detection
- **What**: When SOPs/Skills are selected/deselected, the dialog computes which MCP servers are required
- **Computation chain**: selected SOPs → required skills (locked) ∪ directly selected skills → Skill.tool_ids → McpTool lookup → slug extraction from `slug____tool` → deduplicate
- **Exclusions**: `system____*` tools must never produce a required server
- **Variants**: Solely SOP-selected skills; solely direct skills; mix of both; SOPs with zero required skills; all skills deselected

### 2.2 Inline Dropdown Rendering
- **What**: One labeled section per required MCP server, each with a dropdown of available sessions
- **States to cover**: Loading (spinner/skeleton), loaded with sessions, empty (no sessions available), error (fetch failed with retry button)
- **Passthrough variant**: Servers with passthrough sessions show a "Passthrough" badge; multiple passthrough sessions allowed; non-passthrough servers enforce one-session constraint
- **Zero-state**: When no SOPs/Skills selected, the MCP Session Assignment section is not rendered at all

### 2.3 Pre-Save Validation
- **What**: Save button disabled when any required server lacks a selected session
- **Validation source**: Derived `isSaveDisabled` and `missingServers` from `useMemo`
- **Message**: Inline validation text naming which servers need assignments
- **Edge**: Name field empty also blocks save (existing behavior, must not regress)
- **Edge**: All servers assigned → Save enabled immediately (no manual refresh needed)

### 2.4 Refresh Per Server
- **Goals**:
  - Refresh button per server dropdown reloads available sessions from backend
  - Current selection preserved if still available after refresh
  - Selection cleared and Save blocked if previously selected session no longer exists
  - Individual query invalidation (only the target server's cache, not all servers)
- **States**: Refresh in progress (button disabled/spinner), refresh successful, refresh failed

### 2.5 State Recomputation
- **What**: Required servers recompute when SOP/Skill selection changes
- **Triggers**: Add SOP, remove SOP, add direct skill, remove direct skill (also SOP auto-selects/locks skills → cascades)
- **Effects**: New servers appear with loading dropdowns; removed servers' dropdowns disappear; orphaned selections cleaned from `selectedMcpSessions`
- **Performance**: Recomputations must not cause excessive re-renders or query storms (useMemo + query enabled conditions guard)

### 2.6 Passthrough Session Handling
- **What**: Passthrough sessions identified by `auth_type: 'passthrough'` → badge shown
- **Behavior**: Passthrough sessions are selectable; multiple passthrough sessions per server allowed (no one-per-server constraint); non-passthrough servers still enforce one-per-server
- **Visual**: Badge rendered inline next to server name; distinct from non-passthrough rows

### 2.7 Save Flow Integration
- **Create mode**: POST role → extract role ID → sequentially POST each `selectedMcpSessions` entry
- **Edit mode**: PUT role → diff current assignments vs pre-edit assignments → POST additions / DELETE removals sequentially
- **Both modes**: On success → close dialog → parent table auto-refreshes (no manual reload)
- **Both modes**: On failure → dialogError set → PermissionDeniedAlert renders inline (Dialog Error Handling Standard)
- **Rollback**: If role save succeeds but a session assignment fails, error is surfaced (no silent partial saves)

### 2.8 Parent Table Refresh
- **What**: After save, the Agent Roles list table reflects changes without page reload
- **Mechanism**: `onSaved()` callback invalidates roles query cache
- **Verify**: Created role appears in table; edited role shows updated data; role count changes

### 2.9 Removal of Old Popup
- **What**: `AssignMcpSessionsToRoleDialog` component and its test file are deleted
- **What**: The "Assign MCP Sessions" button and assigned sessions table removed from `AgentRoleDialog`
- **What**: `available-mcp-sessions` endpoint no longer called from frontend
- **Verification**: No import references remain; no dead code; test file for removed component deleted

### 2.10 Error Handling
- **Per-server fetch failure**: Inline error message + retry button per server (not dialog-level error)
- **Save failure (backend validation)**: `dialogError` state → `PermissionDeniedAlert` at top of dialog
- **Session no longer exists at save time**: Backend returns error → surface in dialog
- **Network failure during save**: Dialog stays open, error shown, user can retry
- **Concurrent refresh + save**: No race condition corrupts selection state

---

## 3. Critical Scenarios (WHEN/THEN)

### Scenario 1: Full CRUD — Create Role with MCP Sessions
- **WHEN** user opens "Create Agent Role" dialog and enters a name
- **AND** selects an SOP that requires Skill A (which uses tools from MCP server "github")
- **THEN** an inline "MCP Session Assignment" section appears with a "github" labeled dropdown
- **WHEN** user selects a session for "github" from the dropdown
- **AND** clicks Save
- **THEN** the role is created, session assigned, dialog closes
- **AND** the parent Agent Roles table refreshes to show the new role

### Scenario 2: Create Role — Save Blocked by Missing Session
- **WHEN** user selects an SOP requiring MCP server "github" and "jira"
- **THEN** two inline dropdowns appear (github, jira)
- **WHEN** user selects a session for "github" but leaves "jira" unselected
- **THEN** Save button is disabled
- **AND** an inline message indicates "jira" requires a session assignment

### Scenario 3: Edit Role — Change Session Assignments
- **WHEN** user opens an existing role for editing
- **THEN** previously assigned sessions are pre-selected in the inline dropdowns
- **WHEN** user changes the "github" session to a different session
- **AND** clicks Save
- **THEN** the old session is removed, new session assigned (diff-based)
- **AND** parent table refreshes

### Scenario 4: Edit Role — Add New SOP Triggers New Server
- **WHEN** editing a role with only "github" assigned
- **AND** user adds an SOP that requires "jira" tools
- **THEN** a new "jira" dropdown appears, initially unselected
- **THEN** Save is blocked until a "jira" session is chosen

### Scenario 5: Edit Role — Remove SOP Removes Server Requirement
- **WHEN** editing a role with "github" and "jira" sessions assigned
- **AND** user deselects the SOP that required "jira" (and no other SOP/Skill requires it)
- **THEN** the "jira" dropdown disappears
- **THEN** the "jira" entry is removed from `selectedMcpSessions`
- **AND** Save is enabled (only "github" remains, already assigned)

### Scenario 6: Refresh — Selected Session Still Exists
- **WHEN** a session is selected for "github"
- **AND** user clicks the refresh button on the "github" dropdown
- **THEN** the session list reloads from backend
- **AND** the previously selected session remains selected

### Scenario 7: Refresh — Selected Session Gone
- **WHEN** a session is selected for "github"
- **AND** that session is deleted by another user
- **AND** user clicks the refresh button on the "github" dropdown
- **THEN** the dropdown resets to unselected
- **AND** Save is blocked until a new session is chosen

### Scenario 8: Passthrough Server — Badge and Multi-Select
- **WHEN** a required MCP server has only passthrough-type sessions
- **THEN** a "Passthrough" badge is displayed next to the server name
- **AND** the dropdown allows selection of passthrough sessions
- **AND** multiple passthrough sessions can coexist without violating the one-per-server rule

### Scenario 9: Zero Required Servers
- **WHEN** user opens Create Role dialog with no SOPs or Skills selected
- **THEN** no "MCP Session Assignment" section is displayed
- **AND** Save is enabled (only name required)

### Scenario 10: System Tools Excluded
- **WHEN** a Skill references only `system____*` tools (no real MCP servers)
- **AND** user selects that Skill
- **THEN** no MCP server dropdowns appear (system tools do not create server requirements)

### Scenario 11: Dialog Error on Save Failure
- **WHEN** user completes all required fields and session assignments
- **AND** clicks Save
- **AND** the backend returns a 403 (or other error)
- **THEN** the dialog stays open
- **AND** a `PermissionDeniedAlert` appears at the top of the dialog
- **AND** all user input is preserved (not lost)

### Scenario 12: Parent Table Auto-Refresh After Save
- **WHEN** a role is created or edited via the dialog
- **AND** save succeeds
- **THEN** dialog closes
- **AND** parent table shows updated data without manual page reload
- **AND** role count (if displayed) is updated

### Scenario 13: Old Popup Removal
- **WHEN** the Edit Agent Role dialog is opened
- **THEN** no "Assign MCP Sessions" button is present
- **AND** no separate popup dialog opens for session assignment
- **AND** all assignment happens via inline dropdowns

---

## 4. Edge Cases & Risks

| Edge Case / Risk | Impact | Mitigation |
|---|---|---|
| **Tool name format inconsistency**: Tool names not following `slug____tool` convention | Slug extraction fails → required servers incorrectly computed | Test with both `slug____tool` and legacy `slug/tool` formats (canonicalize before extraction) |
| **Skill with zero tool_ids**: Skill has no tool bindings | No server required for that skill → no dropdown added | Test with skill having empty `tool_ids` array |
| **SOP with no required_skill_ids**: SOP has no skill dependencies | No additional locked skills → no cascading server requirement | Test with SOP having null/empty `required_skill_ids` |
| **Duplicate server across skills**: Two different Skills reference tools on the same server | Server appears once (deduplicated) → one dropdown, not two | Verify deduplication logic |
| **Server with no sessions**: Required server exists but has zero configured sessions | Dropdown shows empty state message "No sessions available" → Save blocked | Test with server having `data: []` from session endpoint |
| **Server slug not in McpServer list**: Tool references a server whose slug isn't in `useMcpServers()` data | Cannot resolve server_id → session query disabled → inline error shown | Test with mismatched slug-vs-server data |
| **Rapid SOP toggling**: User rapidly selects/deselects multiple SOPs | Query cancellation storms, stale state | Test debounce or cancellation logic; use `useQueries` with proper enabled guards |
| **Concurrent edits**: Two users editing the same role simultaneously | Last write wins or conflict error | Backend's responsibility (out of scope); test that backend error is surfaced properly |
| **Passthrough + non-passthrough mix**: Same server has both passthrough and non-passthrough sessions | Dropdown lists all sessions; one-per-server constraint applies only to non-passthrough? | Clarify with PRD: tech spec says passthrough sessions bypass one-per-server; non-passthrough on same server still enforces it |
| **Save in progress + Refresh click**: User clicks refresh on a dropdown while save is in flight | Race condition on session data | Refresh button should be disabled during save |
| **Large number of required servers**: SOP requires tools from 10+ servers | Dialog height; scrollability; query batch size | Test layout with 5+ servers; ensure dialog scrolls or sections collapse |
| **i18n key removal**: Old i18n keys for AssignMcpSessions popup removed | Missing translation → raw key shown in UI | Verify removed keys are not referenced anywhere; verify new keys exist in `en.json` |
| **Existing AssignMcpSessionsToRoleDialog mock in other tests**: `issue-3-sop-skill-autoselect.test.tsx` mocks the removed component | Import error → test failure | Remove the mock from that test file |
| **Backend `available-mcp-sessions` endpoint still functional**: Not called but still deployed | No regression; endpoint idle | Verify no other frontend pages call this endpoint |

---

## 5. Acceptance Criteria Checklist

Maps directly to PRD Section "Acceptance Criteria" (lines 40-73).

### Inline MCP Session Assignment
- [ ] AC-01: Selecting SOPs/Skills displays required MCP servers in the dialog
- [ ] AC-02: Each required MCP server shown as labeled section with inline session dropdown
- [ ] AC-03: Dropdown list updates dynamically when SOPs/Skills added/removed
- [ ] AC-04: No MCP session section displayed when no SOPs/Skills selected

### Session Selection & Enforcement
- [ ] AC-05: Save blocked (button disabled) when any required server lacks session
- [ ] AC-06: Clear inline message indicates which servers need session assignment
- [ ] AC-07: User can select exactly one session per required MCP server from dropdown

### Refresh Capability
- [ ] AC-08: Each server dropdown has a refresh button that reloads available sessions
- [ ] AC-09: After refresh, current selection preserved if session still exists
- [ ] AC-10: After refresh, selection cleared and Save blocked if session no longer available

### Remove Separate Assign MCP Session Popup
- [ ] AC-11: "Assign MCP Session" button removed from Edit Agent Role dialog
- [ ] AC-12: Separate popup dialog no longer opens
- [ ] AC-13: `AssignMcpSessionsToRoleDialog` component file deleted
- [ ] AC-14: `AssignMcpSessionsToRoleDialog.test.tsx` test file deleted
- [ ] AC-15: No remaining imports or references to the removed component

### Passthrough Sessions
- [ ] AC-16: Passthrough MCP servers identified and display "Passthrough" badge
- [ ] AC-17: Passthrough sessions selectable in inline dropdown
- [ ] AC-18: One-session-per-server constraint not applied to passthrough sessions

### Save Behavior & Parent Table Refresh
- [ ] AC-19: After saving role with assigned sessions, dialog closes
- [ ] AC-20: Parent Agent Roles table auto-refreshes (no manual page reload)
- [ ] AC-21: Saved role's MCP session assignments immediately reflected when reopened

### Error Handling
- [ ] AC-22: Session data load failure shows inline error with retry option per server
- [ ] AC-23: Backend validation error on save shown inline in dialog (Dialog Error Handling Standard)
- [ ] AC-24: Dialog stays open on save failure; user input preserved

---

## 6. Test File References

Test paths from `docs/config.yaml` `source.tests`:
- `frontend/src/__tests__/`
- `e2e/tests/`

### 6.1 Component Tests (Vitest)

| File | Status | Coverage |
|------|--------|----------|
| `frontend/src/__tests__/AgentRoleDialog.test.tsx` | **UPDATE** | Inline dropdown rendering, server computation, pre-save validation, refresh, save integration, passthrough badge, error states, removal of old popup elements |
| `frontend/src/__tests__/AssignMcpSessionsToRoleDialog.test.tsx` | **DELETE** | Component no longer exists — all tests now in AgentRoleDialog test above |
| `frontend/src/__tests__/service-decomposition/issue-3-sop-skill-autoselect.test.tsx` | **UPDATE** | Remove mock for `AssignMcpSessionsToRoleDialog` (line 52-54); ensure tests still pass with new inline dropdown behavior |

### 6.2 E2E Tests (Playwright)

| File | Status | Coverage |
|------|--------|----------|
| `e2e/tests/agent-management.spec.ts` | **UPDATE** | Extend with role CRUD scenarios including MCP session assignment (or add dedicated test file below) |
| `e2e/tests/agent-role-mcp-assignment.spec.ts` | **NEW** | Full E2E lifecycle: create role → assign sessions inline → verify save → edit role → change assignments → verify parent table refresh → delete role → verify removal |

### 6.3 Existing E2E Tests (Verify No Regression)

| File | Check |
|------|-------|
| `e2e/tests/agent-navigation.spec.ts` | Agent Roles navigation still works |
| `e2e/tests/passthrough-sessions.spec.ts` | Passthrough functionality still works (no change to passthrough behavior itself) |
| `e2e/tests/skills-system-tools.spec.ts` | System tools still excluded from MCP server computation |
| `e2e/tests/permission-errors.spec.ts` | PermissionDeniedAlert still renders correctly in dialog context |

### 6.4 No-Change Files (Confirm)

| File | Reason |
|------|--------|
| `backend/tests/` (all) | No backend API changes |
| `frontend/src/__tests__/AgentRoleViewDialog.test.tsx` | View dialog out of scope (unchanged) |
| `frontend/src/__tests__/AgentRoleListPage.test.tsx` | List page unchanged (passes `onSaved` callback) |
| `frontend/src/__tests__/McpSessionManager.test.tsx` | Session CRUD unchanged |

---

## 7. Test Data Requirements

### Component Tests
- Mock MCP server with passthrough sessions (`auth_type: 'passthrough'`)
- Mock MCP server with non-passthrough sessions (`auth_type: 'api_key'`)
- Mock MCP server with zero sessions (empty array)
- Mock MCP server with mixed session types
- Mock Skills with varied `tool_ids` (including `system____*`, `slug____*`, and mixed)
- Mock SOPs with and without `required_skill_ids`
- Mock tools with both `slug____tool` and legacy `slug/tool` name formats
- Backend error responses: 403 (forbidden), 404 (not found), 500 (server error)
- Backend success responses: role create, role update, session assign, session delete

### E2E Tests
- Real SOPs and Skills pre-configured in test realm with known MCP tool dependencies
- Real MCP servers with active sessions (both passthrough and non-passthrough)
- Test role names with identifiable prefix: `e2e-mcp-test-{timestamp}`
- Cleanup: delete test roles after each test spec

---

## 8. Execution Order

1. **Delete** `AssignMcpSessionsToRoleDialog.test.tsx` 
2. **Update** `AgentRoleDialog.test.tsx` — remove old MCP popup assertions, add new inline test cases
3. **Update** `issue-3-sop-skill-autoselect.test.tsx` — remove mock for removed component
4. **Run component tests** → all must pass
5. **Create** `e2e/tests/agent-role-mcp-assignment.spec.ts` — full CRUD lifecycle
6. **Run E2E tests** → all must pass (new + existing)
7. **Manual QA** — visual verification, passthrough badge, accessibility
