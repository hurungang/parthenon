# Module: frontend — Agent Surfaces

> Part of the [frontend hub](tech-spec.md) · [technology documentation](../../README.md).

## Overview

This page covers the agent-editing surfaces: role/identity/type/model-configuration pages, the **Agent Management Panel** (the single editing surface for agent composition), the agent type details dialog, the implementation/optimized plan views, the Optimize action, guardrail configuration, the API-key UI, and the single-surface skill tool-binding editor.

All editing state is client-side React Query cache plus the panel's draft composition; the backend contract is the agent-type create/update endpoint (structured 409/422 binding errors). Plan generation is explicit only — there is no implicit generation on save.

---

## Agent CRUD pages

| Component | Description |
|-----------|-------------|
| `AgentRoleListPage` / `AgentRoleDialog` | Role table and editor: SOP/Skill multi-select, live MCP tool preview, assigned identities, inline per-server MCP session dropdowns (save blocked until every required server has a session), passthrough badges, target-agent-slug preview |
| `AssignIdentitiesToRoleDialog` / `AssignRolesToIdentityDialog` | Bulk role↔identity assignment dialogs |
| `AgentIdentityListPage` / `AgentIdentityDialog` | Identity table (realm, token/identity status, refresh/re-auth) and editor with the "Sign In as Agent" OAuth popup |
| `AgentOAuthCallbackPage` | OAuth popup callback; exchanges the code and postMessages the result |
| `AgentTypeForm` | Full agent type form used by the create dialog (and legacy create/edit flows): in-line fields, SOP/skill binding list with add/remove/reorder, role-filtered binding picker, orphan detection, guardrail group, identity-must-be-assigned-to-role validation |
| `AgentManagementPage` | Agent types table; row click opens `AgentTypeDetailsDialog`; Role/Identity name columns; per-row Launch + gated Optimize actions |
| `AgentInstanceDashboardPage` ("Agent Executions") | Execution list at `/agents/executions` (legacy `/agents/instances` redirects); filters; View opens `AgentExecutionDetailsDialog` |
| `ModelConfigListPage` / `ModelConfigDialog` | Model configuration table/editor; workflow-generation selection lives on the System Config page |
| `VendorModelGuardrailPanel` / `AddGuardrailForm` | Vendor → model → guardrail hierarchy with availability toggles and per-period limits |

## Agent Management Panel

Unified composition page at `/agents/panel`. Three regions — agent list sidebar / live topology / property bar. The property bar is the single editing surface for ALL agent properties (no edit dialog); every edit mutates a client-side draft saved by exactly one agent-type PUT.

| Component | Description |
|-----------|-------------|
| `AgentManagementPanelPage` | Panel page: layout, selection, header card (create dialog + delete confirm), property-bar wiring, assign-existing picker routing |
| `AgentPropertiesSection` | Property-bar "Properties" section: name (slug validation), description, system instruction, full guardrail set — draft-only edits |
| `AgentListSidebar` | Agent list with client-side search/filter and selection state |
| `EquipmentSlots` / `EQUIPMENT_SLOT_DEFINITIONS` | Seven permission-gated slots (role, identity, skills, SOPs, input data type, output data type, model); dashed placeholders, locked conversational output slot, 403 explanations |
| `dataTypeToInputSchema` | Maps a data type's fields to the input slot's JSON schema |
| `ResourcePickerDialog` / `ResourcePickerItem` / `ResourcePickerSelectionMode` | Generic searchable, paginated picker (single/multi, equipped pre-selection with `baselineIds`, inline create) |
| `SlotResourcePickerDialog` / `SLOT_PICKER_CONFIGS` / `getSlotPickerConfig` / `SlotPickerConfig` / `SlotDraftApi` | Per-slot picker registry and wrapper (query key, row mapping, selection mode, preset, draft apply) |
| `SharedDialogHost` / `PendingChangesTray` | Shared module-dialog host (create-and-assign contract) and dirty-changes save/discard bar with structured per-binding errors |
| `useAgentDraftComposition` | Draft state hook: init/dirty/snapshot/discard, deduplicated save payload, in-flight guard |
| `useUnsavedChangesDialog` | Discard/keep-editing confirmation |
| `/agents/panel` route + sidebar entry | Protected route and Agents-group nav entry |

## Topology

`PanelTopologyCanvas` is the single canonical topology view — used by both the panel and the agent type details preview (all agent types). Three states are strictly distinguished: **pending** (request in flight, name not cached), **genuinely missing** (request completed, row absent → raw id), and **deliberately empty/set** (dashed placeholder or solid None/Conversation/Auto node).

| Component | Description |
|-----------|-------------|
| `PanelTopologyCanvas` / `buildPanelTopology` | Zoned graph (capabilities → Communication Hub bar → tools), fullscreen zoom/pan, node-click detail, per-container token-health badges |
| `PanelTopologyNames` / `PanelTopologyLabels` / `PanelTopologyGraph` / `PanelTopologyPending` / `NO_PENDING` | Label maps, contract-slot labels, zoned graph shape and typed in-flight flags |
| `capabilityColor` / `mcpGroupColor` | Deterministic accent colours for capability nodes and MCP server groups |
| `TopologyDiagramRenderer` / `TopologyHubBar` / `TopologyNode.pending` / `PendingSpinner` | Shared layered SVG renderer, hub bar declaration, pending marker and viewBox-unit spinner |
| `TopologyNodeIcon` / `NODE_TYPE_ICONS` | Entity-type icons with explicit nested-SVG geometry |
| `estimateTextWidth` / `fitTextToWidth` | ViewBox-unit label fitting/truncation |
| `withCommunicationHub` / `COMMUNICATION_HUB_NODE_ID` | Appends the hub node to generic preview topologies |
| `agentTypeToDraftComposition` | Pure adapter from a loaded agent type to the canvas draft shape |
| `TOPOLOGY_MAX_FONT_SCALE` | Fullscreen font-scale cap (zoom reveals more content, not bigger text) |

## Agent type details and plans

| Component | Description |
|-----------|-------------|
| `AgentTypeDetailsDialog` | Details / **Agent Topology** / **Implementation Plan** / Execution Logs / Sessions / Optimized Plan / Clients tabs; header Refresh re-reads agent type, sessions, scripts, gate, roles and identities; "Run Agent" opens the launch dialog; plan generation shows a generating spinner |
| `AgentPlanContent` / `PlanPreviewModal` | Base-plan step rendering (per-step "View script" on `script_version_id` steps) and the preview modal |
| `PlanStepTree` | Shared tree renderer: flat steps with optional `parent_order` nesting, action icons, type chips |
| `AgentOptimizedPlanTab` | Compact entry (optimizer model + "Talk to optimizer" + help), plan status/feedback, `requires_fix` alert + re-optimize, `needs_feedback` blocker, retire states; mounts the optimization dialog once outside the loading/no-plan branches |
| `AgentOptimizeAction` | One-shot Optimize trigger: self-hides for conversational agents, disabled with the localized backend reason, failures surface as a snackbar |
| `OptimizationHelpDialog` | Interaction-model help (runs as this agent, replay-only, live test needs approval, ask-and-stop) |
| `ScriptViewDialog` | Inline python_source/description/version viewer |
| `AgentJobLaunchDialog` | Dynamic input form per `input_type`; execution-only (no optimization opt-in, no plan generation) |
| `AgentExecutionsDialog` / `AgentExecutionDetailsDialog` | Dialog wrappers for the execution list and a single execution (Execution / Result / Conversation History tabs) |

## Guardrails, API keys and skill bindings

| Component | Description |
|-----------|-------------|
| `LogPresenter` / `LogSummaryPanel` | Guardrail usage summaries and conversational token-visibility chips derived from execution log entries |
| `LogViewer` / `WorkingStepsPanel` / `RawLogToggle` | Execution log display (summary, steps, raw mode) |
| `useExecutionLogs` / `useSessionExecutionLogStream` | Log pull and live stream hooks |
| `ApiKeyListPage` / `CreateApiKeyDialog` / `RevokeApiKeyDialog` / `useApiKeys` / API-key API functions and types | API key management UI |
| `SkillEditor` (`selectedToolIds`, `buildSkillToolEntries`, `groupToolEntries`) | Single binding surface: grouped list is both display and editor; explicit unbind; referenced `cc` entries pinned read-only and never dropped on save |
| `SkillListPage` tool column | "N tools" count with tooltip and an explicit "No tools bound" chip |

---

## Code Reference Map

### Agent CRUD pages

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentRoleListPage` / `AgentRoleDialog` / `AssignIdentitiesToRoleDialog` | components | Role list, editor and bulk assignment | `frontend/src/pages/agents/AgentRoleListPage.tsx`, `frontend/src/components/agents/AgentRoleDialog.tsx`, `frontend/src/pages/agents/AssignIdentitiesToRoleDialog.tsx` |
| `AgentIdentityListPage` / `AgentIdentityDialog` / `AssignRolesToIdentityDialog` / `AgentOAuthCallbackPage` | components | Identity list/editor, role assignment, OAuth popup callback | `frontend/src/pages/agents/AgentIdentityListPage.tsx`, `frontend/src/components/agents/AgentIdentityDialog.tsx`, `frontend/src/pages/agents/AssignRolesToIdentityDialog.tsx`, `frontend/src/pages/agents/AgentOAuthCallbackPage.tsx` |
| `AgentTypeForm` / `AgentTypeFormValues` / `defaultAgentTypeFormValues` | component / interface / constant | Shared controlled agent create form (bindings, guardrails, validation) | `frontend/src/pages/agents/AgentTypeForm.tsx` |
| `AgentManagementPage` | page | Agent types table, row dialog, Role/Identity columns, Launch + Optimize actions | `frontend/src/pages/agents/AgentManagementPage.tsx` |
| `AgentInstanceDashboardPage` | page | Execution list with filters and dialog open | `frontend/src/pages/agents/AgentInstanceDashboardPage.tsx` |
| `ModelConfigListPage` / `ModelConfigDialog` | components | Model configuration CRUD | `frontend/src/pages/agents/ModelConfigListPage.tsx`, `frontend/src/components/agents/ModelConfigDialog.tsx` |
| `VendorModelGuardrailPanel` / `AddGuardrailForm` | components | Vendor/model availability + per-period guardrails | `frontend/src/components/agents/VendorModelGuardrailPanel.tsx`, `AddGuardrailForm.tsx` |

### Agent Management Panel

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentManagementPanelPage` | page | Panel layout and wiring | `frontend/src/pages/agents/AgentManagementPanelPage.tsx` |
| `AgentPropertiesSection` / `AgentListSidebar` / `EquipmentSlots` / `EQUIPMENT_SLOT_DEFINITIONS` / `dataTypeToInputSchema` | components / constants / function | Property bar, list, equipment slots | `frontend/src/components/agents/panel/AgentPropertiesSection.tsx`, `AgentListSidebar.tsx`, `EquipmentSlots.tsx` |
| `ResourcePickerDialog` / `ResourcePickerItem` / `ResourcePickerSelectionMode` | component / interfaces | Generic picker | `frontend/src/components/agents/panel/ResourcePickerDialog.tsx` |
| `SlotResourcePickerDialog` / `SLOT_PICKER_CONFIGS` / `getSlotPickerConfig` / `SlotPickerConfig` / `SlotDraftApi` | component / constants / types | Per-slot picker bindings | `frontend/src/components/agents/panel/SlotResourcePickerDialog.tsx`, `slotPickerConfigs.tsx` |
| `SharedDialogHost` / `PendingChangesTray` | components | Shared dialog host + dirty tray | `frontend/src/components/agents/panel/SharedDialogHost.tsx`, `PendingChangesTray.tsx` |
| `useAgentDraftComposition` | hook | Draft composition state and save mapping | `frontend/src/hooks/useAgentDraftComposition.ts` |
| `useUnsavedChangesDialog` / `usePagination` / `useDataTypes` / `useCreateDataType` / `useUpdateDataType` | hooks | Discard guard, pagination, data-type registry access | `frontend/src/hooks/useUnsavedChangesDialog.tsx`, `usePagination.ts`, `useDataTypes.ts` |
| `/agents/panel` route + sidebar entry | route / nav | Panel registration | `frontend/src/app/AppRouter.tsx`, `frontend/src/app/AppShell.tsx` |

### Topology

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `PanelTopologyCanvas` / `buildPanelTopology` / `PanelTopologyNames` / `PanelTopologyLabels` / `PanelTopologyGraph` | component / functions / interfaces | Canonical zoned topology + composer | `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` |
| `PanelTopologyPending` / `NO_PENDING` | types / constant | Typed per-entity in-flight flags | `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` |
| `capabilityColor` / `mcpGroupColor` | functions | Deterministic node/group colours | `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` |
| `TopologyDiagramRenderer` / `TopologyHubBar` / `PendingSpinner` | components / interface | Shared SVG renderer, hub bar, pending spinner | `frontend/src/components/agents/TopologyDiagramRenderer.tsx` |
| `TopologyNodeIcon` / `NODE_TYPE_ICONS` | component / constant | Entity-type icons | `frontend/src/components/agents/topologyNodeIcons.tsx` |
| `estimateTextWidth` / `fitTextToWidth` | functions | ViewBox-unit label fitting | `frontend/src/components/agents/topologyTextFit.ts` |
| `withCommunicationHub` / `COMMUNICATION_HUB_NODE_ID` | function / constant | Hub node append helper | `frontend/src/components/agents/topologyHub.ts` |
| `agentTypeToDraftComposition` | function | Loaded agent type → canvas draft adapter | `frontend/src/components/agents/agentTypeToDraftComposition.ts` |
| `TOPOLOGY_MAX_FONT_SCALE` | constant | Fullscreen font-scale cap | `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` |

### Plans, optimization and dialogs

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentTypeDetailsDialog` | component | Tabbed agent details, plan tabs, refresh, run action | `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` |
| `AgentPlanContent` / `PlanPreviewModal` | components | Base plan rendering and preview | `frontend/src/components/agents/AgentPlanContent.tsx`, `PlanPreviewModal.tsx` |
| `PlanStepTree` | component | Shared nested step renderer | `frontend/src/components/agents/PlanStepTree.tsx` |
| `AgentOptimizedPlanTab` | component | Optimized Plan tab + optimizer entry | `frontend/src/components/agents/AgentOptimizedPlanTab.tsx` |
| `AgentOptimizeAction` | component | One-shot Optimize trigger | `frontend/src/components/agents/AgentOptimizeAction.tsx` |
| `OptimizationHelpDialog` / `ScriptViewDialog` | components | Help and script viewer | `frontend/src/components/agents/OptimizationHelpDialog.tsx`, `ScriptViewDialog.tsx` |
| `AgentJobLaunchDialog` | component | Execution-only launch dialog | `frontend/src/pages/agents/AgentJobLaunchDialog.tsx` |
| `AgentExecutionsDialog` / `AgentExecutionDetailsDialog` / `AgentRoleViewDialog` / `AgentIdentityViewDialog` | components | Dialog wrappers and read-only entity views | `frontend/src/components/agents/` |
| `useAgentTypes` / `useAgentType` / `useDeleteAgentType` | hooks | Agent type queries and delete mutation | `frontend/src/hooks/useAgentTypes.ts` |
| `useOptimizationGate` | hook | Gate read, polling rules, localized reason helpers | `frontend/src/hooks/useOptimizationGate.ts` |
| `useScripts` family | hooks | Script registry queries and mutations | `frontend/src/hooks/useScripts.ts` |

### Guardrails, logs, API keys and skills

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `LogPresenter` / `presentLog` | service / function | Execution log → structured summary/steps/raw | `frontend/src/services/LogPresenter.ts` |
| `LogViewer` / `LogSummaryPanel` / `WorkingStepsPanel` / `RawLogToggle` | components | Execution log surfaces | `frontend/src/components/executions/LogViewer.tsx`, `LogSummaryPanel.tsx`, `WorkingStepsPanel.tsx`, `RawLogToggle.tsx` |
| `useExecutionLogs` / `useSessionExecutionLogStream` | hooks | Log pull and live stream | `frontend/src/hooks/useExecutionLogs.ts`, `useSessionExecutionLogStream.ts` |
| `ApiKeyListPage` / `CreateApiKeyDialog` / `RevokeApiKeyDialog` | components | API key management | `frontend/src/pages/api-keys/ApiKeyListPage.tsx`, `CreateApiKeyDialog.tsx`, `RevokeApiKeyDialog.tsx` |
| `useApiKeys` / `fetchApiKeys` / `createApiKey` / `revokeApiKey` / `fetchIdentitiesWithRoles` | hook / functions | API key data layer | `frontend/src/hooks/useApiKeys.ts`, `frontend/src/api/apiKeysApi.ts` |
| `ApiKey` / `ApiKeyCreateRequest` / `ApiKeyCreateResponse` / `ApiKeyStatus` / `IdentityWithRoles` | types | API key wire types | `frontend/src/types/apiKeys.ts` |
| `SkillEditor` / `buildSkillToolEntries` / `groupToolEntries` | component / functions | Single binding surface with read-only referenced group | `frontend/src/components/agents/SkillEditor.tsx` |
| `SkillListPage` tool column | page block | Tool count + zero-binding chip | `frontend/src/pages/skills/SkillListPage.tsx` |

### Types and tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentRole` / `AgentIdentity` / `AgentType` / `AgentTypeSopBinding` / `AgentTypeSkillBinding` / `ModelConfig` / `ModelProviderType` / `AgentPlan` / `PlanStep` / `TopologyNode` / `TopologyEdge` | interfaces / types | Agent editing wire types | `frontend/src/types/index.ts` |
| `AgentDraftComposition` / `AgentEquipmentSlotId` / `EquipmentSlotDefinition` / `CreateAndAssignResult` / `PanelDialogRequest` | interfaces / types | Panel draft/slot contracts | `frontend/src/types/index.ts` |
| `AgentOptimizedPlanTab.test.tsx` / `AgentOptimizedPlanTab.optimizerEntry.test.tsx` / `PlanStepTree.test.tsx` | tests | Plan/optimizer UI states and optimizer entry | `frontend/src/__tests__/AgentOptimizedPlanTab.test.tsx`, `AgentOptimizedPlanTab.optimizerEntry.test.tsx`, `PlanStepTree.test.tsx` |
| `AgentManagementPanelPage.test.tsx` / `AgentManagementPage.test.tsx` / `AgentTypeForm.test.tsx` / `AgentRoleDialog.test.tsx` / `AgentTypeDetailsDialog.test.tsx` | tests | Panel, table, form, role and dialog regressions | `frontend/src/__tests__/` |
| `PanelTopologyCanvas.test.tsx` / `TopologyDiagramRenderer.test.tsx` / `agentTypeToDraftComposition.test.ts` | tests | Pending vs missing vs empty, font cap, adapter purity | `frontend/src/__tests__/` |
| `agent-management-panel-topology.spec.ts` / `agent-type-preview-topology.spec.ts` / `agent-type-bindings*.spec.ts` | E2E tests | Panel/preview parity, contract slots, binding flows | `e2e/tests/` |
