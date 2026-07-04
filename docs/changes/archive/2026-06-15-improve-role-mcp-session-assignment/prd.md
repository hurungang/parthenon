# PRD: Improve Role MCP Session Assignment

## Epic Overview

Currently, assigning MCP sessions to an Agent Role requires a separate, disconnected popup dialog that only functions after the role has been saved — users must save the role, reopen it, and then assign sessions in a secondary step. This two-step workflow causes roles to be created without required MCP session assignments, leading to agent execution failures later when tools cannot resolve a session. This change integrates MCP session selection directly into the Edit Agent Role dialog as inline dropdowns that appear dynamically based on the SOPs and Skills the user selects. For each MCP server required by the selected SOPs/Skills, an inline dropdown presents available sessions, and the user must assign one before saving. This eliminates the disconnection between role definition and session assignment, prevents incomplete configurations, and ensures every role is execution-ready the moment it is saved.

---

## Business Goals

- Eliminate agent execution failures caused by roles missing MCP session assignments, improving platform reliability and user trust.
- Reduce the number of steps required to configure a fully operational role from three (create, save, reopen, assign sessions) to one (create and assign sessions inline before save).
- Make MCP server requirements visible to the user at the moment they select SOPs/Skills, reducing the cognitive load of discovering dependencies later.
- Ensure every saved role has all required MCP sessions assigned by enforcing completion before the save action succeeds.
- Provide the flexibility to refresh available session options without leaving the role editing context.

---

## Users & Personas

**Platform Administrators** — Users who create and configure Agent Roles, assigning SOPs, Skills, and MCP sessions. They need a single, coherent workflow where role definition and session assignment happen together, not in disconnected steps.

**Agent Authors / Developers** — Users who design agent behaviors and need to verify at a glance which MCP servers are required for a role's SOPs/Skills. They benefit from seeing MCP dependencies surfaced inline during role configuration.

**Operations / Support Teams** — Users who troubleshoot failed agent executions. They benefit from the assurance that saved roles are guaranteed to have all MCP sessions assigned, reducing the number of configuration-related support tickets.

---

## User Stories

- As a **Platform Administrator**, I want to see which MCP servers are required as soon as I select SOPs or Skills in the Edit Role dialog, so that I understand the tool dependencies of my role before saving it.
- As a **Platform Administrator**, I want an inline dropdown next to each required MCP server showing available sessions, so that I can assign sessions without opening a separate dialog.
- As a **Platform Administrator**, I want the system to require a session selection for every required MCP server before I can save the role, so that I never create a role with missing session assignments.
- As a **Platform Administrator**, I want a refresh button next to each session dropdown so that I can reload available sessions if a new session was just created elsewhere without leaving the role form.
- As an **Agent Author**, I want the MCP server requirements to update dynamically when I add or remove SOPs/Skills, so that the session assignment panel always reflects the current role composition.

---

## Acceptance Criteria

### Inline MCP Session Assignment
- When the user selects one or more SOPs or Skills in the Edit Agent Role dialog, the system analyzes the tool dependencies and displays a list of required MCP servers.
- Each required MCP server appears as a labeled section with an inline dropdown populated with available sessions for that server.
- The dropdown list updates dynamically as the user adds or removes SOPs/Skills (MCP server requirements are recomputed).
- If no SOPs or Skills are selected, no MCP session section is displayed.

### Session Selection & Enforcement
- Every required MCP server must have a session selected before the Save button is enabled or the save action succeeds.
- If any required MCP server has no session selected, the Save action is blocked with a clear inline message indicating which servers need a session assignment.
- The user can select one session per required MCP server from the dropdown.

### Refresh Capability
- Each MCP server session dropdown includes a refresh button that reloads the list of available sessions for that server from the backend.
- After refreshing, the dropdown list updates without clearing the user's current selection (if the selected session still exists).
- If a previously selected session is no longer available after refresh, the dropdown resets to unselected and the Save action is blocked until a new session is chosen.

### Remove the Separate Assign MCP Session Popup
- The existing "Assign MCP Session" button and its associated popup dialog are removed from the Edit Agent Role dialog.
- All session assignment functionality is handled exclusively through the inline dropdowns described above.

### Passthrough Sessions
- MCP servers configured with passthrough session type are identified and displayed with a "Passthrough" badge alongside the server name.
- Passthrough sessions remain selectable in the inline dropdown.
- The one-session-per-server constraint does not apply to passthrough sessions (multiple passthrough sessions may coexist per server per existing platform behavior).

### Save Behavior & Parent Table Refresh
- After saving a role with assigned MCP sessions, the dialog closes and the parent Agent Roles table automatically refreshes to show the updated role data without manual page reload.
- The saved role's MCP session assignments are immediately reflected when the role is reopened for editing.

### Error Handling
- If session data fails to load for a required MCP server, an inline error message is displayed in place of the dropdown with a retry option.
- If saving fails due to a backend validation error (e.g., session no longer exists), a clear error message is shown inline in the dialog consistent with the platform's Dialog Error Handling Standard.

---

## Out of Scope

- Changes to how MCP servers are registered or how sessions are created — this change only affects the role editing workflow.
- Changes to how SOPs or Skills declare their tool dependencies — the dependency analysis consumes existing declarations without modifying them.
- Changes to the passthrough session behavior or the underlying one-session-per-server enforcement logic.
- Changes to the Agent Role view dialog — only the edit/create dialog is affected.
- Backend API changes — all required endpoints already exist (`available-mcp-sessions`, `mcp-sessions` assignment endpoints).
- Auto-assignment or intelligent defaults for session selection — users always choose explicitly.

---

## Dependencies & Constraints

- The backend API endpoint `GET /api/v1/agents/roles/{role_id}/available-mcp-sessions` must return session data filtered by the MCP servers whose tools are used by the role's SOPs/Skills.
- The frontend must have access to SOP/Skill-to-tool and tool-to-MCP-server mappings to compute required MCP servers client-side from selected SOPs/Skills.
- Must comply with the platform's existing Dialog Error Handling Standard for all inline error states.
- Must maintain compatibility with both traditional and passthrough session types as defined in the MCP Hub feature spec.
- The existing `AgentRoleMcpSession` join table (one session per MCP server per role) is the persistence model for assignments — no schema changes needed.
