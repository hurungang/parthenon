# PRD: Agent Type Multi-SOP Binding

## Epic Overview

Agent Types in Parthenon currently support only a single primary SOP binding via the `primary_sop_id` field. When a role associates many SOPs and skills, agents receive all of them as context regardless of relevance — a noisy, unfocused experience that can confuse the agent and produce unpredictable behavior. Agent designers lack the ability to curate exactly which SOPs and skills an agent type should use. This change introduces multi-SOP binding for Agent Types, modelled on the same ordered-list pattern already established in how SOPs bind skills: each Agent Type stores an ordered list of binding entries, where each entry references either an SOP or a skill. These bindings define a curated subset drawn from the role's permissions, drive the system instruction generator and Agent Plan Mode to produce focused context, and are visible to users in the Agent Type editor. The existing `primary_sop_id` single-binding transitions into this richer model.

## Business Goals

- Improve agent predictability and accuracy by narrowing execution context to only the SOPs and skills explicitly curated for that agent type.
- Reduce agent misconfiguration and confusion by preventing unrelated role-assigned SOPs and skills from polluting the agent's context.
- Increase operator confidence in agent configuration through transparent UI visibility of exactly which SOPs and skills each agent type is bound to.
- Establish a consistent mental model across the platform: Agent Types bind SOPs in the same ordered-list pattern that SOPs already use to bind skills, reducing the learning curve.
- Enable more precise Agent Plan Mode output and system instruction generation by providing an explicit, curated input set instead of an unfiltered role dump.

## Users & Personas

- **AI Solution Architects / Agent Designers**: Need to curate exactly which SOPs and skills an agent type uses, filtering out irrelevant role-assigned capabilities to produce focused, predictable agent behaviour.
- **Platform Administrators**: Need visibility into the SOP and skill configuration of every agent type for auditing, governance, and troubleshooting.
- **AI Operations Leads**: Rely on predictable agent behavior and want confidence that agents only operate within their intended capability boundary.
- **Compliance Officers / Auditors**: Require traceability from agent type to the specific SOPs and skills it is authorised to use.

## User Stories

- As an **agent designer**, I want to bind multiple SOPs and skills to an agent type as an ordered list of entries, so that I can curate exactly which capabilities the agent uses and set the context order for AI-generated system instructions.
- As an **agent designer**, I want each binding entry to reference either an SOP or a skill (not both), so that I have the flexibility to compose a capability list at whatever granularity makes sense for the agent.
- As an **agent designer**, I want the bound SOPs and skills to be clearly visible in the Agent Type editor UI, so that I can understand and review the agent's capability set at a glance without inspecting the role.
- As an **agent designer**, I want the system instruction generator and Agent Plan Mode to use only my explicitly bound SOPs and skills (not all role-assigned ones), so that the generated plan and instructions are focused and relevant.
- As an **agent designer**, I want to reorder binding entries via the UI, so that I can control the sequence in which SOPs and skills are presented as context to the AI generators.
- As a **platform administrator**, I want the binding UI to validate that every bound SOP and skill is accessible through at least one role assigned to the agent type's identity, so that I cannot accidentally configure unreachable capabilities.

## Acceptance Criteria

### Structural acceptance criteria

1. An Agent Type stores an ordered list of SOP binding entries. Each entry contains: an order number, a reference type (SOP or Skill), and a reference ID.
2. The existing `primary_sop_id` field is transitioned into this new binding model — an Agent Type that previously had a single primary SOP now has a single binding entry referencing that SOP.
3. Bound SOPs and skills must be accessible through at least one role assigned to the agent type's runtime identity. The system rejects bindings that reference SOPs or skills outside of the agent's role-granted permissions.

### CRUD acceptance criteria (Agent Type editor — SOP bindings)

4. **CREATE:** The user can add a new binding entry to the Agent Type via a dialog or inline control. The user selects the entry type (SOP or Skill) and picks the target from a list of role-accessible items. The new entry is appended to the existing ordered list.
5. **READ:** All binding entries for an Agent Type are displayed in the editor UI in their defined order. Each entry shows its order number, the referenced SOP or skill name, and its type badge. The list loads correctly when the Agent Type record is opened.
6. **UPDATE:** The user can reorder binding entries (move up / move down / drag), change the referenced SOP or skill of an entry, or remove an entry. All changes are saved on the same save action that saves the Agent Type record. After saving, the binding list reflects all changes without requiring a manual page reload.
7. **DELETE:** The user can remove a binding entry from the list. The removal is committed on save. The binding list and any related counts update immediately after save without page reload.

### Validation acceptance criteria

8. The system rejects a binding entry that references an SOP or skill not accessible through the agent type's assigned role, with a clear, user-visible error message.
9. The system prevents duplicate binding entries (same SOP or skill referenced more than once) and shows a clear error.
10. The binding order is preserved exactly as the user arranges it — the saved order matched against the displayed order after reload.

### Integration acceptance criteria

11. The system instruction generator uses only the explicitly bound SOPs and skills (not all role-assigned ones) as input context. Bound entries are presented in their saved order.
12. Agent Plan Mode uses only the explicitly bound SOPs and skills (not all role-assigned ones) when generating the implementation plan for a new or updated Agent Type.
13. If an Agent Type has no binding entries, the system instruction generator and Agent Plan Mode behave as they do today (no curation — current fallback behavior is preserved).
14. The Agent Plan Mode topology diagram reflects the bound SOPs and skills, showing the relationships from agent type to each bound entry.

### Error handling acceptance criteria

15. If an Agent Type is saved with invalid binding entries (unreachable SOP/skill, duplicates), the save is rejected and the user sees a specific error message per invalid entry.
16. If the referenced SOP or skill is deleted while still bound to an Agent Type, the binding renders as a broken reference in the UI with a clear visual indicator, and the user is prompted to update the binding before the agent type can execute.

### UI and accessibility acceptance criteria

17. All binding UI text (labels, placeholders, error messages, type badges) is internationalised via i18next.
18. The binding list is keyboard-navigable: reorder controls, remove controls, and the add-binding control are all reachable and operable via keyboard.
19. After closing the add/edit/delete binding dialog, the parent binding table on the Agent Type editor automatically refreshes without requiring the user to manually reload the page.

## Out of Scope

- **No execution-time ordering enforcement.** The binding order is context for AI-generated system instructions — agents follow the generated system instruction, not the binding order itself. The order is not a runtime execution sequence.
- **No changes to how SOPs bind skills.** The SOP-to-Skill binding model remains unchanged; this change adds the same pattern at the Agent Type level but does not modify the existing implementation.
- **No changes to role-based SOP/skill assignment.** Roles continue to define the full set of SOPs and skills an agent identity is permitted to access; Agent Type bindings filter that set.
- **No automatic migration of all existing Agent Types.** Existing Agent Types with a `primary_sop_id` transition gracefully into a single-entry binding list, but there is no bulk conversion tool or forced migration.
- **No conditional or branching binding logic.** Binding entries are a flat ordered list — there is no support for conditional inclusion (e.g., "bind this SOP only when X"), branching, or dependency rules between entries.
- **No nested SOP references via bindings.** When a binding entry references an SOP, the system does NOT recursively expand that SOP's own skill bindings into the Agent Type's binding list.
- **No runtime binding adjustment.** Bindings are static at execution time — the agent cannot modify its own bindings during a run.
- **No versioning or history of binding changes.**
- **No export or import of binding configurations.**

## Dependencies & Constraints

- **Existing SOP binding model is the reference pattern.** The Agent Type binding model mirrors the established SOP-step-to-skill binding model (ordered list, one reference per entry). Any change to the SOP binding model may cascade here.
- **Role resolution must be complete and accurate.** Validation that bound SOPs and skills are role-accessible depends on the existing role-permission resolution logic being correct and up to date.
- **System instruction generator must be updated** to consume the new binding list instead of (or as a filter over) all role-assigned SOPs and skills.
- **Agent Plan Mode must be updated** to consume the new binding list for plan generation and topology diagram rendering.
- **Backward-compatibility requirement.** Existing Agent Types with only `primary_sop_id` set must continue to function — their single binding is treated as a one-entry binding list. No data loss is acceptable.
- **UI constraint.** The binding list editor must fit within the existing Agent Type editor layout without requiring a page-level redesign.
- **Permission system constraint.** The list of selectable SOPs and skills in the binding picker must be gated to only show items the agent's assigned role(s) grant access to.
- **Top-priority rules from `docs/config.yaml`:** No top-priority rules are impacted — this change operates entirely within the Control Center and its associated UI, with no agent-runtime-side data exposure.
