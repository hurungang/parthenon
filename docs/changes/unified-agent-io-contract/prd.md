# Epic PRD: Unified Agent I/O Contract

## Epic Overview

Parthenon agents have no agreed contract for what goes in and what comes out. A result's shape is currently decided by a mix of settings — an output-type choice, an optional output data type, a legacy free-text schema that only reaches the prompt, and whichever execution path happened to run — so LLM runs, fully-scripted plans, delegated agents, and conversations each return something different. Operators feel it: a delegated agent set to "Auto" hands its parent an untyped block of markdown that nothing can mark as parseable, the optimizer never sees the reference run's contract so it predicts the wrong final format and wrongly declares a workflow fully scriptable, and the same result is described as text in one surface and JSON in another. Input is just as fragmented: typed inputs are hand-authored schemas, so a realistic field such as a passenger list has to be squeezed into one unvalidated comma-separated string. This epic gives every execution path one canonical result shape with an explicit, config-driven result type, makes registered data types the single contract for both input and output, allows one level of child data type plus list fields, adds a schema source view beside the guided editor, and makes delegation, optimization, the result repository, and the UI all read the same result. Existing agents, data types, and recorded executions keep working through a documented, backwards-compatible path.

## Business Goals

- **One result shape, always.** 100% of agent results — LLM, fully-scripted, delegated, conversational, and failed — use the same envelope (execution status, declared result type, result payload, contract metadata); no result exists without a declared result type.
- **No more false "fully scriptable" claims.** Every boundary whose result is markdown or free text is recognised as a semantic step, so optimization can never mark a workflow fully scriptable across such a boundary — target: zero misclassified boundaries after rollout.
- **Data types become the single definition of both input and output.** "Typed output with no data type" and "data type attached to a non-typed output" become impossible states; 100% of typed agent results are validated against their declared data type.
- **Cut the cost of typed input.** A realistic structured input (for example a passenger list) is authored and entered as structured fields in one pass, with no hand-written schema — target: no hand-authored raw schema is required for standard one-level structures.
- **Zero loss on upgrade.** 100% of existing agent types, data types, and previously recorded executions stay readable, valid, and renderable after the change, with a documented migration path.

## Users & Personas

- **Agent Designer / Platform Administrator** — Configures agent types, their result type, and their input and output data types. Needs to express realistic structures (lists of sub-records) without hand-writing schemas, needs the two editor views to agree, and needs to confirm the contract without leaving the agent type dialog.
- **Agent Operator** — Launches agents, reads results, and triggers optimization. Needs one predictable result shape, a visible statement of what type the result is, and an honest answer about whether a workflow is fully scriptable.
- **SOP Author / Workflow Designer** — Composes multi-agent procedures. Needs a delegated agent's result to be typed and inspectable so a parent step can trust it, and needs structured inputs to reach sub-agents intact.
- **Integrator (Third-Party Client)** — Submits typed requests and receives typed results through a client. Needs the input contract it must satisfy and the delivered result (with validation status) to match what the platform itself uses.
- **Compliance & Audit Stakeholder** — Needs every recorded result to be traceable to a declared contract, and needs legacy results to remain readable rather than silently reinterpreted.
- **Business Owner** — Benefits from cheaper, faster optimized workflows that are only declared scriptable when they truly are, and from fewer failed delegation hand-offs.

## User Stories

- As an agent designer, I want every agent result to come back in one consistent shape, so that I can consume it without knowing which execution path produced it.
- As an agent designer, I want to choose an explicit result type (text, markdown, JSON, or typed) for an agent, so that the contract is deliberate rather than inferred from whichever setting happened to win.
- As an agent designer, I want business fields to stay separate from the platform's own runtime bookkeeping, so that my result structure never collides with the envelope.
- As an agent designer, I want to pick one data type and have it define both the agent's input and output, so that I define a contract once instead of maintaining two disagreeing definitions.
- As an agent designer, I want to define a reusable child data type and reference it from a parent field as a single value or a list, so that structures like a passenger list are described in the product instead of hand-written.
- As an agent designer, I want a limit of one child level, so that schemas stay reviewable and predictable and no one accidentally builds an unbounded nested model.
- As an agent designer, I want to switch between a guided field editor and the schema source view, so that I can paste or copy a schema when that is faster and still trust both views agree.
- As an agent designer, I want to preview the selected data type's schema inside the agent type dialog, so that I can confirm the contract before saving without opening another page.
- As an agent operator, I want to enter structured input as proper rows and fields, so that a passenger list is typed in as passengers rather than as one comma-separated line.
- As an agent operator, I want invalid input rejected with a clear message before the run starts, so that bad data never reaches the agent.
- As a SOP author, I want a delegated agent's result to arrive with a declared type, so that the parent step (and the optimizer) can tell whether it is parseable.
- As a SOP author, I want optimization to treat a markdown or free-text boundary as a semantic step, so that it never claims a workflow is fully scriptable when a model must still interpret that hand-off.
- As an agent operator, I want optimizer previews to be based on the reference execution's actual result and contract, so that the predicted final format matches reality.
- As an integrator, I want my typed submission validated against the agent's input contract and the delivered result to carry its status and type, so that my integration behaves the same as an in-product run.
- As a compliance stakeholder, I want results recorded before this change to remain readable, so that history is not rewritten or lost.

## Acceptance Criteria

### One result shape on every execution path

- An LLM run, a fully-scripted run, a delegated agent run, a conversational turn, and a failed run all return the same result shape: an execution status, a declared result type, a result payload, and contract metadata.
- Business fields appear only inside the payload; they never appear at the envelope's top level or mix with the platform's own runtime bookkeeping.
- A failed execution still returns the envelope with a failure status and a readable reason rather than a differently shaped error. For a failed conversational turn the envelope is carried internally and in logs; the error surface the user sees in chat is unchanged.
- Every surface that shows a result — execution log, result repository, delegated hand-off, script result, optimization preview — shows the same status, result type, and payload for that result.
- The declared result type is visible wherever a result is shown, so the operator can tell at a glance whether the result is text, markdown, JSON, or typed.

### Declared result type drives scriptability

- The result type is an explicit setting on the agent type (text, markdown, JSON, typed); it is no longer inferred from the presence of a data type or from a legacy free-text schema.
- Selecting "typed" requires a data type; without one the configuration cannot be saved, and the user is told why.
- Attaching a data type while the result type is anything other than "typed" is prevented rather than being silently converted into typed output.
- Delegation records the delegated agent's declared result type with the hand-off, so a parent step can distinguish a parseable payload from free text.
- When a boundary's result type is markdown or free text, optimization treats that boundary as a semantic step and never reports the overall workflow as fully scriptable.
- When every boundary in a workflow is declared typed or JSON, optimization may report the workflow as fully scriptable.
- The optimizer is given the reference execution's result and its declared contract, so the predicted final format and the scriptability verdict are based on the real result rather than on an assumption.
- A given result uses one format everywhere (execution log, result repository, delegation, third-party delivery): a typed or JSON result is JSON in all of them and a text result is text in all of them.

### Data types are the single input and output contract

- A data type can be assigned to a non-conversational agent type as its input contract, as its output contract, or both, using the same registry entry and the same definition.
- Agents can be run with no input contract (unchanged for existing free-prompt agents); assigning an input data type makes structured input mandatory for that agent.
- Typed results are validated against the output data type; a validation failure still completes the run, is recorded, and shows the raw result as a fallback, unchanged from today.
- Input submitted to an agent with an input data type is validated before the run starts; invalid input is rejected with a message naming the offending field, and no execution is started.
- Improving a data type is reflected everywhere it is used — agent type dialog, decision tools, result rendering — without re-entering the definition.
- Third-party typed submissions are validated against the same input contract and receive the same delivered result shape (status, result type, payload) as an in-product run.

### Child data types and list fields

- A data type field can reference another registered data type as a child, either as a single value or as a list of that child type.
- Child references are one level only: a data type used as a child cannot itself reference another data type. Attempting to create a deeper chain is rejected with a clear message.
- A child data type can only be referenced by data types in the same tenant; a reference to another tenant's data type is rejected with a clear message.
- A child data type cannot be deleted while it is referenced by a parent data type or by any agent type; the error names the dependents.
- Editing a child data type is reflected wherever it is referenced, and the user is warned that the change affects all consumers of that child.
- Any field — primitive or child reference — can be marked as a list.
- A realistic structure (for example: a request with a list of passengers, each with a name, an adult/child/infant type, and a bag count) can be modelled entirely through the registry, with no hand-written schema.
- Create, edit, and delete keep today's behaviour (immediate list refresh, edit pre-filled with current values, confirmation before delete); the new child-reference rules apply on top. After a data type is deleted its name becomes available again; duplicate names are rejected; at least one field is required.

### Data type editing: guided fields and schema source

- The data type editor offers two views over the same definition: a guided field editor and a schema source view that can be pasted into and copied from.
- Switching between the two views never silently discards content: a definition that cannot be represented in the guided view is preserved in the source view and the user is told that the guided view cannot fully display it.
- A definition the product cannot represent (deeper nesting, unsupported types, recursive structures) is rejected on save with a message that points at the specific problem.
- Saving from either view updates the same data type, and every other surface that displays that data type (agent type dialog, decision tools, result rendering) reflects the change on next load.
- Duplicate and required-field validation applies identically regardless of which view was used.

### In-dialog contract preview

- The agent type definition dialog lets the user preview the selected input data type's schema and the selected output data type's schema without leaving the dialog.
- The preview shows the same fields, types, allowed values, and child/list structure the user would see in the registry, and updates immediately when a different data type is selected.
- The preview is read-only; no editing path is introduced there, and no extra navigation is required.

### Structured input entry

- For a non-conversational agent with an input data type, the launch/submit surface presents a structured entry form derived from that data type instead of a single free-text field.
- Fields of a child data type are entered as a nested group, and a list field is entered as repeatable rows with add/remove controls, so a passenger list is typed in as passengers.
- Enum fields offer only their allowed values; dates, numbers, and booleans are entered with type-appropriate controls.
- Required fields are indicated and enforced; submitting an incomplete form shows field-level messages and does not start the run.
- Agents with no input data type, and conversational agents, keep today's free-prompt entry unchanged.

### Backward compatibility

- Existing agent types keep working without operator action: their current output behaviour is preserved and presented in the new vocabulary with a declared result type.
- The legacy "auto" value remains readable for existing agents and is normalised on read to text (free text; a markdown-looking body is not reclassified); new agent configurations do not rely on implicit auto.
- Existing data types, including those with a legacy free-text schema alongside structured fields, remain readable and continue to validate results as they do today.
- Previously recorded executions and results remain readable and renderable in execution logs, the result repository, and exports; historical results are not rewritten or retroactively revalidated.
- The migration path for legacy free-text schemas is documented for operators, including the cases where a faithful automatic conversion is not possible and manual review is advised. No review queue or approval step is introduced.
- No recorded production result or configured agent loses its data as part of this change.

## Out of Scope

- Arbitrary or deeply nested data types beyond one child level; no recursive, self-referencing, or multi-level composition.
- Free-form schema libraries, third-party schema registries, or importing schemas from outside the product.
- Any change to agent identity, role, or permission semantics.
- Redesigning conversation UX: a failed conversational turn carries the envelope internally and in logs only, and the existing chat error surface is unchanged.
- Typed inputs, structured input entry, or typed outputs for conversational turns beyond carrying a consistent result shape.
- A review queue, approval workflow, or operator triage surface for legacy free-text schemas; the migration path is documented, not worked off as a backlog.
- Data type versioning, schema history, or retroactive revalidation of past results.
- Production data loss: legacy input and output schema definitions remain readable and are never dropped by this epic.
- Automatic migration of every exotic legacy free-text schema into a lossless structured definition.
- Changing how scripts are sandboxed, versioned, or promoted; the script registry lifecycle is untouched.
- Changing execution preference and fallback semantics, guardrails, or optimization trigger rules.

## Dependencies & Constraints

- **Service segregation (top priority).** Control Center owns the data type registry and all definitions; Agent Runtime consumes contracts read-only and never reaches the database; agents are never given credentials or identity tokens.
- **Tenant isolation.** Data types, agent contracts, and recorded results stay tenant-owned and tenant-scoped; names remain unique per tenant, child references resolve only within the same tenant, and nothing is resolved across tenants.
- **Existing optimization framework.** Depends on the current optimization and plan-authoring flow, script-first execution with LLM fallback, and the script registry; this epic changes what those consumers read, not when they run.
- **Existing consumers must be migrated together.** Execution logs, the result repository, delegation, script results, plan contracts, reference-execution inspection, third-party delivery, and decision tools each currently assume their own result shape; the envelope is only real when all of them read it.
- **Legacy definitions stay readable.** Legacy free-text input and output schemas remain supported on read; the documented migration path must be available to operators before any editing surface stops offering them.
- **Compatibility over purity.** Where a legacy definition cannot be expressed in the new model, the platform keeps it working and adds a read-only migration note rather than blocking the upgrade.
- **Explainability.** Every rejection (missing data type, unsupported nesting, cross-tenant child, invalid input, non-convertible legacy schema) must state what the user must change; silent coercion between result types is not acceptable.
- **No new configuration burden.** No new setting, licence dimension, or deployment change is introduced; the change is confined to how contracts are defined, enforced, and consumed.
