# Spec Change: AI-Assisted Workflow Authoring for SOP and Skill

## Affected Spec Areas
- openspec/specs/product/skills-authoring
- openspec/specs/product/sop-authoring
- openspec/specs/product/agent-governance-and-instruction-visibility
- docs/master/product/features/skills.md
- docs/master/product/features/sops.md
- docs/master/product/features/agent-governance.md

## New Capabilities
- AI-assisted workflow generation for SOP authoring using selected steps plus SOP description.
- AI-assisted workflow generation for Skill authoring using selected tools plus Skill description.
- System configuration page for choosing the AI model used for workflow generation.
- Skill workflow preview that shows the final formatted instruction file the agent will load.
- SOP workflow preview that shows the final formatted instruction file the agent will load.
- Preview header that shows which configured model was used for generation.
- Default SOP configuration that is available across all agent input types.
- Instruction-aware SOP selection for implementation-plan generation, where only SOPs named in system instruction are included.
- Runtime SOP fallback behavior that appends Default SOP content only when no SOP names are referenced in system instruction.

## Modified Capabilities
- Terminology update across Skill and SOP authoring and view experiences:
  - Before: system instruction
  - After: workflow
- Terminology update for SOP fallback designation:
  - Before: Primary SOP
  - After: Default SOP
- Default SOP applicability expanded:
  - Before: available only for no-input agent type
  - After: available for all supported agent input types
- Authoring experience now supports assisted draft creation:
  - Before: manual workflow drafting only
  - After: optional AI-generated workflow draft, then user edits and confirms
- Preview behavior expanded:
  - Before: no dedicated preview of fully composed workflow context
  - After: explicit preview action showing the formatted instruction file and the configured model prior to save/publish
- Generation model selection expanded:
  - Before: model choice was implicit or hardcoded
  - After: administrators can choose the model from a dedicated system configuration page, sourced from the existing model config module
- Missing model handling is explicit:
  - Before: generation paths could rely on implicit defaults
  - After: generation and preview fail with a user-visible error when no model is configured
- Implementation-plan SOP context behavior is explicit:
  - Before: SOP context inclusion did not consistently follow system instruction references
  - After: only SOPs named in system instruction are included; if no SOP is named, Default SOP is included as fallback
- Runtime SOP injection behavior is explicit:
  - Before: fallback SOP injection could occur regardless of explicit SOP references
  - After: if SOP names are present in system instruction, Default SOP is not injected; if none are present, Default SOP content is appended as fallback

## Removed Capabilities
- Implicit requirement that users must always draft workflow text from scratch.
- Legacy Primary SOP naming and no-input-only fallback behavior.

## Spec Update Instructions
- Update master Skills feature spec to define workflow terminology, AI generation trigger, and Skill preview composition requirements.
- Update master SOPs feature spec to define workflow terminology, AI generation trigger, and SOP preview composition requirements.
- Add a new master system configuration spec area for generation model selection and preview header visibility.
- Update master settings/configuration spec to describe the model selection page used by workflow generation.
- Update governance and instruction-visibility spec to clarify workflow preview obligations and the rendered instruction file shape.
- Update governance and agent planning specs to define instruction-aware SOP selection: include only SOPs named in system instruction for plan context, with Default SOP fallback only when no SOP names are present.
- Update runtime instruction composition specs to define that Default SOP content is appended only when system instruction does not reference SOP names.
- Update terminology references in master specs from Primary SOP to Default SOP and remove any no-input-only constraint.
- Document non-functional guardrails in master product specs: no sensitive identity tokens or database credentials exposed to agents, and existing access boundaries remain unchanged.
- Add acceptance criteria language in master product specs for failure handling: users can continue manual editing when AI generation is unavailable.
