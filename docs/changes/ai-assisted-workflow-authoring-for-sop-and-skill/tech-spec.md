## Technical Overview
This change introduces AI-assisted workflow authoring for Skill and SOP flows by generating editable workflow text from the author’s business description plus selected execution context. Skill generation uses selected MCP tools and SOP generation uses ordered SOP steps, including delegation steps where present. The implementation also adds a system configuration page for choosing the AI model used for generation and preview. The implementation keeps the current service boundary model: frontend calls authenticated backend APIs, Control Center remains the only database-facing service, and any agent-like generation execution is routed through governed runtime pathways without exposing sensitive credentials.

## Component Breakdown
- Skill authoring surface updates in SkillListPage and SkillEditor to add workflow-first labels, generate action, and preview action for create, edit, and view contexts.
- SOP authoring surface updates in SopListPage and SopEditor to add workflow-first labels, generate action, and preview action for create, edit, and view contexts.
- System configuration surface updates in ModelConfigListPage and ModelConfigDialog to select the workflow generation model and show it in preview headers.
- Existing Skill tool-context composition utilities in SkillEditor are reused to assemble the single formatted instruction file shown in preview.
- Skill and SOP API routers are extended with generation and preview endpoints while preserving existing CRUD contracts.
- The existing agents model-configuration API is reused as the source of truth for the selected generation model.
- Skill and SOP schema modules are extended with typed request and response contracts for generation and preview operations.
- Existing permission gating with require_permission and RT_SKILL remains the enforcement path for new endpoints.
- Translation resources in en.json are updated so all user-facing wording shifts from instruction-oriented language to workflow-oriented language in targeted surfaces.
- AgentTypeForm: Default SOP dropdown (renamed from Primary SOP) is now shown for all agent input types, not only no-input; the field is required only when input_type equals none and optional for all other input types; the sops query is no longer gated on input_type; the input_type change handler no longer clears primary_sop_id when switching away from none.
- PlanGenerationService (_resolve_graph): after loading all role SOPs into sop_data_list, applies a system-instruction-aware filtering step; if the agent system instruction text contains one or more SOP names (case-insensitive substring match), the list is filtered to only those referenced SOPs; if no SOP names are found in the instruction and the agent has a primary_sop_id, the list is filtered to only that default SOP; if neither condition applies, all role SOPs are kept unchanged.
- get_agent_context (RuntimeInstructionBuilder in agent_data.py): after building sops_summary from role SOPs, checks whether any role SOP name appears in the agent system instruction (case-insensitive); if at least one SOP name is found, default SOP content is not injected because the system instruction already references specific SOPs; if no SOP name is found, the default SOP content is appended as a fallback using the existing _build_sop_content helper.

## API Changes
- Add Skill workflow generation endpoint in the Skill router namespace.
- Add Skill workflow preview endpoint in the Skill router namespace.
- Add SOP workflow generation endpoint in the SOP router namespace.
- Add SOP workflow preview endpoint in the SOP router namespace.
- Reuse the existing agents model configuration routes for selecting the generation model used by workflow generation.
- Add workflow generation model read or update endpoints under the existing model-config namespace so administrators can configure one selected generation model.
- Model list for system configuration must be loaded from the existing model config module/routes, not hardcoded in authoring surfaces.
- Keep existing Skill CRUD and SOP CRUD routes, with backward-compatible persistence fields while treating workflow as the primary user-facing term.
- For Skill preview responses, include the final formatted instruction file content plus tool metadata used to compose that file.
- For SOP preview responses, include the final formatted instruction file content plus step metadata used to compose that file.
- For preview responses, include the configured model identifier so the preview header can display which model produced the draft.
- If no model is configured, generation and preview endpoints return a validation error and do not apply fallback model selection.
- New endpoints must use the same permission model already used by Skill and SOP routes.
- New endpoints must not return identity tokens, database credentials, or direct database internals.
- Agent type CRUD: primary_sop_id is now sent in the request body for all input types (not gated on input_type equals none); frontend validation still enforces that primary_sop_id is required when input_type is none; for other input types the field is optional and the value is preserved regardless of input_type change.

## State Management
- SkillEditor local form state remains the source of truth for unsaved workflow text, selected tools, and description before any save action.
- SopEditor local form state remains the source of truth for unsaved workflow text, ordered steps, and description before any save action.
- Generate and Preview actions consume current in-memory form state so output reflects unsaved edits immediately.
- System configuration state remains separate from authoring form state but feeds generation and preview model selection.
- Authoring actions must block with an explicit error when system configuration has no selected model.
- React Query cache keys for skills and sops remain the post-save refresh mechanism, while preview and generation requests are dialog-scoped actions.
- Existing dialog error pattern with PermissionDeniedAlert is reused so API failures remain visible and recoverable in authoring dialogs.

## Data Access Patterns
- Frontend obtains and persists Skill and SOP data only via apiClient calls to backend REST endpoints.
- Frontend obtains and persists model configuration data through the existing agents model-config pages and API routes.
- Frontend never connects directly to the database.
- Control Center APIs in skills.py and sops.py remain the persistence boundary for Skill and SOP records.
- Model configuration UI uses the existing agents model-config surface as the system configuration entry point.
- Model options for generation are sourced from existing model configurations only; no local fallback list is permitted in production flows.
- Route-level access control remains enforced through require_permission checks on RT_SKILL actions.
- Preview context is composed from selected UI state and governed backend data; sensitive values are excluded from response payloads.
- Workflow generation and preview behavior must maintain the existing architecture rule that agent runtime cannot own direct database access.

## Code Reference Map
| Symbol | Type | Description | File |
|---|---|---|---|
| SkillListPage | React component | Skill list and entry point for opening authoring dialog states | frontend/src/pages/skills/SkillListPage.tsx |
| SkillEditor | React component | Skill create or edit dialog with instructions field and tool selection | frontend/src/pages/skills/SkillEditor.tsx |
| ModelConfigListPage | React component | System configuration page for selecting the workflow generation model | frontend/src/pages/agents/ModelConfigListPage.tsx |
| ModelConfigDialog | React component | Dialog for editing the selected workflow generation model | frontend/src/pages/agents/ModelConfigDialog.tsx |
| extractGeneratedToolSection | function | Extracts generated tool context block for Skill display | frontend/src/pages/skills/SkillEditor.tsx |
| buildGeneratedToolSectionFromSelection | function | Builds live Skill tool metadata block from selected tools | frontend/src/pages/skills/SkillEditor.tsx |
| SopListPage | React component | SOP list and entry point for opening SOP editor state | frontend/src/pages/skills/SopListPage.tsx |
| SopEditor | React component | SOP create or edit side panel with steps and instructions field | frontend/src/pages/skills/SopEditor.tsx |
| useAllTools | React hook | Loads MCP tools used by Skill authoring context | frontend/src/hooks/useMcpServers.ts |
| useMcpServers | React hook | Loads MCP server metadata used for tool grouping | frontend/src/hooks/useMcpServers.ts |
| useSkillRoles | React hook | Loads role assignments for a Skill | frontend/src/hooks/useSkills.ts |
| useSopRoles | React hook | Loads role assignments for a SOP | frontend/src/hooks/useSops.ts |
| apiClient | HTTP client module | Shared frontend API client used by Skill and SOP pages | frontend/src/api/apiClient.ts |
| PermissionDeniedAlert | React component | Standard dialog-visible error feedback for API failures | frontend/src/components/permissions/PermissionDeniedAlert.tsx |
| AppRouter | React router module | Routes to the system configuration model page and authoring pages | frontend/src/app/AppRouter.tsx |
| Skill | TypeScript interface | Skill API shape used by Skill authoring pages | frontend/src/types/index.ts |
| Sop | TypeScript interface | SOP summary API shape used by SOP list page | frontend/src/types/index.ts |
| SopDetail | TypeScript interface | SOP detail shape including ordered steps | frontend/src/types/index.ts |
| SopStep | TypeScript interface | SOP step shape including skill invocation and delegation fields | frontend/src/types/index.ts |
| SkillRouter | FastAPI router | Skill CRUD and future workflow generation or preview routes | backend/app/api/v1/skills.py |
| assemble_tool_section | function | Composes Skill tool context markdown from tool records | backend/app/api/v1/skills.py |
| _build_skill_read | function | Produces Skill read responses including tool-context field | backend/app/api/v1/skills.py |
| _build_skill_detail_read | function | Produces Skill detail response including editable instructions | backend/app/api/v1/skills.py |
| SopRouter | FastAPI router | SOP CRUD and future workflow generation or preview routes | backend/app/api/v1/sops.py |
| replace_sop_steps | FastAPI route function | Replaces ordered SOP step definitions and validates skills | backend/app/api/v1/sops.py |
| agents API model-config routes | FastAPI router | Existing model configuration routes reused as system configuration source of truth | backend/app/api/v1/agents.py |
| ModelConfigService | service class | Persists and lists model configurations used by workflow generation | backend/app/services/agents/model_config_service.py |
| SkillCreate | Pydantic schema | Skill creation payload schema | backend/app/schemas/skills.py |
| SkillUpdate | Pydantic schema | Skill update payload schema | backend/app/schemas/skills.py |
| SkillDetailRead | Pydantic schema | Skill detail response schema | backend/app/schemas/skills.py |
| SopCreate | Pydantic schema | SOP creation payload schema | backend/app/schemas/skills.py |
| SopUpdate | Pydantic schema | SOP update payload schema | backend/app/schemas/skills.py |
| SopDetailRead | Pydantic schema | SOP detail response schema including steps | backend/app/schemas/skills.py |
| require_permission | dependency function | Route-level authorization enforcement for Skill and SOP APIs | backend/app/api/deps.py |
| RT_SKILL | resource constant | Authorization resource type used by Skill and SOP routers | backend/app/core/resource_types.py |
| ws_router | FastAPI router | Communication Hub websocket entry where runtime delegation pattern is established | backend/app/api/ws/chat.py |
| _delegate_conversation_turn_to_agent_runtime | function | Existing communication-hub to agent-runtime delegation pathway reference | backend/app/api/ws/chat.py |
| en.json skills and sops keys | localization resource | User-facing text keys for Skill and SOP terminology updates | frontend/src/i18n/locales/en.json |
| SkillEditor.handleGenerateWorkflow | function | Calls Skill workflow generation API using current unsaved description and selected tools | frontend/src/pages/skills/SkillEditor.tsx |
| SkillEditor.handlePreviewWorkflow | function | Calls Skill workflow preview API and renders single instruction-file preview with model header | frontend/src/pages/skills/SkillEditor.tsx |
| SopEditor.handleGenerateWorkflow | function | Calls SOP workflow generation API using current unsaved description and ordered steps | frontend/src/pages/skills/SopEditor.tsx |
| SopEditor.handlePreviewWorkflow | function | Calls SOP workflow preview API and renders single instruction-file preview with model header | frontend/src/pages/skills/SopEditor.tsx |
| ModelConfigListPage.handleSaveWorkflowModel | function | Persists the effective workflow generation model selection and avoids unintended clearing when no new selection is made | frontend/src/pages/agents/ModelConfigListPage.tsx |
| WorkflowGenerationModelConfig | TypeScript interface | Frontend contract for selected workflow generation model and option list | frontend/src/types/index.ts |
| SkillWorkflowGenerateRequest | Pydantic schema | Request contract for Skill workflow generation endpoint | backend/app/schemas/skills.py |
| SkillWorkflowPreviewResponse | Pydantic schema | Response contract for Skill workflow preview endpoint | backend/app/schemas/skills.py |
| SopWorkflowGenerateRequest | Pydantic schema | Request contract for SOP workflow generation endpoint | backend/app/schemas/skills.py |
| SopWorkflowPreviewResponse | Pydantic schema | Response contract for SOP workflow preview endpoint | backend/app/schemas/skills.py |
| generate_skill_workflow | FastAPI route function | Generates Skill workflow text from description and selected tools | backend/app/api/v1/skills.py |
| preview_skill_workflow | FastAPI route function | Returns formatted single-file Skill workflow preview plus configured model metadata | backend/app/api/v1/skills.py |
| generate_sop_workflow | FastAPI route function | Generates SOP workflow text from description and ordered steps | backend/app/api/v1/sops.py |
| preview_sop_workflow | FastAPI route function | Returns formatted single-file SOP workflow preview plus configured model metadata | backend/app/api/v1/sops.py |
| get_workflow_generation_model | FastAPI route function | Reads selected workflow generation model and available options from existing model configs | backend/app/api/v1/agents.py |
| set_workflow_generation_model | FastAPI route function | Updates selected workflow generation model with validation against enabled model list | backend/app/api/v1/agents.py |
| WorkflowGenerationModelConfigRead | Pydantic schema | API response contract for workflow generation model system configuration | backend/app/schemas/agents.py |
| workflow_generation_settings | service module | Persists and resolves selected workflow generation model in config/identity.yaml-backed settings | backend/app/services/agents/workflow_generation_settings.py |
| workflow_authoring_service | service module | Generates workflow text via model binding and composes single formatted instruction-file previews | backend/app/services/agents/workflow_authoring_service.py |
| ModelConfigListPage.workflow-generation tests | Vitest test module | Verifies workflow model read and save behavior including preserving existing selected model on save | frontend/src/__tests__/ModelConfigListPage.workflow-generation.test.tsx |
| SkillEditor.workflow-generation-preview tests | Vitest test module | Verifies generate and preview API integration plus standardized dialog-visible error handling | frontend/src/__tests__/SkillEditor.workflow-generation-preview.test.tsx |
| SopEditor.workflow-generation-preview tests | Vitest test module | Verifies SOP generate and preview API integration plus standardized dialog-visible error handling | frontend/src/__tests__/SopEditor.workflow-generation-preview.test.tsx |
| test_skills_workflow_generation_preview | Pytest module | Verifies skill workflow generation or preview routes enforce configured model requirement and single-file preview contract | backend/tests/api/v1/test_skills_workflow_generation_preview.py |
| test_sops_workflow_generation_preview | Pytest module | Verifies SOP workflow generation or preview routes enforce configured model requirement and single-file preview contract | backend/tests/api/v1/test_sops_workflow_generation_preview.py |
| AgentTypeForm | React component | Default SOP dropdown shown for all input types; required only when input_type equals none; sops query no longer gated on input_type | frontend/src/pages/agents/AgentTypeForm.tsx |
| AgentManagementPage | React component | Validation uses defaultSopRequired i18n key; primary_sop_id sent for all input types (not gated on none) | frontend/src/pages/agents/AgentManagementPage.tsx |
| PlanGenerationService._resolve_graph | method | Filters sop_data_list by SOP names found in system instruction; falls back to default SOP when no SOP names referenced; keeps all role SOPs when no default SOP set | backend/app/services/agents/plan_generation_service.py |
| get_agent_context | FastAPI route function | Applies system-instruction-aware default SOP fallback: skips sop_content injection when any role SOP name appears in system instruction; appends default SOP content when no SOP name referenced | backend/app/api/v1/internal/agent_data.py |
