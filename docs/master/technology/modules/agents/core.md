# Module: agents — Core (types, roles, identities, models)

> Part of the [agents hub](tech-spec.md) · [technology documentation](../../README.md).

## Overview

This page covers the definitional half of the agents module: agent roles, first-class agent identities, agent types and their SOP/skill bindings, model configurations and model binding, the **permission/visibility** resolution algorithm, and the admin surfaces used to edit them (CRUD pages, the Agent Management Panel and its topology, and the skill tool-binding editor).

Nothing here executes an agent; the execution pipeline lives in [execution.md](execution.md).

---

## Permission and visibility

A role controls **permission**; an agent type controls **visibility**. The effective tool set is computed per call from three reads:

1. **Visibility** — the agent type's own `AgentTypeSkillBinding` skills, plus the skills reached by its bound SOPs' `skill_invocation` steps, expanded through `SkillToolBinding → McpTool`.
2. **Permission** — `AgentPermissionManager.calculate_allowed_tools(role_id, db)`, the role's grant chain.
3. **Intersection** — `calculate_agent_allowed_tools(agent_type_id, db)` returns visibility ∩ permission. A bound skill the role does not grant stays invisible.

Delegation targets follow the same shape: `calculate_agent_allowed_agent_types` derives targets from the agent type's own `agent_delegation` SOP steps and intersects them with the role-derived targets (falling back to the SOP targets when the role derives none). Inherent `system____` tools are added at the hub layer and are not affected.

Caching is per agent type (`_agent_visibility_cache`, `_agent_visibility_agent_types_cache`). `invalidate(role_id)` clears every agent-visibility entry (a role change affects all agents); `invalidate_agent_type()` clears one and is called from `AgentTypeService.set_bindings` and when an agent type's `role_id` changes.

---

## Key Components

### Roles and identities

| Component | Description |
|-----------|-------------|
| `AgentRoleService` | Role CRUD; `assign_identities` / `remove_identity` / `list_identities` / `is_identity_assigned`; MCP session assignment with one-session-per-server enforcement; `get_available_mcp_sessions` (filtered to servers whose tools the role uses, carrying `auth_type`); invalidates the permission cache on writes |
| `AgentIdentityService` | Identity CRUD; OAuth authorize URL generation; code exchange; encrypted access/refresh token storage; `refresh_token`, `get_reauth_url`; `assign_roles` / `remove_role` / `list_roles` |
| `RealmManager` | Agent-realm bootstrap in the OIDC provider: token policies and the platform OAuth client for the code flow |
| `TokenRefreshService` (background) | Proactively refreshes stored agent OAuth tokens before expiry; re-encrypts the token pair |

### Agent types and bindings

| Component | Description |
|-----------|-------------|
| `AgentTypeService` | CRUD; `set_bindings` replaces ordered SOP/skill binding lists (dedupe + bulk delete/insert), raising the structured `binding_conflict` on concurrent collisions; invalidates the agent's visibility cache |
| `validate_bindings` | Rejects binding entries outside the role's assigned SOPs/skills and duplicate references, with per-binding structured errors |
| `binding error envelopes` | 422 `binding_validation_failed` (`messages` for compatibility + structured `errors`) and 409 `binding_conflict` (per-binding detail) |

### Models

| Component | Description |
|-----------|-------------|
| `ModelConfigService` | CRUD for `ModelConfig`; encrypts/decrypts credentials; `fetch_available_models` returns `enabled_models` or queries the provider live |
| `ModelBindingLayer` | Resolves an `AgentType.model_id` string to a `ModelConfig`; dispatches 12 providers across two families (OpenAI-compatible: `openai`, `azure_openai`, `litellm_proxy`, `mistral`, `groq`, `together`, `fireworks`, `perplexity`, `deepseek`; native-API: `anthropic`, `gemini`, `cohere`); `build_completion_context` supplies `{provider_type, api_base_url, api_key}` for explicit-model calls |
| `PROVIDER_REGISTRY` | Per-provider dispatch family and default API base URL |
| `LangChainModelFactory` | Instantiates the LangChain chat model for a resolved `model_id` (or the mock provider when mock mode is active) |

Workflow-generation, assistant and optimizer model selections are documented in [plans-optimization.md](plans-optimization.md), [assistant.md](assistant.md) and [plans-optimization.md](plans-optimization.md) respectively.

---

## API Endpoints

### Agent roles

| Method | Path | Purpose |
|--------|------|---------|
| `GET` / `POST` | `/api/v1/agents/roles` | List roles (SOP/skill id lists); create role + join rows atomically |
| `GET` / `PUT` / `DELETE` | `/api/v1/agents/roles/{id}` | Detail; replace grants (invalidates cache); delete (409 while referenced by an agent type) |
| `GET` | `/api/v1/agents/roles/{id}/mcp-tools` | Resolved MCP tool identifiers for the role |
| `POST` / `DELETE` / `GET` | `/api/v1/agents/roles/{role_id}/identities[/{identity_id}]` | Bulk assign / remove / list assigned identities |
| `POST` / `DELETE` / `GET` | `/api/v1/agents/roles/{role_id}/mcp-sessions[/{session_id}]` | Assign / remove / list MCP sessions (one per server) |
| `GET` | `/api/v1/agents/roles/{role_id}/available-mcp-sessions` | Assignable sessions for the role's servers (includes `auth_type`) |

### Agent identities

| Method | Path | Purpose |
|--------|------|---------|
| `GET` / `POST` | `/api/v1/agents/identities` | List; create placeholder identity |
| `GET` / `PUT` / `DELETE` | `/api/v1/agents/identities/{id}` | Detail; update; delete (409 while referenced) |
| `POST` / `DELETE` / `GET` | `/api/v1/agents/identities/{identity_id}/roles[/{role_id}]` | Bulk assign / remove / list roles |
| `POST` | `/api/v1/agents/identities/{identity_id}/refresh-token` | Refresh the access token |
| `GET` | `/api/v1/agents/identities/{identity_id}/reauth-url` | OAuth re-authentication URL |
| `GET` | `/api/v1/agents/identities/oauth/authorize` | Authorization URL (`?identity_id=`) |
| `GET` | `/api/v1/agents/oauth/callback` | OIDC redirect handler; exchanges code, stores encrypted tokens, activates the identity |

### Agent types

| Method | Path | Purpose |
|--------|------|---------|
| `GET` / `POST` | `/api/v1/agents/types` | List; create (guardrail defaults/validation; binding errors 422/409; `plan` included). Creation does **not** generate a plan |
| `GET` / `PUT` / `DELETE` | `/api/v1/agents/types/{type_id}` | Detail; update (same binding contract; visibility-cache invalidation on role change); delete |
| `GET` | `/api/v1/agents/types/{type_id}/instances` | Active instances |
| `DELETE` | `/api/v1/agents/instances/{instance_id}` | Terminate an instance |

### Model configurations

| Method | Path | Purpose |
|--------|------|---------|
| `GET` / `POST` | `/api/v1/agents/model-configs` | List; create (credentials AES-256 encrypted) |
| `GET` / `PUT` / `DELETE` | `/api/v1/agents/model-configs/{id}` | Detail (never returns credentials); update (omitted `api_key` keeps the credential); delete (409 while referenced) |
| `GET` | `/api/v1/agents/model-configs/{id}/models` | `enabled_models`, or a live provider listing |

---

## Frontend surfaces

| Surface | Description |
|---------|-------------|
| Role pages | `AgentRoleListPage` + `AgentRoleDialog` (SOP/skill selection, live MCP tool preview, inline per-server session dropdowns, target-agent preview), `AssignIdentitiesToRoleDialog` |
| Identity pages | `AgentIdentityListPage`, `AgentIdentityDialog` ("Sign In as Agent" OAuth popup), `AssignRolesToIdentityDialog`, `AgentOAuthCallbackPage` |
| Agent type pages | `AgentTypeForm` (create dialog + shared form), `AgentManagementPage` (table, details dialog, Launch/Optimize actions) |
| Model pages | `ModelConfigListPage`, `ModelConfigDialog`, `VendorModelGuardrailPanel`, `AddGuardrailForm` |
| Agent Management Panel | `/agents/panel`: property bar is the single editing surface; draft composition; seven equipment slots; shared resource picker; create-and-assign dialogs; save maps to one PUT |
| Topology | `PanelTopologyCanvas` (single canonical view for panel and preview): zoned capabilities → hub bar → tools, pending/missing/empty states, fullscreen zoom cap, node-click detail |
| Skill bindings | `SkillEditor` single-surface grouped list with referenced `cc` entries pinned read-only |

---

## Code Reference Map

### Models and schemas

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentRole` / `AgentRoleSOP` / `AgentRoleSkill` / `AgentRoleIdentity` | models | Role and its SOP/skill/identity joins (`AgentRoleIdentity` is the authoritative identity-role link) | `backend/app/db/models/agents.py` |
| `AgentIdentity` / `AgentIdentityType` / `AgentIdentityStatus` | model / enums | OIDC identity entity with encrypted tokens and token health fields | `backend/app/db/models/agents.py` |
| `AgentType` | model | `identity_id`, `role_id`, `model_id`, `system_instruction`, `input_type`/`input_schema`, `output_type`/`output_schema`, `output_data_type_id`, guardrail fields; removed legacy `mode`/`primary_sop_id`/`llm_*` fields | `backend/app/db/models/agents.py` |
| `AgentTypeSopBinding` / `AgentTypeSkillBinding` | models | Ordered bindings (unique per agent type + resource, surrogate UUID PK) | `backend/app/db/models/agents.py` |
| `AgentInputType` / `AgentOutputType` | enums | `none` / `typed` / `conversation`; `auto` / `typed` / `markdown` | `backend/app/db/models/agents.py` |
| `AgentInstance` / `AgentInstanceStatus` | model / enum | Session-handle tracking (`created` / `active` / `closed` / `error`) | `backend/app/db/models/agents.py` |
| `ModelConfig` | model | Provider config: `provider_type`, `display_name`, `api_base_url`, encrypted `api_key`, `enabled_models` | `backend/app/db/models/agents.py` |
| `ModelGuardrailConfiguration` / `ModelAvailability` / `ModelGuardrailPeriod` / `ModelGuardrailEnforcementPosture` / `ModelUsageUnit` / `ModelAvailabilityDisabledReason` | models / enums | Per-period model usage limits and vendor/model availability | `backend/app/db/models/model_guardrail_configuration.py`, `backend/app/db/models/model_availability.py` |
| `AgentRoleCreate` / `AgentRoleUpdate` / `AgentRoleRead` / `AgentRoleIdentityAssignment` / `AgentRoleAssignment` | schemas | Role contracts (grant id lists) | `backend/app/schemas/agents.py` |
| `AgentIdentityCreate` / `AgentIdentityUpdate` / `AgentIdentityRead` / `AgentIdentityOAuthAuthorizeResponse` | schemas | Identity contracts (derived token status, never raw tokens) | `backend/app/schemas/agents.py` |
| `AgentTypeCreate` / `AgentTypeUpdate` / `AgentTypeRead` | schemas | Agent type contracts incl. bindings, guardrails and derived `output_data_type_name`; UI-parity baseline | `backend/app/schemas/agents.py` |
| `SopBindingCreate` / `SopBindingResponse` / `SkillBindingCreate` / `SkillBindingResponse` / `BindingError` | schemas | Binding wire contracts and structured errors | `backend/app/schemas/agent_type_bindings.py` |
| `ModelConfigCreate` / `ModelConfigUpdate` / `ModelConfigRead` | schemas | Model config contracts (`api_key` write-only) | `backend/app/schemas/agents.py` |
| `_validate_guardrail_contract` | function | Guardrail bounds + conversational/no-enforce contract shared with the assistant tool handlers | `backend/app/schemas/agents.py` |

### Services

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentRoleService` | class | Role CRUD, identity assignment, MCP session assignment, cache invalidation | `backend/app/services/agents/role_service.py` |
| `AgentIdentityService` | class | Identity CRUD, OAuth flow, encrypted tokens, role assignment | `backend/app/services/agents/identity_service.py` |
| `AgentPermissionManager` | class | Role permission + agent-type visibility intersection; A2A target resolution; per-agent-type caches | `backend/app/services/agents/permission_manager.py` |
| `_agent_visibility_cache` / `_agent_visibility_agent_types_cache` / `invalidate` / `invalidate_agent_type` | class state / methods | Visibility caches and invalidation paths | `backend/app/services/agents/permission_manager.py` |
| `RealmManager` | class | Agent realm bootstrap and OAuth client registration | `backend/app/services/identity/realm_manager.py` |
| `TokenRefreshService` | class | Background proactive token refresh for identities | `backend/app/services/agents/token_refresh_service.py` |
| `AgentTypeService` / `AgentTypeService.set_bindings` | class / method | Agent type CRUD; binding replacement with dedupe + visibility invalidation | `backend/app/services/agents/agent_type_service.py` |
| `validate_bindings` | function | Role-access validation for binding entries | `backend/app/services/agents/binding_validation.py` |
| `ModelConfigService` | class | Model config CRUD, credential encryption, model listing | `backend/app/services/agents/model_config_service.py` |
| `ModelBindingLayer` / `PROVIDER_REGISTRY` | class / constant | Model id → config → provider client; `build_completion_context` | `backend/app/services/agents/model_binding.py` |
| `LangChainModelFactory` / `LangChainModelFactoryError` | class / exception | Chat-model instantiation (incl. mock provider) | `backend/app/services/agents/langchain_model_factory.py` |

### API

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentRoleRouter` / `AgentIdentityRouter` / `AgentOAuthRouter` / `AgentTypeRouter` / `AgentInstanceRouter` / `ModelConfigRouter` | routers | Agent definition CRUD surfaces | `backend/app/api/v1/agents.py` |
| `create_agent_type` / `update_agent_type` | endpoints | Guardrail defaults/validation, binding contract, visibility invalidation; no implicit plan generation | `backend/app/api/v1/agents.py` |
| `_binding_conflict_detail` | function | Maps a binding unique-constraint `IntegrityError` to the 409 payload | `backend/app/api/v1/agents.py` |
| `get_workflow_generation_model` / `set_workflow_generation_model` | endpoints | Authoring-model selector (detailed in plans-optimization.md) | `backend/app/api/v1/agents.py` |
| `get_assistant_model_config` / `set_assistant_model_config` | endpoints | Assistant model selector (detailed in assistant.md) | `backend/app/api/v1/agents.py` |
| `get_optimizer_model_config` / `set_optimizer_model_config` | endpoints | Optimizer model selector (detailed in plans-optimization.md) | `backend/app/api/v1/agents.py` |

### Frontend

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentRoleListPage` / `AgentRoleDialog` / `AssignIdentitiesToRoleDialog` | components | Role surfaces | `frontend/src/pages/agents/AgentRoleListPage.tsx`, `frontend/src/components/agents/AgentRoleDialog.tsx`, `frontend/src/pages/agents/AssignIdentitiesToRoleDialog.tsx` |
| `AgentIdentityListPage` / `AgentIdentityDialog` / `AssignRolesToIdentityDialog` / `AgentOAuthCallbackPage` | components | Identity surfaces | `frontend/src/pages/agents/AgentIdentityListPage.tsx`, `frontend/src/components/agents/AgentIdentityDialog.tsx`, `frontend/src/pages/agents/AssignRolesToIdentityDialog.tsx`, `frontend/src/pages/agents/AgentOAuthCallbackPage.tsx` |
| `AgentTypeForm` / `AgentManagementPage` | components | Agent type form and table | `frontend/src/pages/agents/AgentTypeForm.tsx`, `frontend/src/pages/agents/AgentManagementPage.tsx` |
| `ModelConfigListPage` / `ModelConfigDialog` / `VendorModelGuardrailPanel` / `AddGuardrailForm` | components | Model configuration and guardrail UI | `frontend/src/pages/agents/ModelConfigListPage.tsx`, `frontend/src/components/agents/ModelConfigDialog.tsx`, `VendorModelGuardrailPanel.tsx`, `AddGuardrailForm.tsx` |
| `AgentManagementPanelPage` / `AgentPropertiesSection` / `AgentListSidebar` / `EquipmentSlots` / `EQUIPMENT_SLOT_DEFINITIONS` / `SharedDialogHost` / `PendingChangesTray` | components / constants | Panel composition surface | `frontend/src/pages/agents/AgentManagementPanelPage.tsx`, `frontend/src/components/agents/panel/` |
| `ResourcePickerDialog` / `SlotResourcePickerDialog` / `SLOT_PICKER_CONFIGS` / `getSlotPickerConfig` / `SlotPickerConfig` / `SlotDraftApi` / `dataTypeToInputSchema` | components / constants / types | Shared resource picker and per-slot bindings | `frontend/src/components/agents/panel/ResourcePickerDialog.tsx`, `SlotResourcePickerDialog.tsx`, `slotPickerConfigs.tsx`, `EquipmentSlots.tsx` |
| `useAgentDraftComposition` / `useUnsavedChangesDialog` / `usePagination` | hooks | Draft state, discard guard, pagination | `frontend/src/hooks/useAgentDraftComposition.ts`, `useUnsavedChangesDialog.tsx`, `usePagination.ts` |
| `PanelTopologyCanvas` / `buildPanelTopology` / `PanelTopologyNames` / `PanelTopologyLabels` / `PanelTopologyGraph` / `PanelTopologyPending` / `NO_PENDING` | component / functions / types | Canonical topology composer and labels | `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` |
| `capabilityColor` / `mcpGroupColor` | functions | Deterministic node/group colours | `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` |
| `TopologyDiagramRenderer` / `TopologyHubBar` / `PendingSpinner` / `TopologyNodeIcon` / `NODE_TYPE_ICONS` | components / interfaces / constants | Shared SVG renderer, hub bar, spinner, icons | `frontend/src/components/agents/TopologyDiagramRenderer.tsx`, `topologyNodeIcons.tsx` |
| `estimateTextWidth` / `fitTextToWidth` | functions | ViewBox-unit label fitting | `frontend/src/components/agents/topologyTextFit.ts` |
| `withCommunicationHub` / `COMMUNICATION_HUB_NODE_ID` / `TOPOLOGY_MAX_FONT_SCALE` | functions / constants | Hub node append and font-scale cap | `frontend/src/components/agents/topologyHub.ts`, `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` |
| `agentTypeToDraftComposition` | function | Loaded agent type → canvas draft adapter | `frontend/src/components/agents/agentTypeToDraftComposition.ts` |
| `SkillEditor` / `buildSkillToolEntries` / `groupToolEntries` / `SkillListPage` | component / functions / page | Single-surface binding editor and tool-count display | `frontend/src/components/agents/SkillEditor.tsx`, `frontend/src/pages/skills/SkillListPage.tsx` |
| `AgentDraftComposition` / `AgentEquipmentSlotId` / `EquipmentSlotDefinition` / `CreateAndAssignResult` / `PanelDialogRequest` / `AgentType` / `AgentRole` / `AgentIdentity` / `ModelConfig` | types | Frontend agent-editing contracts | `frontend/src/types/index.ts` |
| `useAgentTypes` / `useAgentType` / `useDeleteAgentType` / `useDataTypes` | hooks | Agent type and data-type queries | `frontend/src/hooks/useAgentTypes.ts`, `useDataTypes.ts` |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_permission_manager` | test module | Permission ∩ visibility, A2A targets, cache invalidation | `backend/tests/unit/test_permission_manager.py` |
| `test_agent_type_bindings_api` | integration test | Binding CRUD, role-access validation, cascade delete, name resolution | `backend/tests/api/test_agent_type_bindings_api.py` |
| `AgentRoleDialog.test` / `AgentTypeForm.test` / `AgentManagementPage.test` | frontend tests | Role editor, binding form, table/dialog | `frontend/src/__tests__/` |
| `AgentManagementPanelPage.test` / `PanelTopologyCanvas.test` / `TopologyDiagramRenderer.test` / `agentTypeToDraftComposition.test` | frontend tests | Panel, topology states, renderer, adapter | `frontend/src/__tests__/` |
| `agent-management-panel-topology.spec.ts` / `agent-type-preview-topology.spec.ts` / `agent-type-bindings*.spec.ts` | E2E tests | Panel/preview parity, contract slots, binding flows | `e2e/tests/` |
