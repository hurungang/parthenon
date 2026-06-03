# Spec Change: Agent Type Multi-SOP Binding

## Affected Spec Areas

This change modifies the Agent Type configuration model and extends how the system instruction generator and Agent Plan Mode consume capability data. It also introduces a new UI surface within the Agent Type editor for managing the binding list. No changes to the SOP or Skill entity models themselves, nor to the role-permission model.

| Master Spec Area | Path | Impact |
|---|---|---|
| Agent Types | `docs/master/product/features/agent-types.md` | Primary change: new multi-SOP binding capability, transition from single `primary_sop_id`. |
| Agent Plan Mode | `docs/master/product/features/agent-plan-mode.md` (or closest equivalent) | Plan generation and topology diagram now consume the curated binding list instead of all role-assigned SOPs/skills. |
| System Instruction Generation | (existing spec, if any) | Generator now uses bound SOPs/skills as input context instead of unfiltered role dump. |
| SOPs | `docs/master/product/features/sops.md` | Minor: note that Agent Types use the same ordered-binding pattern established by SOP→Skill bindings. |
| Skills | `docs/master/product/features/skill-management.md` | Minor: note that skills can now be bound directly to Agent Types as well as to SOPs. |

> **Note:** No `openspec/specs/` directory exists in this project — master product specs are stored under `docs/master/product/features/`. Links above point to the equivalent locations.

---

## New Capabilities

- **Multi-SOP/Skill binding for Agent Types.** An Agent Type can bind multiple SOPs and skills in an ordered list of entries. Each entry references either an SOP or a skill and has an order number. The order is context for AI-generated system instructions — not an execution sequence.
- **Binding curation.** The bound SOPs and skills define the curated subset that the agent type explicitly uses, drawn from the set of SOPs and skills the agent's role grants access to.
- **Binding visibility in the Agent Type editor.** Users can view, add, remove, and reorder binding entries directly within the Agent Type editor UI.
- **Binding-driven instruction and plan generation.** The system instruction generator and Agent Plan Mode consume only the explicitly bound SOPs and skills (not all role-assigned ones), producing focused, relevant output.
- **Binding validation.** The system validates that every bound SOP or skill is accessible through at least one role assigned to the agent type. Invalid bindings are rejected with clear error messages.

---

## Modified Capabilities

### Agent Type configuration model

**Before:**

Agent Types store a single `primary_sop_id` — one SOP reference. The system instruction generator and Agent Plan Mode use all SOPs and skills from the agent's assigned role as context, regardless of relevance.

**After:**

Agent Types store an ordered list of SOP binding entries. Each entry has:
- An order number (integer, determines sequence in the list)
- A reference type (SOP or Skill)
- A reference ID (the ID of the bound SOP or skill)

The `primary_sop_id` field transitions into this model: an Agent Type that previously had a single primary SOP now has one binding entry referencing that SOP with order 1. The system instruction generator and Agent Plan Mode use only the explicitly bound entries as context, in their defined order.

### System instruction generator

**Before:** Used all role-assigned SOPs and skills as input context.

**After:** Uses only the Agent Type's bound SOPs and skills as input context. If no bindings exist, falls back to current behaviour (all role-assigned items).

### Agent Plan Mode

**Before:** Generated implementation plans and topology diagrams using all role-assigned SOPs and skills.

**After:** Uses only the Agent Type's bound SOPs and skills for plan generation. The topology diagram shows only the bound entries, with relationships traced from agent type → each bound SOP/skill → (for SOPs) their child skills → tools.

### Agent Type editor UI

**Before:** A single SOP picker (or none, depending on implementation state).

**After:** A binding list editor showing all bound entries in order, with controls to add new entries, remove entries, and reorder the list. Each entry displays the referenced SOP or skill name and its type badge. The binding list saves atomically with the Agent Type record on the same save action.

---

## Removed Capabilities

- **`primary_sop_id` as a standalone field.** The single-SOP binding is replaced by the multi-binding list. The field is no longer independently visible or editable in the UI — existing values are represented as single-entry binding lists.

---

## Spec Update Instructions

Update the following master spec areas to reflect the new binding model. **No code, schema, or implementation details are to be added to spec files.**

### 1. `docs/master/product/features/agent-types.md` — Primary update

- In the **"What It Does"** section, add a bullet describing the multi-SOP/skill binding capability:
  - "Supports binding multiple SOPs and skills to an Agent Type as an ordered list of entries, where each entry references either an SOP or a skill; bindings define the curated capability set used for system instruction generation and Agent Plan Mode."
- Add a new **"SOP & Skill Binding"** subsection (or extend an existing configuration section) documenting:
  - How bindings work: ordered list, each entry is an SOP or skill reference.
  - That bindings must be role-accessible (validation).
  - That the order is AI context, not execution sequence.
  - That the binding list replaces the legacy single-SOP field.
  - That bindings drive system instruction generation and Agent Plan Mode.
- In the **"Acceptance Criteria"** section, add:
  - "Agent Types support binding multiple SOPs and skills in an ordered list."
  - "Bound SOPs and skills must be accessible through the agent's assigned role; invalid bindings are rejected."
  - "System instruction generator and Agent Plan Mode use only explicitly bound SOPs and skills."
  - "Binding list is visible and editable in the Agent Type editor UI."
- In the **"Dependencies & Constraints"** section, add:
  - "SOP/skill binding validation depends on accurate role-permission resolution."
  - "Binding UI must be keyboard-accessible and internationalised."

### 2. Agent Plan Mode spec — `docs/master/product/features/agent-plan-mode.md` (or equivalent)

- Update the plan generation description to state that the plan is generated from the Agent Type's **bound SOPs and skills** (not all role-assigned ones).
- Update the topology diagram description to note that it traces relationships from agent type → bound entries only.
- Add an acceptance criteria bullet: "Plan Mode uses only the Agent Type's explicitly bound SOPs and skills when generating plans and diagrams."

### 3. System instruction generation spec (if a dedicated spec exists)

- Update the instruction-generation input description to note that only bound SOPs and skills are included as context.
- Add a fallback note: if no bindings are defined, the generator falls back to all role-assigned SOPs and skills (current behaviour).

### 4. `docs/master/product/features/sops.md` — Minor update

- In the **"What It Does"** or relevant section, add a note: "Agent Types bind SOPs using the same ordered-list pattern that SOPs use to bind skills, allowing agent designers to curate which SOPs an agent type uses."

### 5. `docs/master/product/features/skill-management.md` — Minor update

- In the **"What It Does"** section, add a note: "Skills can be bound directly to Agent Types (in addition to SOPs), giving agent designers the flexibility to reference skills at any granularity."

### 6. Master UX prototype — `docs/master/ux/prototype/index.html`

- Add the binding list editor UI to the Agent Type editor section of the prototype:
  - A list of bound entries showing order number, SOP/skill name, type badge.
  - An "Add Binding" control that opens a dialog allowing selection of type (SOP/Skill) and target item.
  - Reorder controls (up/down arrows or drag handles) on each entry.
  - Remove control (trash icon or X button) on each entry.
  - Validation error display for unreachable or duplicate bindings.
  - A note that the binding list saves as part of the Agent Type save action.

### 7. Master QA / test plan

- Add or update test coverage for the Agent Type editor to include:
  - Full CRUD lifecycle of binding entries (add, view, edit, reorder, delete).
  - Validation: unreachable SOPs/skills rejected, duplicates rejected.
  - Integration: system instruction generator and Agent Plan Mode consume only bound entries.
  - Backward compatibility: existing Agent Types with only `primary_sop_id` remain functional.
  - Regression: role-based SOP/skill assignment and permission gating still work correctly.

### 8. Master architecture / data model / deployment / operations

- **Architecture:** May need updates if Agent Plan Mode or system instruction generation service architecture changes (handled by architect agent in `architecture.md`).
- **Data model:** A new entity/table for the binding list is expected (handled by database_designer agent in `data-model.md`).
- **Deployment:** Database migration for the new binding table and transition of `primary_sop_id` data (handled by developer agent in `deployment.md`).
- **Operations:** No operational impact expected (no new services, no changed logging topology).
