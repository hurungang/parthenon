## Overview
This implementation delivers AI-assisted workflow authoring for both SOP and Skill creation flows by generating editable workflow text from author-provided descriptions and selected execution context. It also standardizes terminology from system instruction to workflow, adds preview actions that show the single formatted instruction file in edit and view experiences, and introduces a system configuration page for selecting the generation model. The design preserves service boundaries by keeping database access in Control Center and routing agent-driven generation through the existing governed runtime path.

## Task Checklist
### Phase 1 — Workflow UX and Terminology Alignment
- [x] 1.1 — Define workflow terminology contract across Skill and SOP create edit and view surfaces
- [x] 1.2 — Update Skill and SOP i18n labels and helper text from instructions or system instruction wording to workflow wording
- [x] 1.3 — Align Skill editor and SOP editor field labels placeholders and validation messages to workflow semantics
- [x] 1.4 — Introduce explicit edit and view dialog mode behavior for Skill and SOP authoring surfaces
- [x] 1.5 — Add a system configuration page for selecting the workflow generation model

### Phase 2 — Backend Workflow Generation and Preview Contracts
- [x] 2.1 — Define request and response schema contracts for Skill workflow generation and preview
- [x] 2.2 — Define request and response schema contracts for SOP workflow generation and preview
- [x] 2.3 — Add Skill API routes for workflow generation from selected tools plus description
- [x] 2.4 — Add SOP API routes for workflow generation from selected steps plus description
- [x] 2.5 — Add preview routes that return the final formatted instruction file for Skill and SOP dialogs
- [x] 2.6 — Add model configuration access for workflow generation
- [x] 2.7 — Enforce permission and sensitive-data guardrails for all new generation and preview endpoints

### Phase 3 — Frontend Authoring Integration
- [x] 3.1 — Extend Skill editor state and payload mapping to treat workflow as the primary authored field
- [x] 3.2 — Extend SOP editor state and payload mapping to treat workflow as the primary authored field
- [x] 3.3 — Add Generate with AI action in Skill edit and view dialogs using selected tools and description
- [x] 3.4 — Add Generate with AI action in SOP edit and view dialogs using selected steps and description
- [x] 3.5 — Add Preview Workflow action in Skill dialogs showing the single formatted instruction file
- [x] 3.6 — Add Preview Workflow action in SOP dialogs showing the single formatted instruction file
- [x] 3.7 — Ensure preview and generation always use unsaved current form edits and current selections without manual refresh
- [x] 3.8 — Add clear recoverable error handling for generation failures and missing input while preserving manual editing
- [x] 3.9 — Surface the configured generation model in system settings and preview headers

### Phase 4 — Verification and Change Completion
- [x] 4.1 — Update frontend unit tests for Skill editor and SOP editor workflow generation and preview behaviors
- [x] 4.2 — Add backend API tests for Skill and SOP generation preview success and failure paths
- [x] 4.3 — Validate top-priority architecture rules and confirm no boundary violations in final implementation
- [x] 4.4 — Update change artifacts and mark developer completion status in change metadata
- [x] 4.5 — Verify system configuration page coverage in tests

### Refinement — Default SOP Rename and Instruction-Aware SOP Routing ⚠️ NEEDS REWORK
- [x] P0 — AgentTypeForm: Primary SOP dropdown shown only when input_type equals none ⚠️ NEEDS REWORK — must show Default SOP for all input types; required only for none
- [x] P0 — AgentManagementPage: no-input validation uses primarySopRequired and clears primary_sop_id for non-none input types ⚠️ NEEDS REWORK — must use defaultSopRequired key and send primary_sop_id for all input types
- [x] P0 — PlanGenerationService: loads all role SOPs into plan context without system-instruction filtering ⚠️ NEEDS REWORK — must filter by SOP names referenced in system instruction with default SOP fallback
- [x] R1 — Rename primarySop i18n keys to defaultSop in en.json and update all references
- [x] R2 — Show Default SOP field for all agent input types in AgentTypeForm.tsx; required for none, optional otherwise; send primary_sop_id for all input types in AgentManagementPage.tsx
- [x] R3 — Update PlanGenerationService to filter SOPs by system instruction mentions; default SOP as fallback when none mentioned
- [x] R4 — Update get_agent_context to inject default SOP only when system instruction mentions no SOP names

## Phase 1 — Workflow UX and Terminology Alignment
### Task 1.1 — Define workflow terminology contract across Skill and SOP create edit and view surfaces
Create a UI terminology matrix that identifies every user-facing instance of instructions or system instruction language in Skill and SOP screens, then map each to workflow language while preserving backend field compatibility.

**Done when:** A reviewed list of affected screens and strings exists, and each entry has an approved replacement that uses workflow terminology consistently.

### Task 1.2 — Update Skill and SOP i18n labels and helper text from instructions or system instruction wording to workflow wording
Update translation keys and values used by Skill and SOP pages so labels, helper text, button text, and empty states use workflow wording, while keeping localization structure intact.

**Done when:** All Skill and SOP authoring/view labels render workflow wording via i18n keys and no hardcoded replacement text is introduced.

### Task 1.3 — Align Skill editor and SOP editor field labels placeholders and validation messages to workflow semantics
Update editor field captions, helper hints, and validation messages so users understand they are authoring workflow content and not a generic instruction blob.

**Done when:** Both editors present workflow-first labels and validation copy across create and edit paths with no remaining instruction-only wording in those surfaces.

### Task 1.4 — Introduce explicit edit and view dialog mode behavior for Skill and SOP authoring surfaces
Define and implement mode handling that supports edit and view contexts in the same authoring dialog components, including read-only behavior and action visibility for preview and generation.

**Done when:** Skill and SOP authoring surfaces can be opened in explicit edit or view mode with the correct field mutability and action buttons for each mode.

### Task 1.5 — Add a system configuration page for selecting the workflow generation model
Create a system configuration surface that lets administrators choose the AI model used for Skill and SOP workflow generation and reflects the chosen model in preview metadata.

**Done when:** Administrators can view and change the selected workflow generation model from the existing model config module and the chosen model is available to the preview experience.

## Phase 2 — Backend Workflow Generation and Preview Contracts
### Task 2.1 — Define request and response schema contracts for Skill workflow generation and preview
Add typed schema contracts for Skill workflow generation and preview payloads that include description, selected tool identifiers, and composed metadata sections for preview responses.

**Done when:** Schema models exist for Skill generation and preview endpoints, validate required fields, and support structured response metadata for tool context.

### Task 2.2 — Define request and response schema contracts for SOP workflow generation and preview
Add typed schema contracts for SOP workflow generation and preview payloads that include description, ordered step context, delegation references, and composed preview metadata.

**Done when:** Schema models exist for SOP generation and preview endpoints, validate required fields, and support structured response metadata for delegation context.

### Task 2.3 — Add Skill API routes for workflow generation from selected tools plus description
Implement Skill generation API routes that accept current unsaved editor context, invoke governed generation flow, and return editable workflow text for client-side insertion.

**Done when:** A Skill generation route returns deterministic structured output for valid requests, returns actionable validation errors for missing required inputs, and is protected by existing permission checks.

### Task 2.4 — Add SOP API routes for workflow generation from selected steps plus description
Implement SOP generation API routes that accept ordered step context and description, invoke governed generation flow, and return editable workflow text for client-side insertion.

**Done when:** An SOP generation route returns structured workflow text for valid requests, returns actionable validation errors for missing required inputs, and is protected by existing permission checks.

### Task 2.5 — Add preview routes that return the final formatted instruction file for Skill and SOP dialogs
Implement preview API routes for Skill and SOP that combine current workflow text with the context needed to render the single formatted instruction file shown to reviewers.

**Done when:** Preview routes return the single formatted instruction file expected by UI preview dialogs for both authoring types.

### Task 2.6 — Add model configuration access for workflow generation
Define how the selected generation model is read by the workflow generation flow so the same configured model is used by Skill and SOP draft creation and preview rendering.

**Done when:** Generation requests resolve the configured model consistently from existing model configs, preview headers display that model, and no fallback model is used when configuration is missing.

### Task 2.7 — Enforce permission and sensitive-data guardrails for all new generation and preview endpoints
Ensure all generation and preview routes enforce authorization and do not expose identity tokens, database credentials, or direct database access from agent-execution paths.

**Done when:** New routes use existing permission gates, pass security review checks against top-priority rules, and expose only sanitized context fields required by preview UX.

## Phase 3 — Frontend Authoring Integration
### Task 3.1 — Extend Skill editor state and payload mapping to treat workflow as the primary authored field
Refactor Skill editor local state and payload mapping so the user-authored text is represented as workflow in UI behavior while remaining compatible with current API persistence fields.

**Done when:** Skill editor form and save flow consistently bind the authored workflow text and preserve backward-compatible backend payload behavior.

### Task 3.2 — Extend SOP editor state and payload mapping to treat workflow as the primary authored field
Refactor SOP editor local state and payload mapping so workflow is the first-class authored content and remains consistent across step editing and save operations.

**Done when:** SOP editor save flow persists authored workflow content correctly and uses workflow naming in all user-facing controls.

### Task 3.3 — Add Generate with AI action in Skill edit and view dialogs using selected tools and description
Add a Skill dialog action that calls the new Skill generation API with current description and selected tools and writes returned workflow text back into the editor state.

**Done when:** Skill generate action works in edit and view contexts, updates workflow text on success, and preserves existing text when generation fails.

### Task 3.4 — Add Generate with AI action in SOP edit and view dialogs using selected steps and description
Add an SOP dialog action that calls the new SOP generation API with current description and selected ordered steps and writes returned workflow text back into editor state.

**Done when:** SOP generate action works in edit and view contexts, updates workflow text on success, and preserves existing text when generation fails.

### Task 3.5 — Add Preview Workflow action in Skill dialogs showing the single formatted instruction file
Add a Skill preview dialog action that renders the single formatted instruction file derived from selected tools and preview API response.

**Done when:** Skill preview always reflects unsaved current form state and displays the single formatted instruction file.

### Task 3.6 — Add Preview Workflow action in SOP dialogs showing the single formatted instruction file
Add an SOP preview dialog action that renders the single formatted instruction file derived from current steps and preview API response.

**Done when:** SOP preview always reflects unsaved current form state and displays the single formatted instruction file.

### Task 3.7 — Ensure preview and generation always use unsaved current form edits and current selections without manual refresh
Wire generation and preview actions to consume live form state, selected tools, selected steps, and current descriptions so users see immediate outcomes from unsaved edits.

**Done when:** Both actions use current in-memory form state and no save or reload is required for preview parity.

### Task 3.8 — Add clear recoverable error handling for generation failures and missing input while preserving manual editing
Apply dialog error handling standards to generation and preview actions so users receive actionable feedback and can continue editing manually after any failure.

**Done when:** Missing-input, missing-model, and backend-failure scenarios display clear in-dialog errors, and users can continue manual workflow editing without data loss.

### Task 3.9 — Surface the configured generation model in system settings and preview headers
Display the selected AI model on the system configuration surface and in preview headers so reviewers know which configuration produced the draft.

**Done when:** The system configuration page and preview header both show the selected workflow generation model consistently.

## Phase 4 — Verification and Change Completion
### Task 4.1 — Update frontend unit tests for Skill editor and SOP editor workflow generation and preview behaviors
Extend existing editor tests to verify workflow label rendering, generate and preview actions, live-state usage, and error fallbacks for missing input and failed calls.

**Done when:** Frontend tests cover success and failure scenarios for both editors and pass with workflow terminology assertions.

### Task 4.2 — Add backend API tests for Skill and SOP generation preview success and failure paths
Create backend route tests for generation and preview endpoints covering valid payloads, validation failures, and authorization checks.

**Done when:** Backend tests validate contract shape and error handling for all new routes and pass in CI-aligned local test runs.

### Task 4.3 — Validate top-priority architecture rules and confirm no boundary violations in final implementation
Perform final architecture compliance review against top-priority rules with explicit checks for runtime isolation, control-center DB ownership, and sensitive-data protection.

**Done when:** A final compliance check confirms no new endpoint or UI flow violates documented top-priority architecture constraints.

### Task 4.4 — Update change artifacts and mark developer completion status in change metadata
Update change documents and metadata state for developer completion after implementation and tests are verified.

**Done when:** Change artifacts reflect implemented scope accurately and developer completion status is updated in the change metadata.

### Task 4.5 — Verify system configuration page coverage in tests
Add or update tests that validate the generation model configuration page, its effect on workflow generation, and its presence in preview headers.

**Done when:** Tests cover model selection, model persistence in the UI state, and model display in preview outputs.

## Completion Checklist
- [x] All Phase 1-4 Task Checklist items are completed and verified against done conditions
- [x] Skill and SOP dialogs support workflow generation and preview in edit and view contexts
- [x] Workflow terminology replaces system instruction wording in all targeted Skill and SOP UI text
- [x] Generation and preview APIs are permission-protected and return actionable validation errors
- [x] Top-priority architecture rules are satisfied with no sensitive-data exposure regressions
- [x] Frontend and backend test coverage is updated and passing for the new behavior
- [x] Refinement tasks R1-R4 implemented: Default SOP rename, all-input-type support, instruction-aware SOP filtering in PlanGenerationService and get_agent_context

