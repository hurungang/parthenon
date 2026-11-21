## Overview

Implement the unified Agent Result Envelope and the data-type-as-contract model across Control Center, Agent Runtime, Communication Hub, and the frontend, without breaking any existing agent type, data type, or recorded result. Work proceeds in dependency order: schema foundation and backfill, then contract resolution and legacy adaptation, then envelope production and consumption on every path, then optimization, UI, third-party parity, and finally cross-cutting verification.

## Task Checklist

### Phase 1 — Data-type and contract schema foundation

- [ ] 1.1 — Add the canonical definition and child-reference entity to the data-type model
- [ ] 1.2 — Add result-type, input-contract, and validation-status columns to agent type, job, and output models
- [ ] 1.3 — Generate and hand-review the structure Alembic revision
- [ ] 1.4 — Apply and verify the structure revision
- [ ] 1.5 — Write, apply, and verify the idempotent backfill revision
- [ ] 1.6 — Implement the schema canonicalizer and guided-field projection module
- [ ] 1.7 — Extend data-type Pydantic schemas for canonical definitions, list flags, and child references
- [ ] 1.8 — Rework the data-type write path to regenerate the projection and enforce child rules
- [ ] 1.9 — Extend data-type delete protection and consumer listing to child references and input assignments
- [ ] 1.10 — Add the projection drift reconcile/repair path
- [ ] 1.11 — Extend the data-type REST API for canonical schema, source validation, and expanded usage
- [ ] 1.12 — Backend tests for canonical definitions, child rules, list fields, and delete protection

### Phase 2 — Contract resolution, legacy adapter, and agent I/O configuration

- [ ] 2.1 — Create the pure contract module with declared-result-type normalisation
- [ ] 2.2 — Implement the backward-compat adapter for legacy result types and legacy schemas
- [ ] 2.3 — Build the read-only contract snapshot with one-level child expansion
- [ ] 2.4 — Implement the scriptability classifier for boundaries and result types
- [ ] 2.5 — Define the envelope models for build, normalise, and validate
- [ ] 2.6 — Enforce contract invariants on the agent-type write path
- [ ] 2.7 — Expose the resolved contract on the agent-type read path
- [ ] 2.8 — Enforce conversational restrictions and retire implicit auto for new configurations
- [ ] 2.9 — Support data-type source editing and guided-representability in the registry service
- [ ] 2.10 — Backend tests for resolution, legacy adapter, invariants, and scriptability

### Phase 3 — Envelope on every execution path

- [ ] 3.1 — Return the contract snapshot from the internal agent-context endpoint
- [ ] 3.2 — Build the envelope after the Agent Runtime LLM loop
- [ ] 3.3 — Drive typed persistence from the envelope and stop flattening business fields
- [ ] 3.4 — Derive provider structured-output and schema prompts from the resolved contract
- [ ] 3.5 — Add step-contract checking to the fully-scripted dispatch path
- [ ] 3.6 — Carry the envelope and declared result type through delegation hand-offs
- [ ] 3.7 — Keep the Communication Hub a pass-through for envelope results
- [ ] 3.8 — Persist envelope facts on session completion in Control Center
- [ ] 3.9 — Derive one content type per result in the result repository
- [ ] 3.10 — Persist envelopes for failed and terminated runs
- [ ] 3.11 — Build internal-only envelopes for conversational turns and failures
- [ ] 3.12 — Return envelopes from the result, output, and execution-log read paths
- [ ] 3.13 — Backward-compat read adapter for historical rows and results

### Phase 4 — Optimization integration

- [ ] 4.1 — Expose the reference result and declared contract from the execution-log tool
- [ ] 4.2 — Validate step contracts when an optimized plan is generated
- [ ] 4.3 — Reject fully-scripted claims across text or markdown boundaries
- [ ] 4.4 — Check the result contract during script replay verification
- [ ] 4.5 — Resolve script input validation from the input contract, not the legacy schema
- [ ] 4.6 — Record the declared result type per step and per hand-off in plan payloads
- [ ] 4.7 — Update optimizer mission and mode prompts with contract guidance
- [ ] 4.8 — Tests for verdicts, step-contract rejection, and reference-result exposure

### Phase 5 — Frontend

- [ ] 5.1 — Extend frontend types for result types, input contracts, canonical schemas, and child references
- [ ] 5.2 — Extend the data-type hooks for new payload fields and invalidation
- [ ] 5.3 — Extend the data-types page with consumers, agent usage, and legacy markers
- [ ] 5.4 — Add guided and schema-source tabs to the data-type editor
- [ ] 5.5 — Add child data-type selection with one-level constraints
- [ ] 5.6 — Add the per-field list toggle and keep the enum editor consistent
- [ ] 5.7 — Handle source-only definitions without silent loss
- [ ] 5.8 — Show consumer warnings and blocked deletion with named dependents
- [ ] 5.9 — Add the input contract slot and explicit result type to the agent type form
- [ ] 5.10 — Add read-only input and output schema preview inside the agent type dialog
- [ ] 5.11 — Build the structured input form for agents with an input data type
- [ ] 5.12 — Render results from the envelope with a visible result type
- [ ] 5.13 — Show result type and validation status in the repository and outputs pages
- [ ] 5.14 — Present legacy agents and legacy results in the new vocabulary
- [ ] 5.15 — Frontend tests for the editor, contract form, structured input, and rendering

### Phase 6 — Third-party and decision-tool parity

- [ ] 6.1 — Expose the input contract to integration clients
- [ ] 6.2 — Validate typed submissions against the input contract before enqueue
- [ ] 6.3 — Deliver envelope-shaped results to third-party clients
- [ ] 6.4 — Extend decision-tool schema resolution to the expanded definition model
- [ ] 6.5 — Keep decision-tool selection read-only over the registry
- [ ] 6.6 — Bring assistant-managed data types to parity with the expanded model
- [ ] 6.7 — Backend tests for third-party submission and decision tools

### Phase 7 — Verification and hand-off

- [ ] 7.1 — Contract-matrix regression test across agent configurations
- [ ] 7.2 — Cross-surface consistency test for one result, one shape, one content type
- [ ] 7.3 — Regression suite for behaviours that must not change
- [ ] 7.4 — Structural tests for service segregation
- [ ] 7.5 — Migration and verification runbook for operators
- [ ] 7.6 — Legacy free-text schema migration notes
- [ ] 7.7 — Prepare master-doc update notes
- [ ] 7.8 — Full backend and frontend suite run

## Phase 1 — Data-type and contract schema foundation

Everything downstream reads the canonical definition, so the registry and its storage land first. Both revisions are additive; no existing column or enum value is dropped.

### 1.1 — Add the canonical definition and child-reference entity to the data-type model

Add the canonical definition column, a schema version marker, and a guided-representability flag to the data-type entity, and introduce the child-reference projection entity (parent, child, field name, list flag, tenant) with tenant-scoped uniqueness. Keep the existing field list column untouched. Add the parent/child relationships on the registry entity.

**Done when:** the ORM models import cleanly, the child-reference entity declares both foreign keys and the tenant-scoped unique constraint, and the existing field-list column is unchanged.

### 1.2 — Add result-type, input-contract, and validation-status columns to agent type, job, and output models

Extend the declared-result-type enumeration with text and JSON while keeping auto, markdown, and typed. Add the optional input data-type reference and relationship on the agent type. Add the result-type and result-validation-status columns on the session entity, a validation-status enumeration, and a result-type column on the typed output entity.

**Done when:** the models import cleanly; every new column is nullable or defaulted so the running application is unaffected before cutover; no existing enum value is removed.

### 1.3 — Generate and hand-review the structure Alembic revision

Autogenerate one structure revision on top of the current head and review it by hand: enum creation strategy, nullable/defaulted additions, the child-reference table and its constraints, the same-tenant uniqueness needed for the child composite reference, and supporting indexes for filtering by result type and validation status. Confirm the down-revision chain and write a reversible downgrade.

**Done when:** the revision file exists, its chain points at the previous head, every new enum uses a non-creating reference in the migration, and the downgrade is complete and reversible.

### 1.4 — Apply and verify the structure revision

Apply the revision to the development database and confirm the reported current revision matches the new head. Restart the Control Center service afterwards so ORM metadata is reloaded.

**Done when:** the migration status reports the new head, the service starts without schema errors, and the existing data-type, agent-type, and output list endpoints still respond successfully.

### 1.5 — Write, apply, and verify the idempotent backfill revision

Add a data-only revision that derives a canonical definition for every data type that has none, preserving field order, enum values, required flags, and description; mark the schema version and guided representability accordingly. Set the typed result type on existing output records. Leave historical session result types null so the read path applies legacy normalisation. Create no child references. Apply, then re-run to prove idempotency.

**Done when:** a second run of the backfill makes no changes, spot-checked legacy data types round-trip through the canonical definition, existing output records read as typed, and historical sessions still render.

### 1.6 — Implement the schema canonicalizer and guided-field projection module

Create a new canonicalizer module that converts between the guided field list and the canonical object schema: primitive types, enum allowed values, required flags, list markers, and one-level child references keyed by data-type identifier. It also reports whether a definition is fully guided-representable and detects drift between the canonical definition and the projection.

**Done when:** round-tripping a guided definition is lossless, a definition with an unresolvable or nested child is reported as not guided-representable rather than truncated, and drift detection reports the field-level difference.

### 1.7 — Extend data-type Pydantic schemas for canonical definitions, list flags, and child references

Extend the create, update, and response schemas with the canonical definition, an optional schema-source input mode, the list flag on a field, and a child-reference field type carrying the child identifier. Keep the existing field schema accepted so current clients and tests remain valid. Add guided-representability and expanded usage to responses.

**Done when:** existing payloads still validate unchanged, new payloads expose the canonical definition and list/child markers, and invalid combinations (child without reference, enum without values, empty field list) fail with field-specific messages.

### 1.8 — Rework the data-type write path to regenerate the projection and enforce child rules

On create and update, treat the supplied canonical definition (or the source view) as authoritative, regenerate the guided projection and the child-reference rows in the same transaction, and enforce same-tenant, one-level, and no-self-reference rules. Return the dependent parents when a child data type is edited so the caller can warn.

**Done when:** saving a definition that violates a child rule is rejected with a message naming the offending field, a valid save leaves the projection and child rows consistent with the definition, and no rejection path leaves a partially written registry row.

### 1.9 — Extend data-type delete protection and consumer listing to child references and input assignments

Block deletion when a data type is referenced as a child by a parent data type, as an input contract, as an output contract, or by a decision tool. Name the dependents in the error and in the usage response. Deleting a parent removes only its own child rows.

**Done when:** each reference class produces a distinct, named rejection; usage responses list parent data types with field names plus agent types split by input and output; the child data type survives deletion of its parent.

### 1.10 — Add the projection drift reconcile/repair path

Add a Control Center maintenance path that finds data types whose guided projection disagrees with the canonical definition and repairs them by regenerating the projection from the definition — never by trusting the projection. Report rows that legitimately have no canonical definition (pre-change rows not yet saved).

**Done when:** the check reports zero drift immediately after the backfill, a deliberately corrupted projection is detected and repaired from the definition, and the report distinguishes drift from pre-change rows.

### 1.11 — Extend the data-type REST API for canonical schema, source validation, and expanded usage

Extend the data-type routes to return the canonical definition and representability in list and detail responses, accept a source-mode definition on create and update, and add a validate-only route that parses and validates a source definition without persisting. Extend the usage flag to include parent data types and agent types split by input and output.

**Done when:** the detail response alone is enough to render both editor views, the validate-only route returns field-specific problems without writing, and the usage response drives a delete dialog without further calls.

### 1.12 — Backend tests for canonical definitions, child rules, list fields, and delete protection

Cover: primitive and enum round-trip, list on primitives and on children, one-level rejection, self-reference rejection, cross-tenant rejection, deletion blocked by a parent, by an input assignment, and by a decision tool, and the backfilled rows reading correctly.

**Done when:** the new and extended tests pass, the existing data-type API tests pass unchanged, and each rejection asserts the named dependent or offending field.

## Phase 2 — Contract resolution, legacy adapter, and agent I/O configuration

One module owns what a run's contract is; every consumer asks it rather than re-deriving from columns.

### 2.1 — Create the pure contract module with declared-result-type normalisation

Create the new contract module as pure functions and models with no database access: declared result types, normalisation of stored values to a declared result type, resolution of an agent configuration plus its data types into a contract description, and the contract invariants. This module is the single origin of contract truth for both services.

**Done when:** the module imports without any database or session dependency, resolution covers every supported combination, and an unknown or absent stored value normalises deterministically.

### 2.2 — Implement the backward-compat adapter for legacy result types and legacy schemas

In the same module, implement the only read path for legacy definitions: auto normalises to text (a markdown-looking body is not reclassified), typed with no data type normalises to text, a legacy free-text schema is surfaced as a read-only legacy contract and never enforced, and historical rows with no recorded result type fall back to the legacy behaviour.

**Done when:** every legacy state resolves to a declared result type, nothing is written back, and the adapter reports the legacy source so the UI can label it.

### 2.3 — Build the read-only contract snapshot with one-level child expansion

Produce a snapshot describing input and output contracts: declared result type, resolved JSON Schema including expanded one-level children and list markers, data-type identity and slug, schema version, and per-boundary scriptability. Snapshot construction is the only place that expands children.

**Done when:** a snapshot with a list-of-child field contains fully expanded child properties, a snapshot for an agent with no contracts contains no schema, and the same input always yields the same snapshot.

### 2.4 — Implement the scriptability classifier for boundaries and result types

Classify a declared result type as scriptable (typed, JSON) or a semantic bridge (text, markdown), with conversational turns always semantic. Expose the per-boundary verdict and a helper that answers whether a set of boundaries permits a fully-scripted claim; the binding verdict remains with plan validation.

**Done when:** classification follows the declared type only, never the payload's appearance, and legacy auto resolves through the adapter before classification.

### 2.5 — Define the envelope models for build, normalise, and validate

Define the envelope models (execution status, declared result type, payload, validation status, contract metadata, error, producer metadata) and the build/normalise entry points used by every producer. Provide a validation step that rejects business fields at envelope level and requires contract metadata consistent with the declared result type.

**Done when:** each producer path can express its outcome without adding fields to the envelope, a failed result builds a valid envelope with no payload, and an envelope carrying a business field at top level is rejected.

### 2.6 — Enforce contract invariants on the agent-type write path

Enforce on create and update: typed requires an output data type; a result type other than typed must not carry one; a non-conversational agent may declare an input data type; a conversational agent may carry neither; new configurations may not select auto. Reject with a message that names the field to change. Do not retroactively invalidate existing rows.

**Done when:** every impossible combination is unsaveable through the REST API, an existing auto row can be read and saved once it chooses an explicit value, and no legacy row becomes unsaveable without operator action.

### 2.7 — Expose the resolved contract on the agent-type read path

Return the declared result type as normalised, the input data type identity and name, the output data type identity and name, and legacy markers (legacy auto, legacy free-text schema present, not guided-representable) from the agent-type read endpoints and the management-panel serialisation.

**Done when:** the read payload alone lets the UI state the declared result type and both contracts without extra calls, and legacy markers are present for pre-change rows.

### 2.8 — Enforce conversational restrictions and retire implicit auto for new configurations

Make the agent-type form and API treat conversation as an input type only available to conversational agents, and text/markdown as the only declared result types for them. Confirm no new configuration can be created with auto, while auto remains readable.

**Done when:** conversational configurations cannot carry typed input or output through any write path, and a create request with auto is rejected with guidance.

### 2.9 — Support data-type source editing and guided-representability in the registry service

Ensure the registry service can save a definition supplied from the source view even when the guided editor cannot display it, preserving the definition and marking representability false; and can convert a guided definition into the canonical form on save. Keep "at least one field", duplicate-name, and name/slug uniqueness rules identical regardless of the input view.

**Done when:** a source-only definition saves and reloads byte-for-byte equivalent, the guided view is reported as unable to display it, and duplicate and empty-field validation behaves identically from both views.

### 2.10 — Backend tests for resolution, legacy adapter, invariants, and scriptability

Cover the resolution matrix end to end, each legacy normalisation, each invariant rejection, conversational restrictions, and the classifier's verdicts including legacy auto.

**Done when:** the matrix is fully exercised, no test asserts on stored-value rewriting, and existing agent-type API tests keep passing.

## Phase 3 — Envelope on every execution path

The envelope is only real when every producer builds it and every consumer reads it; this phase migrates them together.

### 3.1 — Return the contract snapshot from the internal agent-context endpoint

Add the resolved contract snapshot to the internal execution-context response, replacing the current separate output-type, output-schema, data-type, and prompt fields with a single contract block plus deprecated aliases kept populated for one release. The endpoint continues to be served only by Control Center over the internal certificate and signed tenant headers.

**Done when:** Agent Runtime can execute with the snapshot alone, the deprecated aliases still carry their previous values, and the snapshot contains no identity tokens, credentials, or provider secrets.

### 3.2 — Build the envelope after the Agent Runtime LLM loop

Replace path-specific output extraction with one normalisation step that takes the raw outcome, the resolved contract, and the producer metadata and returns the envelope. Guardrail usage, session identifiers, and model identifiers move to producer metadata; they are no longer merged into the result payload.

**Done when:** an LLM run with a text, markdown, JSON, or typed result produces the same envelope shape; business fields appear only inside the payload; and structured-output and plain-text runs are distinguishable only by content, not by envelope shape.

### 3.3 — Drive typed persistence from the envelope and stop flattening business fields

Persist the typed output record from the envelope payload, record the validation status on both the envelope and the output record, and keep the raw fallback on validation failure. Remove the behaviour that copies business fields to the top level of the stored output; keep only the envelope and the typed output link.

**Done when:** a typed run yields one typed output record and an envelope whose contract names the data type, a validation failure still completes the run with a recorded verdict and raw fallback, and no business field appears beside the envelope.

### 3.4 — Derive provider structured-output and schema prompts from the resolved contract

Build the provider structured-output schema and the system-prompt schema block from the resolved output contract rather than from the stored field list, including expanded one-level children and list markers, and keep the thinking-mode fallback that injects the schema block into the system instruction.

**Done when:** a typed agent with a list-of-child field sends an accurate provider schema, a thinking-mode model still receives the prompt-based schema block, and text/markdown/JSON agents send no structured-output schema.

### 3.5 — Add step-contract checking to the fully-scripted dispatch path

Give script steps a declared input and output contract, check each step result against its contract, and treat a mismatch as the enumerated fallback trigger that routes to the LLM path — not as a run failure. Build the session envelope from the final script result and persist it through the same completion path as the LLM run.

**Done when:** a matching script produces a success envelope with a scripted producer path, a mismatched step result produces a recorded fallback reason and an LLM-produced envelope, and the session never fails solely because a contract mismatched.

### 3.6 — Carry the envelope and declared result type through delegation hand-offs

Validate the delegated input against the child's resolved input contract in Control Center before the delegated step is dispatched, rejecting with field-level errors instead of starting a child run. Return the child envelope, including the declared result type and contract metadata, to the parent instead of a bare JSON dump of the child output. Record the declared result type on the delegation status event so the parent and optimizer can classify the boundary without inspecting the payload.

**Done when:** a delegated markdown result reaches the parent with a markdown declared type, a delegated typed result reaches it with the data type identity, a delegated input that violates the child's contract starts no child execution and names the offending field, and existing delegation logging and token accounting are unchanged.

### 3.7 — Keep the Communication Hub a pass-through for envelope results

Carry the envelope unchanged through the delegation wait and result relay, including on failure, so the parent always receives the same shape. The hub gains no interpretation of payload or contract and stores nothing.

**Done when:** the relayed result is byte-identical to what the child persisted, a failed child yields a failed envelope rather than a differently shaped error, and the hub holds no contract or payload state.

### 3.8 — Persist envelope facts on session completion in Control Center

Accept and persist the declared result type and validation status alongside the payload on both completion endpoints, keeping the existing terminal-state guards, output-id extraction, stop-field handling, and hub dispatch. Retain the payload in the existing output column as the envelope payload.

**Done when:** a completed session rows carry the declared result type and validation status, the operator-termination guard still refuses a late completion, and existing clients that send only a payload still complete (with the type resolved at read time).

### 3.9 — Derive one content type per result in the result repository

Derive the stored content type from the declared result type rather than from the agent type's stored output type, so a typed or JSON result is JSON in every surface and a text result is text. Populate the repository from the envelope payload.

**Done when:** the same result shows one content type in the execution log, the repository, and exports; and a legacy auto agent's result is stored as text.

### 3.10 — Persist envelopes for failed and terminated runs

Record a failed-run envelope: failure status, declared result type, no payload, error message and category, and the retained contract identity. Do not alter the existing stop-category/stop-reason semantics or the operator-termination attribution.

**Done when:** a failed run reads back with a declared result type and an error rather than an empty result, a terminated run keeps its attribution, and no failure path synthesises a payload.

### 3.11 — Build internal-only envelopes for conversational turns and failures

Build the envelope for conversational turns (result type text or markdown) and for failed turns, and record it in logs and diagnostics only. Do not change the chat surface, the retry behaviour, or the persisted activity states.

**Done when:** logs show one envelope per conversational turn including failures, the chat error surface is unchanged, and conversation durability behaviour is untouched.

### 3.12 — Return envelopes from the result, output, and execution-log read paths

Return the envelope from session result reads, typed-output reads, execution-log detail, and the management-panel serialisation, with the declared result type and validation status surfaced as first-class fields so lists can filter on them.

**Done when:** every read surface returns the same status, result type, and payload for the same result, and filters on result type and validation status work without parsing the payload.

### 3.13 — Backward-compat read adapter for historical rows and results

For rows with no recorded result type or validation status, resolve through the legacy adapter at read time: auto becomes text, typed without a data type becomes text, and pre-change typed outputs read as typed. Never rewrite stored history and never revalidate it.

**Done when:** a pre-change row renders exactly as before with a declared type shown, no historical payload changes, and no retroactive validation runs during a read.

## Phase 4 — Optimization integration

Optimization must stop guessing: it receives the reference result and contract, and Control Center owns the verdict.

### 4.1 — Expose the reference result and declared contract from the execution-log tool

Add the reference execution's envelope payload, declared result type, and resolved contract to the execution-log response alongside the existing input, input schema, tool-call transcript, and text log. Keep command runs excluded from reference selection and keep the existing limits.

**Done when:** the optimizer can read the actual result and the contract that produced it, the input and transcript fields keep their current shape, and no reference run is a command run.

### 4.2 — Validate step contracts when an optimized plan is generated

Validate every authored step's declared input and output contract, and every hand-off, before persisting the plan. Reject with a structured error naming the step and the offending boundary. Keep the existing status allow-list and terminal-status rules.

**Done when:** a plan with an undeclared or inconsistent step contract is rejected with a step-specific message, a valid plan persists unchanged, and `requires_fix` remains settable only by the execution-fallback path.

### 4.3 — Reject fully-scripted claims across text or markdown boundaries

Make plan validation the binding authority: a fully-scripted claim is rejected when any step or hand-off boundary resolves to text or markdown through the adapter. Accept the claim only when every boundary is typed or JSON.

**Done when:** a workflow with a delegated markdown boundary can never persist a fully-scripted claim, an all-typed workflow can, and the rejection message states which boundary forced the verdict.

### 4.4 — Check the result contract during script replay verification

Extend replay verification to check the script's produced result against the declared output contract, in addition to the existing tool-name and input-context checks, and return field-level mismatches so the optimizer can repair the script.

**Done when:** a script that produces a wrongly shaped result fails verification with a contract mismatch, a correct script still verifies, and replay remains replay-only with no live tool calls.

### 4.5 — Resolve script input validation from the input contract, not the legacy schema

Resolve the required input keys from the agent's input data type (falling back to the legacy schema only when no data type is assigned), including one-level child structures and lists, so the replay context must match the real contract.

**Done when:** a script authored against renamed input keys is rejected with the real required keys, an agent with no input contract is unaffected, and the legacy fallback still validates pre-change agents.

### 4.6 — Record the declared result type per step and per hand-off in plan payloads

Persist the declared result type with each authored step and each delegated hand-off inside the existing plan payload, so a plan review can distinguish parseable boundaries from semantic ones without re-resolving the agent type.

**Done when:** stored plans carry per-step declared types, an older plan without them still loads and resolves at read time, and no new plan entity or column is introduced.

### 4.7 — Update optimizer mission and mode prompts with contract guidance

Teach the optimizer, in mission text only, that typed and JSON boundaries are scriptable, markdown and text boundaries require a model, and it must reason from the reference result and contract rather than assuming a final format. Do not change when optimization is offered or approved.

**Done when:** the guidance is present in both the command mission and the optimization-mode conversation rules, no trigger or approval rule changed, and no prompt instructs the optimizer to declare scriptability itself.

### 4.8 — Tests for verdicts, step-contract rejection, and reference-result exposure

Cover: all-typed fully-scripted acceptance, markdown boundary rejection, delegation hand-off classification, reference result exposure, replay contract mismatch, and legacy plan read compatibility.

**Done when:** each scenario has a focused test, and existing optimization and script tests pass.

## Phase 5 — Frontend

UI work follows the approved prototype flows: data types (guided + source), in-dialog contract preview, structured input, envelope-backed results.

### 5.1 — Extend frontend types for result types, input contracts, canonical schemas, and child references

Extend the shared types with the four declared result types, the input data-type assignment, the canonical definition, guided representability, list flags, child references, result validation status, and envelope fields on sessions and results. Keep the legacy types readable so existing components compile.

**Done when:** type checking passes, legacy auto remains a permitted read value, and no component needs an ad-hoc cast to read the new fields.

### 5.2 — Extend the data-type hooks for new payload fields and invalidation

Extend the data-type query and mutation hooks to send the canonical definition and source mode, and to invalidate not only the data-type queries but also agent-type queries (contract previews and forms) and decision-tool queries, since all three display the same definition.

**Done when:** saving a data type refreshes the registry, any open agent-type contract preview, and decision-tool selections without a page reload.

### 5.3 — Extend the data-types page with consumers, agent usage, and legacy markers

Show, per data type, how many fields it defines, which parent data types reference it (with field names and list markers), how many agent types use it, and a legacy marker for registry rows that still carry a free-text schema. Add the empty-registry state with guidance toward creating a contract.

**Done when:** the list is accurate for a data type used as a child and as an output contract simultaneously, and a legacy row is visibly marked as readable rather than migrated.

### 5.4 — Add guided and schema-source tabs to the data-type editor

Add two tabs over one definition: guided fields with a live resolved-schema preview, and a source view that can be pasted into and copied from. Switching views keeps the definition; the source view is generated from the guided state until it is edited.

**Done when:** switching tabs repeatedly never changes the stored definition, the preview updates as fields change, and the same save path is used from both tabs.

### 5.5 — Add child data-type selection with one-level constraints

Add the child data-type field type with a picker that excludes the current data type, excludes candidates that already reference a child, and disables the child option on a data type that is itself used as a child — with an inline explanation of why an option is unavailable.

**Done when:** an invalid one-level selection cannot be made through the UI, the disabled reasons are visible, and the API's rejection is also rendered if it occurs.

### 5.6 — Add the per-field list toggle and keep the enum editor consistent

Add a list toggle on every field row, primitive and child, and ensure the enum value editor, required flag, ordering controls, and duplicate-name validation behave identically for list and non-list fields.

**Done when:** a list of primitives and a list of children both round-trip through save and reload, and duplicate or empty-field validation is unchanged.

### 5.7 — Handle source-only definitions without silent loss

When the source definition cannot be displayed by the guided view, keep it, block guided editing of that part, and state that the guided view cannot fully display the definition. Offer an explicit action to discard the source edit and reload the last guided definition. Reject definitions the product cannot represent with a message pointing at the specific field.

**Done when:** no tab switch discards content, a nested or unsupported definition is rejected on save with a specific message, and the user can always see which definition will be saved.

### 5.8 — Show consumer warnings and blocked deletion with named dependents

Warn before saving a data type that has consumers, naming each consumer and whether the data type is used as a child. In the delete dialog, list the dependents and disable deletion, distinguishing parent data types from agent types and decision tools. Keep the existing confirm-before-delete behaviour for unreferenced data types.

**Done when:** a referenced data type cannot be deleted from the UI, the dialog names every dependent, and an unreferenced delete still behaves as today.

### 5.9 — Add the input contract slot and explicit result type to the agent type form

Replace the free-text input schema with an input contract selection (none, typed with a data type, conversation for conversational agents only) and an explicit declared result type (text, markdown, JSON, typed). Disable the output data-type selector unless typed is chosen, clear it when the result type changes away from typed, and show inline validation for missing contracts.

**Done when:** no combination the API rejects can be submitted, the result type is always explicit for new and edited agents, and a legacy auto agent opens with text selected and a legacy note.

### 5.10 — Add read-only input and output schema preview inside the agent type dialog

Show a collapsed-by-default preview of the selected input and output contract: field names, types, allowed values, required markers, list markers, and child fields expanded one level. Update immediately when the selection changes; offer no edit path and no navigation.

**Done when:** the preview matches the registry for a list-of-child contract, it updates on selection change, and the dialog needs no extra navigation to confirm a contract.

### 5.11 — Build the structured input form for agents with an input data type

Generate a form from the input contract: type-appropriate controls for dates, numbers, and booleans; enum fields limited to allowed values; child fields as a nested group; list fields as repeatable rows with add and remove. Indicate required fields, show field-level messages, and do not start the run while the form is invalid. Keep the free-prompt form for agents with no input contract and leave conversational entry unchanged.

**Done when:** a request with a list of passengers is entered as rows rather than a delimited string, an incomplete submission starts nothing and shows field-level messages, and agents without an input contract are visually unchanged.

### 5.12 — Render results from the envelope with a visible result type

Render from the envelope: execution status, declared result type, payload, validation status, and contract identity, with a type badge on every result. Typed payloads render structurally, JSON payloads as JSON, markdown as markdown, and text as text — the same format the API returned. On validation failure show the recorded verdict with the raw fallback; on failure show the error and no payload.

**Done when:** the same result looks identical in the execution log and the repository, the declared type is always visible, and no render path branches on the agent type's stored output type.

### 5.13 — Show result type and validation status in the repository and outputs pages

Add result-type and validation-status columns and filters to the result repository and the agent outputs page, and carry the same fields into the output detail drawer and CSV export.

**Done when:** results can be filtered by declared type and validation outcome without parsing payloads, and the export carries both columns.

### 5.14 — Present legacy agents and legacy results in the new vocabulary

Label agents whose stored value is auto as text with a legacy note, show a read-only legacy definition where a free-text schema still exists, and render pre-change results with their declared type resolved by the backend rather than by client-side guessing.

**Done when:** no screen shows auto as a selectable or current result type for a new configuration, legacy agents remain editable, and legacy results render without being reinterpreted.

### 5.15 — Frontend tests for the editor, contract form, structured input, and rendering

Cover: guided/source round-trip, source-only definition handling, child constraint disabling, list rendering, agent-type invariant validation, preview refresh on selection change, structured input validation and repeatable rows, envelope rendering for each result type, validation-failure fallback, and failed-run rendering.

**Done when:** the new and extended tests pass and existing page tests for these screens keep passing.

## Phase 6 — Third-party and decision-tool parity

Outside consumers must see the same contract and the same result shape as in-product runs.

### 6.1 — Expose the input contract to integration clients

Return the resolved input contract (data type identity, slug, resolved schema, and whether structured input is required) from the integration client configuration response so a client can render or validate input before submitting.

**Done when:** a client can determine the required input shape without an authenticated management call, and an agent with no input contract reports that clearly.

### 6.2 — Validate typed submissions against the input contract before enqueue

Validate the submitted input against the agent's input data type in Control Center before the session is enqueued, returning field-level errors and starting no execution. Keep the existing credential classes, origin allowlist, rate limiting, and non-conversational restriction unchanged.

**Done when:** invalid input is rejected with field-level messages and no session row, valid input enqueues exactly as today, and an agent with no input contract accepts the same payloads it accepts today.

### 6.3 — Deliver envelope-shaped results to third-party clients

Return the envelope (status, declared result type, payload, validation status, error) from the client session-poll endpoint, using the same normalisation as the in-product read path so a text result is text and a typed result is JSON everywhere.

**Done when:** a client receives the same shape and the same result type the product shows for the same session, and an in-flight session still polls successfully.

### 6.4 — Extend decision-tool schema resolution to the expanded definition model

Resolve decision-tool input and output schemas from the canonical definition so list fields and one-level child references are honoured in the tool contract and in result rendering.

**Done when:** a decision tool selecting a list-of-child data type receives an accurate schema, and existing simple data types are unaffected.

### 6.5 — Keep decision-tool selection read-only over the registry

Confirm and test that decision tools still select registry entries only: no ad-hoc schema authoring, no cross-tenant reference, and the same permission checks. Deletion protection must name decision tools as dependents.

**Done when:** a decision tool cannot be saved with an inline schema, cannot reference another tenant's data type, and blocking deletion names it.

### 6.6 — Bring assistant-managed data types to parity with the expanded model

Extend the assistant-managed data-type create/update capability to accept the canonical definition, list flags, and child references, returning structured, actionable validation errors the assistant can correct on retry. Keep the canonical preview-and-approval intervention and the prohibition on deletion.

**Done when:** a data type with a child list can be created conversationally at parity with the form, an invalid definition returns correctable field-level errors, and deletion remains unavailable.

### 6.7 — Backend tests for third-party submission and decision tools

Cover: input contract exposure, invalid submit rejection with no session, envelope-shaped poll response, decision-tool schema with a child list, cross-tenant rejection, and assistant parity.

**Done when:** every scenario has a focused test and existing integration-gateway and decision-tool tests pass.

## Phase 7 — Verification and hand-off

### 7.1 — Contract-matrix regression test across agent configurations

Exercise the full configuration matrix (input type × declared result type × data type presence, plus conversational and legacy states) through the API, asserting the allowed/rejected outcome and the resulting envelope for each allowed case.

**Done when:** every cell of the resolution matrix has an asserted expectation and no matrix combination is untested.

### 7.2 — Cross-surface consistency test for one result, one shape, one content type

For a handful of representative results (typed valid, typed validation failure, JSON, markdown delegated, text legacy, failed), assert that the execution log, result repository, delegation hand-off, third-party poll, and export all report the same status, declared result type, and payload format.

**Done when:** the test fails if any surface diverges on status, type, or payload format.

### 7.3 — Regression suite for behaviours that must not change

Run and where needed extend the suites for guardrails and the repeated-call loop, sandboxing and script lifecycle, execution preference and fallback, optimization triggers and live-test approval, conversation turn durability, tenant isolation, and permissions.

**Done when:** all listed suites pass without modification to their asserted semantics, and any test change is limited to fixture data shaped by the new contract.

### 7.4 — Structural tests for service segregation

Assert that Agent Runtime and Communication Hub perform no database access, that contract resolution lives in Control Center, that internal endpoints require the service certificate plus signed tenant headers, and that the hub does not interpret envelope payloads.

**Done when:** the structural assertions exist and pass, including a check that the new contract module has no datastore dependency.

### 7.5 — Migration and verification runbook for operators

Document, in the change folder, the ordered deployment steps: structure revision, backfill revision, verification queries (as described checks, not scripts), the expected post-migration state, how to confirm the projection is consistent, and how to roll back each revision independently.

**Done when:** an operator can execute and verify the upgrade from the documented steps alone, and the rollback path is explicit for both revisions.

### 7.6 — Legacy free-text schema migration notes

Write the operator-facing notes: which legacy rows remain readable, why an automatic conversion is not attempted when it would not be faithful, what the read-only legacy marker means, and the recommended manual path for converting a legacy definition into a data type — with no review queue or approval step introduced.

**Done when:** every legacy state named in the data model has a documented operator action or an explicit "no action needed" statement.

### 7.7 — Prepare master-doc update notes

Collect the master-doc deltas produced by this change (architecture, data model, product features, UX, QA, technology) into a hand-off note so the master-update stage needs no re-derivation. Do not edit master docs in this change.

**Done when:** each master file named in `architecture.md`, `data-model.md`, and `spec-change.md` has a corresponding note with the specific change required.

### 7.8 — Full backend and frontend suite run

Run the complete backend test suite and the complete frontend test suite, then confirm the services start cleanly with the migrated schema and a representative typed, scripted, delegated, conversational, and failed run each render correctly in the UI.

**Done when:** both suites are green, all services start without schema errors, and the five representative runs show one envelope shape with a visible declared result type.

## Completion Checklist

- [ ] Every task in Phases 1–7 is complete and its done condition is demonstrated
- [ ] Both Alembic revisions are applied, verified, and reversible; the backfill is idempotent
- [ ] No existing column, enum value, data type, agent type, or recorded result was dropped or rewritten
- [ ] Legacy auto, legacy typed-without-data-type, and legacy free-text schemas remain readable everywhere
- [ ] One envelope shape is produced by LLM, fully-scripted, delegated, conversational, and failed paths
- [ ] Declared result type is persisted per execution and visible on every result surface
- [ ] Typed requires a data type and a data type requires typed, enforced on save only
- [ ] Child data types are one level, same-tenant, and protected from deletion with named dependents
- [ ] Plan validation is the only authority for a fully-scripted claim
- [ ] Agent Runtime holds no datastore access; Communication Hub stays transport-only
- [ ] Backend and frontend suites are green, including structural and cross-surface tests
- [ ] Migration runbook and legacy migration notes are written
- [ ] Master-doc update notes are prepared for the next stage
