# PRD: AI-Assisted Workflow Authoring for SOP and Skill

## Epic Overview
Authoring high-quality SOPs and Skills currently requires users to manually write both the workflow instruction and the execution steps, which slows delivery and creates inconsistency across teams. This epic introduces AI-assisted workflow authoring so users can generate a workflow from selected steps/tools plus a short business description, choose the model used for generation through a system configuration page, and review the final formatted instruction file before save or publish; it also standardizes SOP fallback behavior by renaming Primary SOP to Default SOP, allowing it for all agent input types, and making both plan generation and runtime SOP usage follow explicit SOP references in the system instruction with clear fallback rules.

## Business Goals
- Reduce average SOP authoring time by at least 30% for first draft creation.
- Reduce average Skill authoring time by at least 30% for first draft creation.
- Increase first-pass publish success rate (no rework due to unclear workflow text) by at least 20%.
- Improve author satisfaction for workflow clarity and usability to at least 4/5 in post-release feedback.
- Ensure zero increase in authorization incidents by preserving existing permission and sensitive-data boundaries.
- Give administrators a simple system configuration page to select the AI model used for instruction generation.
- Improve agent implementation-plan relevance by ensuring plan context includes only SOPs referenced in system instruction, with Default SOP fallback only when no SOP is referenced.

## Users & Personas
- Platform Administrators: need faster, consistent creation of governable SOPs and Skills.
- System Administrators: need a simple configuration page to choose the model used for workflow generation.
- AI Workflow Authors: need help translating intent into clear workflow text without starting from blank.
- Agent Designers: need predictable SOP selection behavior for implementation plans and runtime execution across all agent input types.
- Compliance and Operations Reviewers: need transparent preview of final workflow content before publish.

## User Stories
- As an AI Workflow Author, I want to generate an SOP workflow from selected steps and an SOP description so that I can create complete SOPs faster.
- As an AI Workflow Author, I want to generate a Skill workflow from selected tools and a Skill description so that I can produce clearer instructions with less manual drafting.
- As a System Administrator, I want to choose the model used for workflow generation from a system configuration page so that generation behavior is controlled centrally.
- As an Agent Designer, I want to configure a Default SOP for any agent input type so that all agents can have a governed fallback procedure.
- As an Agent Designer, I want implementation plan generation to include only SOPs named in system instruction so that plan context stays focused on explicitly requested procedures.
- As an Agent Designer, I want the Default SOP to be used as fallback only when system instruction names no SOP so that behavior is predictable and non-conflicting.
- As a Platform Administrator, I want the label to use workflow terminology so that the authoring experience is easier to understand.
- As a Compliance Reviewer, I want to preview the final Skill workflow as the formatted instruction file so that I can validate the exact content the agent will load before save or publish.
- As a Compliance Reviewer, I want to preview the final SOP workflow as the formatted instruction file so that I can verify the exact content the agent will load before execution.
- As a Compliance Reviewer, I want the preview header to show the configured generation model so I can verify which model produced the current draft.

## Acceptance Criteria
- In Skill and SOP authoring flows, users can trigger AI-assisted generation of workflow text using selected tools/steps and a short description.
- Generated workflow text appears in the editable workflow field and can be revised before saving.
- The field label and terminology are changed from system instruction to workflow in Skill and SOP create/edit/view experiences.
- Terminology is changed from Primary SOP to Default SOP in all relevant create/edit/view and configuration experiences.
- Default SOP can be assigned and saved for every supported agent input type, not only no-input agents.
- Administrators can select the generation model from a system configuration page.
- If no generation model is configured, AI generation and preview actions show a clear error instead of using a fallback model.
- Model options in system configuration come from the existing model configuration module.
- Skill dialogs provide a preview action that shows the final formatted instruction file the agent will load.
- SOP dialogs provide a preview action that shows the final formatted instruction file the agent will load.
- Preview headers show the configured generation model used for the draft.
- Preview content reflects current selections and latest edits without requiring manual refresh.
- When generating the agent implementation plan, only SOPs explicitly mentioned in system instruction are included in plan context.
- If system instruction mentions no SOPs, implementation plan context includes the Default SOP as fallback.
- At runtime, when system instruction references one or more SOP names, Default SOP content is not injected into the instruction.
- At runtime, when system instruction references no SOP names, Default SOP content is appended to the instruction as fallback.
- If generation fails or required input is missing, users receive a clear, actionable message and can continue manual editing.
- Existing access control boundaries remain enforced, including no direct exposure of sensitive identity tokens or database credentials to agents.

## Out of Scope
- Changes to role or permission models.
- New database schema or migration work.
- Changes to scheduling, execution runtime behavior, or external notification channels.
- Automatic publishing or approval workflow redesign.
- Automatic SOP-name inference from intent when SOP names are not explicitly present in system instruction.

## Dependencies & Constraints
- Depends on existing Skill and SOP authoring UI flows.
- Must comply with architecture rules: agent runtime isolation, control-center-owned database access, and no sensitive token/credential exposure to agents.
- Must preserve current auditability and traceability expectations for generated workflow content.
