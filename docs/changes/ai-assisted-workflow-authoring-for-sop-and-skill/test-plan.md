# Test Plan: AI-Assisted Workflow Authoring for SOP and Skill

Created by: Tester Agent
Date: 2026-05-25
Status: Planned

## 1) Test Strategy

This plan validates AI-assisted workflow authoring for Skill and SOP create, edit, and view experiences, with a focus on UI correctness, preview fidelity, and secure backend context assembly.

Strategy principles:
- Validate terminology migration from system instruction to workflow across Skill and SOP authoring and read-only surfaces.
- Validate full authoring lifecycle outcomes for workflow content: generate, edit, preview, save, reopen, and view.
- Validate system configuration behavior for selecting the model used by workflow generation.
- Validate preview freshness: preview must reflect current in-memory form state (latest edits and selections) without manual page refresh.
- Validate preview shape: preview must show the single formatted instruction file the agent will load.
- Validate failure-resilient authoring: generation and preview errors must be actionable and must not block manual workflow editing.
- Validate architecture boundaries from docs/config.yaml top_priority_rules:
  - Agent runtime execution stays isolated to runtime services.
  - Database access remains Control Center only.
  - No sensitive data exposure (identity tokens, database credentials, internal secrets) in generation or preview payloads.

Test layers aligned to docs/config.yaml source.tests:
- Backend tests in backend/tests/ for API contracts, permission enforcement, secure context assembly, and non-leakage assertions.
- Frontend tests in frontend/src/__tests__/ for label changes, generation and preview interactions, dialog rendering in create/edit/view, and error handling.
- E2E tests in e2e/tests/ for complete user flows across Skill and SOP authoring with real UI behavior.
- Supporting tests in mcp-demo-app/tests/ only for MCP-side metadata assumptions used by workflow context composition.

Execution guidance:
- Run backend, frontend, and e2e layers for this change scope before sign-off.
- Include at least one real-backend e2e path (not only mocked routes) for generation and preview to verify true API behavior and secure payload shape.

## 2) Coverage Areas

0. Default SOP rename and availability coverage
- Default SOP label (renamed from Primary SOP) appears in agent form for all input types (none, typed, conversation).
- Default SOP field is required for no-input agents and optional for all other input types.
- Terminology in all create/edit/view surfaces uses Default SOP consistently with no legacy Primary SOP wording.

0a. PlanGenerationService SOP filtering coverage
- `_resolve_graph` filters `sop_data_list` to contain only the SOP whose name is mentioned in system instruction.
- `_resolve_graph` uses the configured default SOP (primary_sop_id) as fallback when system instruction mentions no SOPs.
- `_resolve_graph` keeps all role SOPs when no system instruction and no default SOP are configured.

0b. Runtime SOP injection coverage
- At runtime, `get_agent_context` does NOT inject default SOP content when system instruction already references a SOP name.
- At runtime, `get_agent_context` DOES inject default SOP content when system instruction references no SOP names.

1. Workflow terminology rename coverage
- Skill create/edit/view surfaces show workflow label text and no legacy system instruction wording.
- SOP create/edit/view surfaces show workflow label text and no legacy system instruction wording.
- Any related helper text, section titles, and preview titles align to workflow terminology and i18n keys.

2. Skill workflow generation coverage
- Generation request uses current Skill description plus selected tools context.
- Generated workflow text is inserted into editable workflow field.
- User can modify generated workflow before save.
- Missing required inputs and generation failures show actionable dialog-visible error states.

3. SOP workflow generation coverage
- Generation request uses current SOP description plus ordered steps context, including delegation context.
- Generated workflow text is inserted into editable workflow field.
- User can modify generated workflow before save.
- Missing required inputs and generation failures show actionable dialog-visible error states.

4. Skill preview rendering coverage
- Preview action in Skill create/edit/view shows the single formatted instruction file.
- Preview reflects latest unsaved edits and current tool selection state.
- Preview remains readable and stable for long workflow text and multi-tool content.

5. SOP preview rendering coverage
- Preview action in SOP create/edit/view shows the single formatted instruction file.
- Preview reflects latest unsaved edits and current ordered steps.
- Preview remains readable and stable for large step sets and mixed delegation patterns.

6. Integration/API security and context assembly coverage
- Skill generation/preview endpoints assemble context from governed data and current request state only.
- SOP generation/preview endpoints assemble context from governed data and current request state only.
- System configuration page persists and exposes only the selected model, not sensitive credentials or internal prompts.
- Responses exclude sensitive fields: identity tokens, database credentials, internal secret material, and direct database internals.
- Permission checks remain enforced for generation and preview operations using existing authorization model.

7. System configuration coverage
- Administrators can open the configuration page and choose the model used for workflow generation.
- The selected model is reflected in Skill and SOP preview headers.
- The selected model persists in the UI state and survives dialog reopen or page refresh based on the application’s existing config storage pattern.
- Model options are loaded from the existing model config module (not hardcoded in the workflow authoring dialogs).

## 3) Critical Scenarios (WHEN/THEN format)

0. Default SOP label for no-input agents
- WHEN a user opens the agent create/edit form with no-input type.
- THEN the Default SOP field is visible and marked required.

0a. Default SOP label for typed-input agents
- WHEN a user opens the agent create/edit form with typed or conversation input type.
- THEN the Default SOP dropdown is visible and optional (not required).

0b. PlanGenerationService filters SOPs by system instruction
- WHEN system instruction mentions a SOP name (e.g. "query-supabase").
- THEN `_resolve_graph` returns sop_data_list containing only that SOP.

0c. PlanGenerationService default SOP fallback
- WHEN system instruction mentions no SOP names and agent has primary_sop_id set.
- THEN `_resolve_graph` returns sop_data_list containing only the default SOP.

0d. PlanGenerationService keeps all SOPs when no instruction and no default
- WHEN system instruction is empty and primary_sop_id is None.
- THEN `_resolve_graph` returns sop_data_list with all role SOPs.

0e. Runtime: default SOP skipped when instruction references SOP name
- WHEN system instruction contains a SOP name from the agent role's SOP list.
- THEN `get_agent_context` returns `sop_content = None` (no injection).

0f. Runtime: default SOP injected when instruction references no SOP names
- WHEN system instruction contains no SOP names and agent has primary_sop_id.
- THEN `get_agent_context` returns `sop_content` with the default SOP content.

1. Workflow label rename in Skill dialogs
- WHEN a user opens Skill create, edit, or view dialogs.
- THEN workflow terminology is shown consistently and legacy system instruction wording is absent.

2. Workflow label rename in SOP dialogs
- WHEN a user opens SOP create, edit, or view dialogs.
- THEN workflow terminology is shown consistently and legacy system instruction wording is absent.

3. Skill workflow generation happy path
- WHEN a user provides Skill description and selects tools, then triggers generation.
- THEN generated workflow text appears in the editable workflow field and can be revised before save.

4. SOP workflow generation happy path
- WHEN a user provides SOP description and ordered steps, then triggers generation.
- THEN generated workflow text appears in the editable workflow field and can be revised before save.

5. Skill preview freshness
- WHEN a user edits workflow text or tool selections and immediately opens preview.
- THEN preview shows the latest unsaved state without manual refresh.

6. SOP preview freshness with delegation
- WHEN a user edits workflow text or SOP steps including delegation steps and immediately opens preview.
- THEN preview shows the latest unsaved state including delegation context without manual refresh.

7. Skill generation missing input
- WHEN required Skill generation input is missing.
- THEN the user sees a clear actionable message and can continue manual workflow editing.

8. SOP generation failure
- WHEN SOP generation API fails.
- THEN the user sees a clear actionable message, dialog remains recoverable, and manual workflow editing remains available.

9. Secure context assembly for Skill preview
- WHEN Skill preview API returns the rendered instruction file.
- THEN the file includes only allowed tool context used for composition, shows the configured model, and excludes tokens, credentials, and secret/internal database fields.

10. Secure context assembly for SOP preview
- WHEN SOP preview API returns the rendered instruction file.
- THEN the file includes only allowed step/delegation context used for composition, shows the configured model, and excludes tokens, credentials, and secret/internal database fields.

11. System configuration model selection
- WHEN an administrator selects a different generation model in the system configuration page.
- THEN subsequent generation and preview operations use the selected model and the preview header reflects the change.

13. Missing model configuration behavior
- WHEN no generation model is configured.
- THEN generate and preview actions show a user-visible error and do not use a fallback model.

12. Authorization boundary enforcement
- WHEN a caller lacks permission for Skill or SOP workflow generation/preview.
- THEN API returns authorization error and no sensitive context is leaked in error payloads.

## 4) Edge Cases & Risks

- Empty or whitespace-only workflow description entered before generation request.
- Extremely long workflow drafts causing truncated preview or UI lag.
- Large tool selections for Skill causing oversized context assembly.
- Large SOP step lists with multiple delegation hops causing preview rendering pressure.
- Rapid consecutive generate clicks causing stale or out-of-order field updates.
- Edit-view state drift where preview accidentally uses saved state instead of latest in-memory edits.
- Translation key drift where some surfaces still show legacy wording.
- API error payloads accidentally exposing internal identifiers or stack details.
- Unauthorized user attempts for generation/preview returning inconsistent status codes or messages.
- Cross-service contract drift between frontend request shape and backend schema models.

## 5) Acceptance Criteria Checklist

- [ ] Default SOP label (not Primary SOP) appears in agent form for all input types.
- [ ] Default SOP is required for no-input agents and optional for all other input types.
- [ ] PlanGenerationService filters plan context SOPs to those named in system instruction.
- [ ] PlanGenerationService uses default SOP as fallback when instruction names no SOPs.
- [ ] Runtime: default SOP not injected when instruction already references a SOP name.
- [ ] Runtime: default SOP content injected when instruction references no SOP names.
- [ ] Skill and SOP create/edit/view experiences use workflow terminology consistently.
- [ ] AI generation is available for Skill using description plus selected tools.
- [ ] AI generation is available for SOP using description plus ordered steps.
- [ ] Generated workflow text is inserted into editable workflow field for Skill and SOP.
- [ ] Users can manually edit generated workflow before save.
- [ ] Skill preview action renders the single formatted instruction file.
- [ ] SOP preview action renders the single formatted instruction file.
- [ ] System configuration page lets administrators choose the workflow generation model.
- [ ] Preview headers show the configured model used for generation.
- [ ] Model choices for generation are loaded from the existing model config module.
- [ ] No fallback model is applied when model configuration is missing.
- [ ] Preview always reflects latest unsaved edits and selections without manual refresh.
- [ ] Missing input and generation failures show clear actionable user messages.
- [ ] Generation/preview API responses do not expose tokens, credentials, or database internals.
- [ ] Existing permission model is enforced on generation/preview endpoints.
- [ ] Architecture boundaries remain compliant: runtime isolation, Control Center database ownership, and no sensitive data exposure.
- [ ] Backend, frontend, and e2e tests for this scope pass.

## 6) Test File References

Backend tests (backend/tests/):
- backend/tests/api/v1/test_skills_api.py
- backend/tests/api/v1/test_sops_api.py
- backend/tests/unit/test_skill_sop.py
- backend/tests/unit/test_skill_tool_section_builder.py
- backend/tests/integration/test_enhance_mcp_hub_skills_sops_db.py
- backend/tests/integration/test_skill_system_tools.py
- backend/tests/api/v1/test_skills_workflow_generation_preview.py
- backend/tests/api/v1/test_sops_workflow_generation_preview.py
- backend/tests/api/test_model_configs_api.py
- backend/tests/unit/services/test_plan_generation_service.py
- backend/tests/unit/test_agent_data_sop_injection.py

Frontend tests (frontend/src/__tests__/):
- frontend/src/__tests__/SkillEditor.test.tsx
- frontend/src/__tests__/SkillEditor.minimal.test.tsx
- frontend/src/__tests__/SkillEditor.generatedToolReference.test.ts
- frontend/src/__tests__/SopEditor.test.tsx
- frontend/src/__tests__/SopEditor.simple.test.tsx
- frontend/src/__tests__/SkillEditor.workflow-generation-preview.test.tsx
- frontend/src/__tests__/SopEditor.workflow-generation-preview.test.tsx
- frontend/src/__tests__/ModelConfigListPage.workflow-generation.test.tsx
- frontend/src/__tests__/WorkflowTerminology.rename-coverage.test.tsx
- frontend/src/__tests__/AgentManagementPage.test.tsx

E2E tests (e2e/tests/):
- e2e/tests/skills-sops.spec.ts
- e2e/tests/skills-system-tools.spec.ts
- e2e/tests/skills-workflow-generation-preview.spec.ts
- e2e/tests/sops-workflow-generation-preview.spec.ts

MCP demo app supporting tests (mcp-demo-app/tests/):
- mcp-demo-app/tests/integration/test_agent_flow.py
- mcp-demo-app/tests/unit/test_tools.py
