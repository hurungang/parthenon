# Agent Plan Mode — Spec Change Delta

## 1. Affected Spec Areas

- [docs/master/agent-types/](../master/agent-types/)
- [docs/master/agent-roles/](../master/agent-roles/)
- [docs/master/sops/](../master/sops/)
- [docs/master/skills/](../master/skills/)
- [docs/master/ui/agent-type-editor.md](../master/ui/agent-type-editor.md)
- [docs/master/ui/agent-plan-preview.md](../master/ui/agent-plan-preview.md) *(new or updated)*
- [docs/master/ux/prototype/](../master/ux/prototype/)

## 2. New Capabilities

- Automatic generation of a step-by-step implementation plan for each Agent Type upon save
- Visual topology diagram showing Agent Role, SOPs, Skills, and Tools for the agent
- Plan and diagram preview available before agent execution or deployment
- Dynamic plan updates in response to changes in agent configuration
- Clear error messaging for plan generation failures

## 3. Modified Capabilities

**Before:**
- Users could configure Agent Types and assign roles, SOPs, and skills, but had no way to preview the agent's execution plan or see a visual representation of its logic.
- No consolidated view of how SOPs, skills, and tools would be orchestrated for a given agent.

**After:**
- Users see a generated, human-readable plan outlining the agent's workflow, based on its configuration.
- Users can view a topology diagram mapping the relationships between Agent Role, SOPs, Skills, and Tools.
- Plan and diagram are available for preview before agent execution, increasing transparency and reducing misconfiguration.

## 4. Removed Capabilities

- None. No existing user-facing capabilities are removed by this change.

## 5. Spec Update Instructions

- Update [agent-types spec](../master/agent-types/) to describe plan generation and preview requirements.
- Update [agent-roles spec](../master/agent-roles/) to clarify role-to-SOP/Skill mapping for plan generation.
- Update [sops](../master/sops/) and [skills](../master/skills/) specs to note their inclusion in agent plans and diagrams.
- Update [ui/agent-type-editor.md](../master/ui/agent-type-editor.md) to add plan preview and diagram UI requirements.
- Create or update [ui/agent-plan-preview.md](../master/ui/agent-plan-preview.md) to specify plan/diagram display, user flows, and error handling.
- Update [ux/prototype/](../master/ux/prototype/) to include new plan mode screens and user journeys.
- Ensure all new/modified UI text is included in i18next resource files and follows localization guidelines.
