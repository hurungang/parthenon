# Specification Delta: Improve Role MCP Session Assignment

## Affected Spec Areas

| Spec Area | Description of Change |
|-----------|----------------------|
| Agent Management (`docs/master/product/features/agent-management.md`) | Remove separate Assign MCP Session popup; add inline MCP session dropdowns in Edit Agent Role dialog; new dynamic MCP server requirement detection from SOP/Skill selection |
| MCP Hub (`docs/master/product/features/mcp-hub.md`) | Cross-reference update — note that session-to-role assignment is performed inline in the role edit dialog, not via a separate popup |

---

## New Capabilities

1. **Dynamic MCP Server Requirement Detection** — When a user selects SOPs or Skills in the Edit Agent Role dialog, the system automatically analyzes the tool dependencies of those selections and determines which MCP servers are required. This is surfaced immediately as a list of required servers, each with an inline session dropdown.

2. **Inline MCP Session Dropdowns in Role Edit Dialog** — For each MCP server required by the selected SOPs/Skills, an inline dropdown is rendered directly within the Edit Agent Role dialog. The dropdown is populated with available sessions for that server. Users select one session per required server.

3. **Pre-Save Validation of MCP Session Completeness** — The Save action is blocked (disabled) until every required MCP server has a session selected. An inline message indicates which servers are missing assignments. This guarantees no role is saved in an execution-incomplete state.

4. **Inline Session Refresh** — Each MCP server session dropdown includes a refresh button that reloads available sessions from the backend without leaving the role form. The user's current selection is preserved if the session still exists.

5. **Dynamic Re-computation on SOP/Skill Changes** — The list of required MCP servers and their dropdowns updates automatically whenever the user adds or removes SOPs/Skills. Removed dependencies cause the corresponding dropdown to disappear; new dependencies cause a new dropdown to appear.

---

## Modified Capabilities

| Capability | Before | After |
|------------|--------|-------|
| MCP Session Assignment in Role Edit | Separate "Assign MCP Session" button opens a popup dialog (`AssignMcpSessionsToRoleDialog`); only functional after role has been saved; user must save first, reopen, then assign | Inline dropdowns appear directly in the Edit Agent Role dialog based on selected SOPs/Skills; assignment happens during role creation/editing before save |
| Role Save Workflow | Save succeeds regardless of MCP session assignment status; sessions can be assigned later in a separate step | Save is blocked until every required MCP server has a session selected; role is execution-ready on save |
| MCP Server Requirement Visibility | No indication during role editing of which MCP servers are needed; user discovers requirements later or through separate documentation | Required MCP servers are displayed inline as soon as SOPs/Skills are selected, with immediate visual feedback on assignment status |
| Edit Agent Role Dialog Layout | Dialog contains SOP multi-select, Skill multi-select, assigned identities table, assigned MCP sessions table with Assign/Remove buttons | Dialog contains SOP multi-select, Skill multi-select, inline MCP session dropdowns (dynamic), assigned identities table; the separate MCP sessions table and Assign/Remove buttons are removed |
| `AssignMcpSessionsToRoleDialog` Component | Active component used for session-to-role assignment via popup | Component removed; all assignment functionality migrated inline to `AgentRoleDialog` |

---

## Removed Capabilities

- **Separate Assign MCP Session Popup Dialog** — The `AssignMcpSessionsToRoleDialog` component and its associated trigger button in `AgentRoleDialog` are removed. The popup-based workflow is fully replaced by inline dropdowns.
- **Post-Save Session Assignment Workflow** — The ability (and necessity) to assign MCP sessions to a role after it has been saved, as a separate step, is removed. Session assignment is now an integral part of the role creation/editing flow.

---

## Spec Update Instructions

1. **`docs/master/product/features/agent-management.md`**: Update the "What It Does" section to describe the inline MCP session assignment flow replacing the separate popup. Add bullet points for: dynamic MCP server requirement detection from SOP/Skill selection, inline dropdowns per required MCP server, pre-save validation, and inline refresh. Remove references to the separate Assign MCP Session popup. Update the "Acceptance Criteria" section to reflect the new inline session assignment acceptance criteria.

2. **`docs/master/product/features/mcp-hub.md`**: Add a cross-reference note in the "Session-to-Role Mapping" description indicating that session assignment is performed inline within the Edit Agent Role dialog, not via a separate popup.

3. **Master tech spec updates** (`docs/master/technology/modules/agents/tech-spec.md`):
   - Mark `AssignMcpSessionsToRoleDialog` as **removed** in the Code Reference Map.
   - Update `AgentRoleDialog` description to reflect the new inline MCP session dropdowns replacing the separate Assign button and session table.
   - Remove references to `AssignMcpSessionsToRoleDialog.test.tsx` from the test file references (component no longer exists).

4. **Master test plan updates** (`docs/master/qa/test-plans/agents-ui-test-plan.md` and `docs/master/qa/test-plans/frontend-test-plan.md`):
   - Remove test scenarios referencing the `AssignMcpSessionsToRoleDialog` popup.
   - Add test scenarios for: inline MCP server requirement detection, inline session dropdown population, pre-save validation blocking save, inline refresh, dynamic re-computation on SOP/Skill changes.
   - Remove the test file reference `frontend/src/__tests__/AssignMcpSessionsToRoleDialog.test.tsx`.
