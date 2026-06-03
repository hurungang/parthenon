# Agent UI Test Plan

## Scope

Covers frontend UI tests for agent navigation structure, `AgentTypeDetailsDialog`, agent executions filtering, and role/identity view dialogs. Backend engine logic, CRUD API operations, session lifecycle, and execution log rendering are covered in `agent-engine-test-plan.md`.

---

## Coverage Areas

### 1. Navigation Menu Structure

**What is tested:**
- "AI Agent" collapsible group present in sidebar with all five child links in the correct order
- Each child link routes to its correct path
- Group defaults to expanded on first render
- Group header highlights when any child route is active; active child item highlighted individually
- Collapse/expand toggle behavior within a session
- Legacy `/agents/instances` URL redirects to `/agents/executions`

**Acceptance criteria:**
- All five child links present in order: Agent Roles (`/agents/roles`), Agent Identities (`/agents/identities`), Agent Types (`/agents`), Agent Executions (`/agents/executions`), Agent Logs (`/conversations`)
- Exactly one child item highlighted at any time
- AI Agent group header highlighted when any child route is active
- `/agents/instances` redirect resolves without error

**Test files:**
- [e2e/tests/agent-navigation.spec.ts](../../../../e2e/tests/agent-navigation.spec.ts) — Full navigation structure: link routing, active highlighting, group collapse/expand, legacy redirect

---

### 2. Agent Roles and Agent Identities Navigation

**What is tested:**
- "Agent Roles" and "Agent Identities" menu items present in the AI Agent group
- Navigation to each page via the sidebar menu
- Active state highlighting for each route
- AI Agent group header highlighted when on Agent Roles or Agent Identities route

**Acceptance criteria:**
- Clicking "Agent Roles" navigates to the Agent Roles page and highlights that menu item
- Clicking "Agent Identities" navigates to the Agent Identities page and highlights that menu item
- Direct navigation to `/agents/roles` or `/agents/identities` activates the corresponding menu item and the group header

**Test files:**
- [e2e/tests/agent-navigation.spec.ts](../../../../e2e/tests/agent-navigation.spec.ts) — Agent Roles and Agent Identities navigation and active state
- [frontend/src/__tests__/AgentRoleListPage.test.tsx](../../../../frontend/src/__tests__/AgentRoleListPage.test.tsx) — Agent Roles page rendering
- [frontend/src/__tests__/AgentIdentityListPage.test.tsx](../../../../frontend/src/__tests__/AgentIdentityListPage.test.tsx) — Agent Identities page rendering

---

### 3. Agent Types Table — Role and Identity Columns

**What is tested:**
- "Role" column displays the role name for each agent type
- "Identity" column displays the identity name for each agent type
- Columns show the human-readable name, not a raw ID or technical key
- Null role or identity renders a dash or placeholder, not a crash or blank render

**Acceptance criteria:**
- Role column present; shows role name, or dash/placeholder when `role_id` is null
- Identity column present; shows identity name, or dash/placeholder when `identity_id` is null
- No render error on agent types without role or identity assignments

**Test files:**
- [frontend/src/__tests__/AgentManagementPage.test.tsx](../../../../frontend/src/__tests__/AgentManagementPage.test.tsx) — Role and Identity column rendering; null state placeholders
- [e2e/tests/agent-navigation.spec.ts](../../../../e2e/tests/agent-navigation.spec.ts) — Agent Types table column smoke (names visible, no crash)

---

### 4. Agent Type Details Dialog

**What is tested:**
- Dialog opens when an agent type row is clicked; row action buttons (Edit, Launch, Plan Preview) do not open dialog
- Tab state resets to Details (index 0) on every open; stale state from prior render does not carry over
- Details tab: all configured fields displayed; role and identity names are clickable links that open view dialogs without navigating away; links are non-clickable when `role_id` or `identity_id` is null
- Plan Preview tab: plan steps and topology rendered when plan exists; placeholder shown when `plan` is null
- Execution Logs tab: recent sessions fetched with a distinct React Query key (cache isolation); "View All Executions" closes dialog and navigates to `/agents/executions`
- Dialog shows `PermissionDeniedAlert` on 403; distinct error state on 404 or network failure
- Execution Logs tab error is isolated; Details and Plan Preview tabs unaffected
- Parent table refreshes automatically when dialog closes (no page reload required)

**Acceptance criteria:**
- Row click opens dialog; row action button clicks do not
- Tab state always resets to Details on open
- Role/identity name links open view dialogs inline; non-null check prevents clickable link when value is absent
- Parent Agent Types table shows updated data after dialog close without a page reload

**Test files:**
- [frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx](../../../../frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx) — Dialog rendering, tab switching, field display, error states, `stopPropagation` on action buttons
- [frontend/src/__tests__/AgentManagementPage.test.tsx](../../../../frontend/src/__tests__/AgentManagementPage.test.tsx) — Row click → dialog open; parent table refresh on dialog close
- [e2e/tests/agent-navigation.spec.ts](../../../../e2e/tests/agent-navigation.spec.ts) — Full dialog interaction: open, tab navigation, view dialog launch, close and table refresh

---

### 5. Role and Identity View Dialogs

**What is tested:**
- Role view dialog opens when the role name link is clicked in the Details tab
- Identity view dialog opens when the identity name link is clicked in the Details tab
- Both dialogs contain an "Edit" button that switches the dialog to edit mode
- Edit button is hidden or disabled for users without edit permissions
- All three dialog widths (`AgentTypeDetailsDialog`, role view, identity view) match `PlanPreviewModal`

**Acceptance criteria:**
- View dialogs open without navigating away from the agent type details context
- Edit button present and switches dialog to edit mode when clicked
- Edit button not visible to read-only users
- Dialog widths consistent with `PlanPreviewModal`

**Test files:**
- [frontend/src/__tests__/AgentRoleViewDialog.test.tsx](../../../../frontend/src/__tests__/AgentRoleViewDialog.test.tsx) — Role view dialog rendering, Edit button presence, edit mode switch
- [frontend/src/__tests__/AgentIdentityViewDialog.test.tsx](../../../../frontend/src/__tests__/AgentIdentityViewDialog.test.tsx) — Identity view dialog rendering, Edit button presence, edit mode switch
- [e2e/tests/agent-navigation.spec.ts](../../../../e2e/tests/agent-navigation.spec.ts) — Role and identity view dialog open/edit flows; dialog width assertions

---

### 6. Agent Executions Filtering

**What is tested:**
- Agent type dropdown populated from `useAgentTypes()` results
- Selecting an agent type passes `agent_type_id` as a query param to the sessions fetch
- React Query key includes `agentTypeId` to prevent cache collision with unfiltered page-level state
- Clearing the filter restores the unfiltered result set
- All page strings use "Executions" (not "Instances")
- `agentTypeId` prop pre-selects the dropdown when the component is embedded in the dialog

**Acceptance criteria:**
- Filter dropdown populated and functional
- Filter clears and restores correctly
- No "Instances" wording anywhere on the Agent Executions page

**Test files:**
- [frontend/src/__tests__/AgentInstanceDashboard.test.tsx](../../../../frontend/src/__tests__/AgentInstanceDashboard.test.tsx) — Dropdown population, filter application, cache key isolation, prop-controlled pre-selection, string assertions for "Executions"
- [e2e/tests/agent-navigation.spec.ts](../../../../e2e/tests/agent-navigation.spec.ts) — Agent Executions filter interaction end-to-end

---

### 7. i18n Translation Keys

**What is tested:**
- All navigation and UI strings for agent features use `t()` with registered keys
- New keys present in `en.json`: `nav.aiAgent`, `nav.agentTypes`, `nav.agentExecutions`, `nav.agentLogs`, `nav.agentRoles`, `nav.agentIdentities`
- `agents.sessions.dashboardTitle` uses "Executions" wording
- `nav.agentInstances` removed or aliased; no leftover `t('nav.agentInstances')` calls in production code

**Acceptance criteria:**
- No hardcoded English strings in changed components
- No missing key warnings in browser console for agent nav items

**Test files:**
- [e2e/tests/agent-navigation.spec.ts](../../../../e2e/tests/agent-navigation.spec.ts) — UI text assertions use i18n-resolved values; missing keys would surface as key-string labels

---

### 8. A2A Delegation Preview and Slug Validation

**What is tested:**
- Agent type create/edit form enforces slug-safe names with inline validation feedback
- Plan preview list includes `agent_delegation` steps from generated plan payload
- Topology preview renders delegated agent type nodes/edges
- Agent role edit dialog shows allowed delegated target agent type slugs

**Acceptance criteria:**
- Non-slug agent type name is rejected before save
- Plan preview and topology both show delegated agent type when present in plan payload
- Allowed delegated agent type slug list is visible in role edit dialog

**Test files:**
- [frontend/src/__tests__/AgentTypeForm.test.tsx](../../../../frontend/src/__tests__/AgentTypeForm.test.tsx) — slug-safe name validation behavior in agent type form
- [frontend/src/__tests__/TopologyDiagramRenderer.test.tsx](../../../../frontend/src/__tests__/TopologyDiagramRenderer.test.tsx) — delegated node/edge rendering in topology diagram
- [frontend/src/__tests__/PlanPreviewModal.test.tsx](../../../../frontend/src/__tests__/PlanPreviewModal.test.tsx) — plan step rendering including delegation step types
- [frontend/src/__tests__/AgentRoleDialog.test.tsx](../../../../frontend/src/__tests__/AgentRoleDialog.test.tsx) — role dialog delegated-target preview rendering
- [e2e/tests/agent-a2a-communication.spec.ts](../../../../e2e/tests/agent-a2a-communication.spec.ts) — end-to-end UI coverage for slug enforcement and delegation previews

---

### 9. Agent Type Guardrail Profile UI (add-agent-execution-guardrails)

**What is tested:**
- Guardrail editor remains collapsed by default in create/edit flows
- Guardrail section adapts by input type (conversational versus non-conversational)
- Token controls render using k-token presentation in editor and details surfaces
- Agent details dialog renders guardrail profile values for operator review

**Acceptance criteria:**
- Guardrail section is closed on first render and opens on explicit user action
- Conversational forms show conversational token-visibility controls and hide non-conversational token-enforcement controls
- Non-conversational forms show token-enforcement controls and token budget units
- Details dialog displays readable guardrail profile values, including token budget formatting

**Test files:**
- [frontend/src/__tests__/AgentTypeForm.test.tsx](../../../../frontend/src/__tests__/AgentTypeForm.test.tsx) — collapsed-by-default behavior and input-type-aware guardrail controls
- [frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx](../../../../frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx) — guardrail profile rendering and k-token formatting in details dialog
- [e2e/tests/agent-management.spec.ts](../../../../e2e/tests/agent-management.spec.ts) — guardrail controls visible in create/edit dialog flows
- [e2e/tests/agent-navigation.spec.ts](../../../../e2e/tests/agent-navigation.spec.ts) — details dialog guardrail section visibility and values

---

### 10. Agent Type Form Default SOP Behavior (ai-assisted-workflow-authoring-for-sop-and-skill)

**What is tested:**
- Agent type form uses "Default SOP" terminology (legacy "Primary SOP" wording is not shown)
- Default SOP dropdown is visible for all input types (`none`, `typed`, `conversation`)
- Default SOP is required only for no-input agent types and optional for other input types
- Switching input type away from no-input does not clear an already-selected default SOP value
- Agent type payload preserves `primary_sop_id` for all input types; client-side validation enforces required-only-for-none behavior

**Acceptance criteria:**
- Default SOP label appears consistently in create and edit flows
- Required marker appears only when input type is `none`
- Existing selected SOP remains when input type changes
- Save payload includes `primary_sop_id` when selected, regardless of input type

**Test files:**
- [frontend/src/__tests__/AgentManagementPage.test.tsx](../../../../frontend/src/__tests__/AgentManagementPage.test.tsx) — Default SOP label coverage, required/optional behavior by input type, payload behavior for `primary_sop_id`

---

### 11. Model Configurations — Expanded Provider Dropdown

**What is tested:**
- Provider-type dropdown in the create/edit dialog lists all 12 providers with human-readable i18n labels; no hard-coded English strings in the component
- Each of the 12 providers renders a distinct chip colour on the list page; no two providers share a colour; compute coverage is machine-checked
- Full create → read → update → delete lifecycle for a new-provider config through the UI; parent table refreshes automatically after each dialog close without a manual page reload
- Edit dialog pre-populates display name, the correct provider in the dropdown, `api_base_url`, `enabled_models` chips, and the API-key placeholder (never the raw value)
- Provider-type change during edit (e.g. from `gemini` to `mistral`) persists and the chip colour and label update in the list page
- Delete confirmation dialog is in place; on confirm the row is removed; on cancel it remains
- Recreate after delete: an admin can create a new config with the same display name, same provider, and a fresh API key confirming true deletion
- Disable/enable toggle works for each new provider with the same cascade semantics as incumbent providers
- "Fetch Models" returns a non-empty list for each provider; failure degrades gracefully with the "no models returned" state
- API-key placeholder semantics: editing a config with a stored credential shows a placeholder; leaving the field unchanged preserves the stored credential; typing a new value replaces it; clearing the field explicitly removes the credential
- Dialog error pattern (`dialogError` state + `PermissionDeniedAlert`) is in place for all error paths (403, 409, 422, 500, network failure); errors appear inline in the dialog, not as silent failures
- i18n labels for all 8 new providers are present in `frontend/src/i18n/locales/en.json` under `agents.modelConfigs.providerLabels`; a missing key falls back gracefully to the raw provider key

**Acceptance criteria:**
- Dropdown lists exactly 12 providers in stable order; every label resolved through i18next `t()`
- Chip colours are machine-verified unique across all 12 keys; unknown key falls back to the `default` colour
- Create dialog inserts a row and closes without page reload; parent table updates automatically
- Edit dialog pre-populates all fields correctly including the placeholder never showing the raw key
- Provider-type change on update persists and chip colour updates in the list
- Delete confirm/cancel behaviour works; 409 deletes blocked by referencing AgentType
- Recreate after delete confirms true deletion
- Disable/enable toggle works with same semantics as incumbent providers
- "Fetch Models" returns models or shows the empty state on failure
- All dialogs follow the project's `dialogError` + `PermissionDeniedAlert` standard

**Test files:**
- [frontend/src/__tests__/ModelConfigDialog.test.tsx](../../../../frontend/src/__tests__/ModelConfigDialog.test.tsx) — dropdown lists 12 providers, create/edit/delete reload-free, edit pre-population, dialog error pattern, placeholder semantics, recreate after delete
- [frontend/src/__tests__/ModelConfigListPage.test.tsx](../../../../frontend/src/__tests__/ModelConfigListPage.test.tsx) — chip rendering for all 12 providers, chip-colour-uniqueness machine-check, parent table refresh, delete confirmation, reload-free behaviour
- [e2e/tests/agent-runtime.spec.ts](../../../../e2e/tests/agent-runtime.spec.ts) — `Model Config CRUD` block (mocked): list page chips, create/delete flows; `Real Backend Integration - Model Configurations` block: live backend round-trip, validates migration applied

---

## Manual Testing Requirements

| Scenario | Why Manual |
|---|---|
| Sidebar nav group header highlight when child route is active (visual) | CSS active-state styling requires visual confirmation; automated assertions cover presence, not visual weight |
| Collapsible nav group behavior on narrow/responsive sidebar | Responsive sidebar collapse is viewport-dependent; visual review confirms correctness beyond basic Playwright breakpoint checks |
| Dialog width matching `PlanPreviewModal` across viewports | Pixel-accurate width comparison across breakpoints requires visual review or a dedicated visual regression tool |

---

## Edge Cases & Risks

- Menu children rendered in wrong order — breaks user muscle memory and documentation references; exact order must be verified
- Active highlight missing for Agent Roles / Agent Identities routes — no visual context when on those pages
- Role or Identity column showing a raw ID instead of a human-readable name
- Null role or identity crashing the Agent Types table row render
- `AgentTypeDetailsDialog` tab state carrying over between opens (stale `agentTypeId` from prior render)
- React Query cache collision between Execution Logs tab fetch (`['agents', 'sessions', 'dialog', agentTypeId]`) and the page-level sessions cache
- Parent table not refreshing after dialog close — stale data displayed until manual reload
- Row action buttons (Edit, Launch, Plan Preview) accidentally opening the details dialog due to missing `stopPropagation`
- Clickable role/identity name triggering when `role_id`/`identity_id` is null — view dialog opens with no ID and may crash
- Edit button visible to read-only users — must be hidden or disabled by permission check
- `/agents/instances` redirect missing — bookmarks and deep links 404 after rename
- Missing i18n keys causing key-string literals to render in production

---

## Change History

| Change | Description | Added |
|--------|-------------|-------|
| unified-agent-navigation | AI Agent nav group; AgentTypeDetailsDialog; Role/Identity columns; Agent Executions filter; view dialogs with Edit mode; legacy redirect | 2026-05-10 |
| agent-a2a-communication-and-slug-enforcement | Added A2A delegation preview and slug validation coverage (agent type naming, role allowed-target preview, plan/topology delegation rendering) | 2026-05-22 |
| add-agent-execution-guardrails | Added Agent Type guardrail profile UI coverage (collapsed editor behavior, input-type adaptation, and k-token rendering checks) | 2026-05-25 |
| ai-assisted-workflow-authoring-for-sop-and-skill | Added Agent Type form Default SOP behavior coverage (label rename, visibility across input types, required-only-for-none validation, and payload preservation) | 2026-05-29 |
| expand-model-config-providers | Added Model Configurations — Expanded Provider Dropdown coverage (12-provider dropdown, chip colour uniqueness, full CRUD lifecycle, dialog error pattern, i18n labels, reload-free parent table refresh) | 2026-06-03 |
