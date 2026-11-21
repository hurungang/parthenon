# Test Plan: Unified Agent I/O Contract

**Change**: `unified-agent-io-contract`
**Date**: 2026-11-21
**Status**: Planned — no layer executed yet
**Scope**: `has_db_changes: true`, `has_ui_changes: true`, `has_architecture_changes: true`
**Sources**: [`prd.md`](prd.md) · [`tech-spec.md`](tech-spec.md) · [`data-model.md`](data-model.md) · [`implementation-plan.md`](implementation-plan.md) · [`architecture.md`](architecture.md)

---

## 1. Test Strategy

This change replaces five path-specific result shapes with one **Agent Result Envelope** and makes the registry data type the single input/output contract. The risk is not one broken feature but **asymmetric migration**: one producer, consumer, or surface still inventing its own shape while the rest read the envelope.

Three seams carry most of the risk and therefore most of the test weight:

1. **Resolution seam** — stored configuration (explicit, legacy `auto`, legacy `typed`-without-data-type, legacy free-text schema) must resolve to exactly one declared result type, deterministically, without rewriting stored values.
2. **Producer/consumer seam** — LLM, fully-scripted, delegated, conversational, and failed paths must all emit the same envelope, and execution log, result repository, delegation hand-off, export, and third-party poll must all report the same status, result type, and payload.
3. **Schema-truth seam** — the canonical definition is authoritative, `fields` is a regenerated projection, child references are a regenerated projection, and the source view, guided view, preview, validation, and rendering must never disagree.

Testing is **assertion-first on observable outcomes**: a passing test must name the envelope field value, the rendered artefact, the HTTP status/field error, or the database row that proves the claim. Tests that only assert "the dialog renders" are not acceptable for this change.

### Test Layers

| Layer | Framework | Location | Covers | Bar |
|---|---|---|---|---|
| Backend unit — pure contract | pytest | `backend/tests/unit/` | Declared-type normalisation, legacy adapter, snapshot expansion, envelope build/normalise/validate, boundary classification, invariants, canonicalizer round-trip, drift detection, child-rule validation | 100% pass; each legacy state and each invariant has a dedicated assertion |
| Backend API / service | pytest + in-process app + test DB | `backend/tests/`, `backend/tests/api/` | Data-type CRUD/child/delete/source routes, agent-type create/update invariants, results and outputs read paths, internal session status/result endpoints, optimization tools, integration-gateway submit/poll | 100% pass; every rejection asserts the named field/dependent |
| Backend integration (real stack) | pytest + Postgres + services | `backend/tests/integration/`, `backend/tests/communication_hub/`, `backend/tests/agent_runtime/` | Envelope persistence, delegation relay, cross-surface consistency, tenant fail-closed, script replay contract checks | 100% pass; stack-dependent suites may skip only when services are absent, and the skip is reported |
| Backend DB / migration | pytest + real Postgres | `backend/tests/db/` | `information_schema` assertions, enum values, nullability, FK and tenant-scoped uniqueness, negative constraint inserts, backfill idempotency, downgrade/upgrade | 100% pass against real Postgres; skipped (reported) only if no Postgres is reachable |
| Frontend unit / component | Vitest + RTL | `frontend/src/__tests__/` | Contract utilities, editor tabs, source validation surface, child/list controls, agent-type invariants, contract preview, structured input, envelope rendering, result-type chip, filters/export | 100% pass; JSON reporter used (see §6) |
| E2E mocked | Playwright | `e2e/tests/` | Operator flows end to end over `page.route()` mocks: registry authoring, agent config, structured launch, result rendering | 100% pass |
| E2E real backend | Playwright | `e2e/tests/*.real-backend.spec.ts` | At least one unmocked typed-submit → typed-result journey and one legacy-result render against the migrated database | 100% pass when the stack and token are provided; skip is reported, not silently accepted |
| Manual / exploratory | — | — | Cross-service delegated typed run, optimizer conversation about a markdown boundary, legacy agent edit, large passenger list | Operator sign-off recorded in the test report |

### Test Data and Isolation Rules

- Identifiable prefixes: `e2e-dt-<timestamp>`, `e2e-agent-<timestamp>`, `e2e-child-<timestamp>`; every scenario that writes cleans up (delete or roll back) and the cleanup is asserted, not assumed.
- Two tenants are required for every isolation scenario: a default root tenant plus a second tenant created by the fixture. Cross-tenant assertions use the second tenant's identifiers against the first tenant's session.
- No test may assert on a stored value being rewritten. Legacy assertions compare pre-read and post-read stored values and expect **equality**.
- Existing suites that seed data types or agent types are extended with new fields only; their asserted semantics are not changed (except where the PRD deliberately retires implicit `auto` for new configurations).

---

## 2. Coverage Areas

### 2.1 Contract resolution and legacy adaptation

| Area | Why it is critical | What the tests must prove |
|---|---|---|
| Declared result type resolution | Every result must have exactly one declared type; a second inference path would recreate the original bug | Four explicit types resolve unchanged; unknown/absent values normalise deterministically |
| Legacy `auto` | Existing agents must keep working with no operator action | Resolves to `text`; a markdown-looking body is **not** reclassified; an attached data type is surfaced as legacy and not enforced |
| Legacy `typed` without data type | Pre-existing invalid state must stay readable | Resolves to `text` on read; no write-back; row becomes saveable once an explicit value is chosen |
| Legacy free-text schemas | No definition may be lost; enforcement must stop | `contract.source = legacy_schema`; may inform the prompt; never sent as provider structured output; never validated against |
| Conversational restriction | Turns are semantic bridges, never typed boundaries | Only conversation input; `typed` rejected; selector not offered |

### 2.2 Envelope producers

| Producer | Why it is critical | What the tests must prove |
|---|---|---|
| LLM loop (text/markdown/json/typed) | The most common path and the one that previously flattened business fields | Same envelope keys for all four types; business fields only inside payload; telemetry in `producer.telemetry`, never in payload |
| Typed persistence | Validation status and typed record must agree with the envelope | One typed output row, `typed_output_id` linked, `validation_status` identical on envelope and row, raw fallback retained on failure |
| Fully-scripted dispatch | Script contract mismatch must never fail a run | Match → success envelope with `producer.path = fully_scripted`; mismatch → recorded fallback + LLM envelope, run completed |
| Delegation | The parent must be able to classify the boundary without parsing | Child envelope and declared type reach the parent; child input validated before dispatch; failure relayed as a failed envelope |
| Conversational turn | Chat UX must not change | One internal envelope per turn, including failures, visible in logs/diagnostics only |
| Failure/termination | Errors must be envelope-shaped, not differently shaped | No payload; readable `error.message`; `category`/`stop_reason` retained; termination attribution unchanged |

### 2.3 Envelope consumers and cross-surface consistency

| Consumer | Why it is critical | What the tests must prove |
|---|---|---|
| Execution log result tab | Operator's primary read surface | Renders status, result type, payload, validation verdict; failed run shows reason and no payload |
| Result repository + agent outputs | Two lists that previously inferred type independently | Same status/type/payload; filters on type and validation status work without payload parsing; CSV export carries both columns |
| Delegation hand-off | Parent and optimizer classify from here | Declared type present; payload format matches the child's declared type |
| Third-party poll | Integrators must see product parity | Same envelope, same format, same vocabulary; in-flight polling still succeeds |
| Session result read API | The canonical persisted read | Envelope fields are first-class, not derived client-side |

### 2.4 Data type registry — canonical schema, child references, lists, source view

| Area | Why it is critical | What the tests must prove |
|---|---|---|
| Canonical definition ↔ projection | Two definitions disagreeing is the central data-integrity risk | Guided → canonical → guided round-trip is lossless; `fields` is regenerated on save; drift detection reports field-level differences and repair regenerates from the definition |
| Child reference (single + list) | The passenger-list use case | Child rows created with field name and list flag; expansion yields child properties in the resolved schema; two fields may reference the same child |
| One-level rule | Keeps schemas reviewable; prevents unbounded nesting | Child that already has children is rejected; a data type already used as a child cannot gain children; message names the field |
| Self-reference / cycles | The only expressible cycle | Rejected on save with a specific message |
| Same-tenant rule | Tenant isolation is non-negotiable | Cross-tenant child rejected by the application rule and by the composite reference |
| Delete protection | Silent deletion would orphan parents and agents | 409 names parent data types + field names, input agent types, output agent types, and decision tools; unreferenced delete still succeeds |
| Parent deletion / rename survival | References are keyed by id | Deleting a parent removes only its own child rows; renaming a child leaves parents resolving unchanged |
| Guided ↔ source views | The PRD's explicit no-silent-loss requirement | Same save path; switching tabs never mutates the draft; unrepresentable definitions preserved and flagged; invalid source rejected with a field path |
| List on primitives and children | Explicit PRD requirement | List flag round-trips for both; enum editor/required/order behave identically on list fields |

### 2.5 Agent type configuration invariants

- `typed` requires an output data type; a non-typed result type must not carry one.
- Input data type is allowed only on non-conversational agent types; conversational agents carry neither.
- New and edited configurations cannot select `auto`; legacy rows remain readable and editable once an explicit value is chosen.
- Rejections name the field to change and are enforced identically on REST, assistant-managed, and form paths.
- Invariants are enforced on save only — no legacy row becomes unsaveable without operator action.
- A data-type edit propagates to every display surface (dialog preview, decision tools, result rendering) on next load without re-entry and without a page reload.

### 2.6 Structured input

- Form generated from the input contract, replacing the single free-text field only when an input data type exists.
- Nested child group, repeatable list rows with add/remove, enum choice control, date/number/boolean controls.
- Required-field enforcement with field-level messages and **no run started** on invalid input (client and server).
- Free-prompt and conversational entry unchanged.
- The server remains authoritative: a client that bypasses pre-validation still cannot start a run.

### 2.7 Optimization verdicts

- `get_execution_log` exposes the reference result and its resolved contract; command runs stay excluded.
- `generate_optimized_plan` validates every step and hand-off contract and is the **only** authority for `fully_scripted`.
- A `text`/`markdown` boundary (including legacy `auto`) always rejects a fully-scripted claim, and the rejection names the boundary.
- All-`typed`/`json` workflow accepts the claim and persists per-step declared types.
- Replay verification checks the produced result against the output contract and remains replay-only.
- Script input requirements resolve from the input contract, with legacy schema fallback only when no data type is assigned.

### 2.8 Compatibility and migration

- Both revisions apply in order on head `7b1e4c2d9f03`; the backfill is idempotent; downgrade/upgrade is reversible.
- No column, enum value, definition, or result is dropped or rewritten.
- Historical session rows (null result type/validation status) render exactly as before with a resolved declared type shown.
- Historical typed outputs read as `typed` with their original verdict; verdicts are never recomputed.
- Legacy data types with only `fields` read correctly and gain a canonical definition on first save.
- Legacy plan payloads without per-step declared types still load and resolve at read time.
- Legacy free-text schema migration notes exist; no review queue or approval gate is introduced.

### 2.9 Tenant isolation and service segregation

- Foreign identifiers are reference errors, not lookup misses or silent nulls.
- Contract snapshots are built only from rows resolved in the calling tenant.
- Internal envelope/validation/persistence endpoints fail closed without the signed tenant header set.
- Agent Runtime and Communication Hub gain no database access; the hub interprets no payload; the contract module has no datastore dependency.
- Result, repository, export, and third-party reads are tenant-scoped and cannot cross tenants.

---

## 3. Critical Scenarios

Scenario IDs are referenced by §5. All are WHEN/THEN; no implementation steps.

### A. Contract resolution (S1–S6)

- **S1 — typed LLM run.** **WHEN** an agent type declares `typed` with an output data type whose definition includes a list-of-child field, and a run produces a matching payload, **THEN** the envelope reports `result_type = typed`, `validation_status = valid`, `contract.source = data_type` with the data type id/slug/name and schema version, the payload contains the business fields only, and one typed output record is linked by `contract.typed_output_id`.
- **S2 — legacy `auto`.** **WHEN** a stored legacy row with `output_type = auto` runs and produces a markdown-looking body, **THEN** the envelope reports `result_type = text`, `validation_status = not_applicable`, the body is rendered as text (not markdown, not JSON), any attached data type is labelled legacy and not enforced, and the stored `auto` value is unchanged after the read.
- **S3 — legacy `typed` without data type.** **WHEN** a pre-change row stores `typed` with no output data type, **THEN** reads resolve `result_type = text`, the agent type detail opens without error and reports the legacy marker, and saving is possible only after an explicit result type is chosen.
- **S4 — legacy free-text schema.** **WHEN** an agent type has `input_schema`/`output_schema` and no data type, **THEN** the resolved contract reports `contract.source = legacy_schema`, no structured-output schema is sent to the provider, no payload is validated against it, and the stored schema is byte-identical before and after the run.
- **S5 — conversational agent.** **WHEN** a conversational agent is configured and a turn runs, **THEN** only `text`, `markdown`, or `json` can be stored, `typed` selection is unavailable and rejected by every write path, and the turn is classified as a non-scriptable boundary.
- **S6 — unresolvable assignment.** **WHEN** an agent type references a data type that does not exist in the calling tenant, **THEN** the read/validation reports a reference error naming the identifier rather than returning a null contract, and no envelope is built from the missing contract.

### B. Envelope producers (S7–S17)

- **S7 — typed run renders once.** **WHEN** a typed run completes with a valid payload, **THEN** the execution log and result repository render the payload structurally exactly once (no double-encoded JSON string, no duplicated copy beside the envelope), with a single visible result-type badge and a validated verdict.
- **S8 — text run.** **WHEN** a `text` agent completes, **THEN** the envelope carries a string payload, `validation_status = not_applicable`, and the stored result content type is text in the log, repository, delegation hand-off, and export.
- **S9 — JSON run without a data type.** **WHEN** a `json` agent with no data type completes, **THEN** the payload is an object, `validation_status = not_applicable`, and every surface renders it as JSON (not text, not typed).
- **S10 — matching fully-scripted run.** **WHEN** every script step result matches its declared step contract and the final result matches the agent's declared type, **THEN** the envelope reports `producer.path = fully_scripted`, success status, the script version id, and business fields appear only in the payload.
- **S11 — scripted contract mismatch.** **WHEN** a script step produces a result that does not match its declared contract, **THEN** the run records an explicit fallback reason, routes to the LLM path, ends `completed` (not `failed`) with an LLM-produced envelope, and the mismatch reason is visible in the execution record.
- **S12 — delegated markdown child.** **WHEN** an agent delegates to a child whose declared result type is `markdown` and the child completes, **THEN** the parent receives the child envelope with `result_type = markdown` and a readable markdown payload, the hand-off records that declared type, and the optimizer refuses a `fully_scripted` claim across that boundary.
- **S13 — delegated typed child.** **WHEN** an agent delegates to a child declared `typed` with a data type, **THEN** the parent hand-off carries `result_type = typed` plus the data type identity, the boundary classifies as scriptable, and an otherwise all-typed plan may claim `fully_scripted`.
- **S14 — failed and terminated runs.** **WHEN** a run fails (provider error, guardrail stop, script failure, timeout, internal error) or is terminated, **THEN** the result is an envelope with the failure/terminated status, a readable `error.message`, the matching `error.category`, no payload, and — for termination — the unchanged stop reason/attribution.
- **S15 — conversational turn.** **WHEN** a conversational turn completes or fails, **THEN** exactly one internal envelope is recorded in logs/diagnostics with its declared type (and failure reason when applicable), while the chat surface shows the same message/error presentation and retry behaviour as before.
- **S16 — envelope rejects business fields.** **WHEN** a raw outcome tries to place a business field at envelope level or reuse an envelope key name, **THEN** envelope validation rejects the result and names the offending key, and the failure is surfaced as a producer defect rather than persisted as a valid result.
- **S17 — telemetry placement.** **WHEN** a run consumes guardrails, tokens, and a model identifier, **THEN** those values appear only in `producer.telemetry`, the payload contains no platform bookkeeping keys, and the payload's own fields are not renamed or flattened.

### C. Cross-surface consistency (S18–S21)

- **S18 — one shape in five places.** **WHEN** the same typed result is read from the execution log, result repository, agent-outputs page, session-result API, and third-party session poll, **THEN** all five report the same status, result type, payload content, and validation status, and any divergence fails the test.
- **S19 — validation failure fallback.** **WHEN** a typed result fails validation, **THEN** the run still completes, the envelope records `validation_status = validation_error` with field-level errors and `contract.raw_payload`, the raw result is shown as the fallback, and no typed record is presented as valid.
- **S20 — filters and export.** **WHEN** the repository and outputs page are filtered by result type and by validation status, **THEN** the filtered rows match the envelope facts without payload parsing, and the CSV export carries the same result-type and validation-status columns for those rows.
- **S21 — historical verdict stability.** **WHEN** a data type is edited after a result was recorded, **THEN** that result's recorded result type, payload, and validation verdict are unchanged on every surface and no revalidation occurs during the read.

### D. Data type registry — child, list, source (S22–S32)

- **S22 — array of child.** **WHEN** a parent data type defines a list field referencing a registered child (request → passengers: name, adult/child/infant type, bag count), **THEN** save, reload, resolved schema, guided projection, and child-reference row all express a list of that child, and the structure was created without authoring raw JSON Schema.
- **S23 — one-level rejection.** **WHEN** a data type that already references a child is selected as a child of another data type, or a child gains a child, **THEN** the save is rejected with a message naming the offending field and the reason (one level only), and no partial registry row is written.
- **S24 — self-reference.** **WHEN** a data type references itself as a child, **THEN** the save is rejected with a specific self-reference message.
- **S25 — cross-tenant child.** **WHEN** a parent references a child data type owned by another tenant, **THEN** the save is rejected naming the foreign identifier, and the foreign child is not revealed in any list/preview response.
- **S26 — delete blocked with named dependents.** **WHEN** deletion is attempted for a data type used as a child, as an input contract, as an output contract, or by a decision tool, **THEN** the response is a structured conflict naming each dependent class (parent data type + field name, agent types split input/output, decision tools), the delete dialog lists them, deletion is disabled, and nothing is deleted.
- **S27 — parent deletion and rename survival.** **WHEN** a parent data type is deleted, **THEN** only that parent's child-reference rows are removed and the child remains usable; **WHEN** the child is renamed, **THEN** existing parents still resolve to it and no parent definition is rewritten.
- **S28 — child edit affects consumers.** **WHEN** a child data type's fields are edited, **THEN** the response reports its dependent parents, the UI warns that all consumers are affected before applying, and after save the agent-type preview, decision-tool schema, and result rendering show the new shape on next load.
- **S29 — source ↔ guided consistency.** **WHEN** a definition is saved from the schema source view and reopened in the guided view, **THEN** field names, order, types, allowed values, required flags, list flags, and one-level child references are identical; **WHEN** the user switches tabs repeatedly without saving, **THEN** the stored definition and the draft are unchanged.
- **S30 — unrepresentable definition preserved.** **WHEN** a pasted source definition exceeds the guided subset (deeper nesting, unsupported type, recursive structure), **THEN** it is either preserved with a visible "guided view cannot fully display this" notice and a read-only guided state, or rejected on save with a message pointing at the specific field — never silently truncated.
- **S31 — invalid source rejected.** **WHEN** the source view or the validate-source route receives an invalid definition, **THEN** it returns field-specific problems with a path and the guided-representability verdict, and the validate-only path writes nothing.
- **S32 — list/enum/required invariants.** **WHEN** a list field is created for a primitive and for a child, **THEN** both round-trip; **WHEN** an enum field has no allowed values, a field name is duplicated, or the field list is empty, **THEN** save is rejected identically from both editor views.

### E. Agent configuration invariants (S33–S37)

- **S33 — typed without data type.** **WHEN** a create or update sets `typed` with no output data type, **THEN** the save is rejected with a message naming the output data type as the field to set, identically on REST, assistant-managed, and form paths.
- **S34 — data type on non-typed.** **WHEN** an output data type is attached while the result type is `text`, `markdown`, or `json`, **THEN** the save is rejected rather than silently converting the result type to `typed`, and the form prevents the combination while showing why.
- **S35 — conversational restrictions.** **WHEN** a conversational agent is created or updated, **THEN** `typed` and any data-type assignment are rejected, the input data-type selector is not offered, and `conversation` remains the only input type accepted.
- **S36 — auto retirement.** **WHEN** a new configuration or an edit submits `auto`, **THEN** it is rejected with guidance to choose an explicit value; **WHEN** an existing `auto` row is opened, **THEN** it displays `text` with a legacy note, no `auto` option is selected or offered, and saving with an explicit value succeeds without changing any other stored field.
- **S37 — propagation without re-entry.** **WHEN** a data type used as input and output is edited, **THEN** the agent-type dialog preview, decision-tool schema, and result rendering reflect it on next load, invalidated queries refresh without a page reload, and the agent type was not re-saved.

### F. In-dialog contract preview (S38–S39)

- **S38 — preview fidelity.** **WHEN** an agent type dialog has input and output data types selected, **THEN** each preview shows the same fields, types, allowed values, required markers, list markers, and one-level child expansion as the registry detail, and the preview is read-only with no navigation away from the dialog.
- **S39 — preview refresh.** **WHEN** the selected data type is changed in the dialog, **THEN** the preview updates immediately to the newly selected definition and the previous definition is no longer shown.

### G. Structured input (S40–S45)

- **S40 — form derivation.** **WHEN** a non-conversational agent with an input data type is launched, **THEN** the launch surface presents a structured form derived from that contract instead of a single free-text field; **WHEN** the agent has no input data type, or is conversational, **THEN** the existing free-prompt or chat entry is visually unchanged.
- **S41 — passenger rows.** **WHEN** the input contract contains a list of a child type, **THEN** each row is entered as child fields (name, passenger type, bag count) with add and remove controls, and the submitted payload contains N separate records rather than one delimited string.
- **S42 — typed controls.** **WHEN** a field is an enum, date, number, or boolean, **THEN** the form offers only allowed enum values and type-appropriate date/number/boolean controls, and an out-of-range enum value cannot be chosen.
- **S43 — required enforcement.** **WHEN** a required field or required list row is left incomplete and the operator submits, **THEN** field-level messages appear, no submission is sent, and no run starts; **WHEN** at least one adult is required by the modelled structure and only children are entered, **THEN** submission is blocked with a field-level message.
- **S44 — server authority.** **WHEN** a client bypasses the form and submits invalid input to the API, **THEN** the run is rejected with a field-level error naming the offending field and no session/execution row is created.
- **S45 — large list usability.** **WHEN** a list grows to a realistic size (for example 25 rows) with interspersed add/remove operations, **THEN** the form remains operable, the submitted payload contains exactly the rows on screen in order, and no row is duplicated or dropped.

### H. Third-party parity (S46–S48)

- **S46 — input contract exposure.** **WHEN** an integration client requests its configuration, **THEN** the response returns the resolved input contract (identity, slug, resolved schema, structured-input-required flag) for an agent with an input data type, and states clearly that no contract applies for an agent without one.
- **S47 — submit validation.** **WHEN** a third-party client submits input that violates the agent's input contract, **THEN** field-level errors are returned and no execution is enqueued; **WHEN** the input is valid, **THEN** the submission enqueues exactly as before, and credential classes, origin allowlist, rate limits, and the non-conversational restriction behave unchanged.
- **S48 — delivered envelope.** **WHEN** a third-party client polls a typed session, **THEN** the response carries the same envelope status, declared result type, payload format, and validation status as the in-product surface for that session, and an in-flight session still polls successfully.

### I. Optimization verdicts (S49–S55)

- **S49 — reference result exposure.** **WHEN** the optimizer requests the execution log for a reference run, **THEN** the response includes the run's result payload, declared result type, and resolved contract beside the existing input, schema, transcript, and text log, and command runs remain excluded from reference selection.
- **S50 — markdown boundary blocks fully scripted.** **WHEN** a plan claims `fully_scripted` while any step or hand-off resolves to `markdown` or `text`, **THEN** plan generation rejects the claim with a message naming the boundary that forced the verdict, and no plan with that claim is persisted.
- **S51 — all-typed claim accepted.** **WHEN** every step and hand-off resolves to `typed` or `json`, **THEN** the `fully_scripted` claim is accepted and the persisted plan carries the declared result type per step and per hand-off.
- **S52 — legacy auto boundary.** **WHEN** a plan boundary's agent stores legacy `auto`, **THEN** the boundary is evaluated as `text` after the adapter and a `fully_scripted` claim is rejected, proving the adapter runs before classification.
- **S53 — replay contract check.** **WHEN** replay verification runs a script whose produced result does not match the declared output contract, **THEN** verification fails with field-level mismatches; **WHEN** the result matches, **THEN** it verifies successfully; in both cases no live tool call is made.
- **S54 — script input contract.** **WHEN** a script is authored against input keys that do not match the agent's input contract, **THEN** verification rejects it and names the real required keys; **WHEN** the agent has no input contract, **THEN** the legacy schema fallback still validates it.
- **S55 — legacy plan payload.** **WHEN** a plan stored before this change (no per-step declared types) is loaded, **THEN** it loads successfully and its step types resolve at read time without a rewrite.

### J. Tenant isolation and service segregation (S56–S59)

- **S56 — assignment isolation.** **WHEN** an agent type is created or updated with a data-type identifier owned by another tenant, **THEN** the request is rejected as a reference error naming the identifier and no row is written with a foreign reference.
- **S57 — read isolation.** **WHEN** tenant B requests tenant A's data type, agent type, session result, output record, or CSV export identifier, **THEN** the response is not-found/forbidden without confirming existence, and no payload or schema leaks.
- **S58 — snapshot scoping.** **WHEN** an internal contract snapshot is requested, **THEN** it is built only from rows resolved in the calling tenant and the request fails closed (401) without the signed tenant headers.
- **S59 — structural segregation.** **WHEN** the changed modules are inspected statically, **THEN** Agent Runtime and Communication Hub contain no database session/query usage, the contract module imports no datastore, and the hub contains no payload or contract interpretation.

### K. Backward compatibility and migration (S60–S61)

- **S60 — historical results unchanged.** **WHEN** a session or typed output recorded before this change is opened after the migration, **THEN** its payload renders byte-identically to before, a declared result type is shown (resolved on read, not guessed client-side), its recorded validation verdict is unchanged, and no revalidation call is made during the read.
- **S61 — legacy definitions stay readable.** **WHEN** a data type that has only `fields` is read, **THEN** it behaves as if its definition were derived from those fields and its stored `fields` column is unchanged; **WHEN** it is saved for the first time, **THEN** it gains a canonical definition while the `fields` projection remains readable by existing consumers.

---

## 4. Edge Cases & Risks

| # | Edge case / risk | Expected behaviour | Why it matters |
|---|---|---|---|
| 1 | Canonical definition and `fields` projection drift | Definition wins; reconcile reports field-level drift and repairs by regenerating the projection | Two disagreeing definitions would make the source and guided views lie |
| 2 | Data type edited mid-run | The run uses its immutable snapshot; the change applies to the next run; no mid-run re-resolution | Otherwise a run could be validated against a schema it never received |
| 3 | Legacy free-text schema that cannot be expressed faithfully | Stays readable and non-enforcing, flagged as legacy, operator migration note explains manual review; never blocked | Compatibility-over-purity is an explicit PRD constraint |
| 4 | Same result, different content type across surfaces | One content type derived from the declared result type everywhere; typed/JSON is JSON, text is text | The original defect was one result described as text in one surface and JSON in another |
| 5 | Tenant scoping on child references and assignments | Application rule plus composite reference; foreign identifiers are errors, never nulls | A silent null would look like "no contract" rather than a misconfiguration |
| 6 | Migration ordering | Structure revision (inert, nullable/defaulted) → backfill → readers prefer canonical definition; enum values exist before any writer persists them | Out-of-order deployment would make the running application read a definition that does not exist yet |
| 7 | Migration rollback | Both migrations reversible; downgrade leaves legacy columns/values untouched; new enum values may remain unused (harmless); re-upgrade succeeds | A failed deployment must not destroy definitions or history |
| 8 | Large lists (input payload and result payload) | Validation runs once per result; list rows and array items are validated without per-field round trips; UI remains operable | A passenger-list contract is the headline use case, not an exotic case |
| 9 | Empty payload / empty list / null fields | `typed` with an empty object is validated as such; an optional empty list is valid; an empty required list is a field-level error; text/markdown may be an empty string; a failed result has no payload | Off-by-one "missing vs empty" bugs are common in envelope work |
| 10 | Failure before any payload exists | Envelope with failure status, no payload, readable reason; no surface shows an empty result as success | The old failure path returned a different shape |
| 11 | Payload that looks like a different type | A markdown-looking `text` stays text; a JSON-looking `text` stays text; a `json` result is never reclassified as typed | Classification must follow the declaration, not appearance |
| 12 | Double-encoded or duplicated payload | Typed payload rendered once, structurally; no JSON string wrapper and no second copy beside the envelope | Directly visible to the operator and a common regression when envelopes are added |
| 13 | Concurrent child delete/create race | Composite reference prevents an orphaned reference; the losing write fails cleanly with a conflict, leaving a consistent registry | The projection entity exists precisely for this |
| 14 | Partial write on save | Definition, projection, and child rows commit together or not at all; no half-written registry row on any rejection path | Data-model mitigation for the dual-write design |
| 15 | Historical rows with null result type/validation status | Resolve through the adapter on read; declared type shown; no retroactive validation; no payload change | "Zero loss on upgrade" is a business goal and an acceptance criterion |
| 16 | `auto` row with an attached data type | Reads `text`; attached data type is legacy and not enforced; not rewritten, not converted to typed | The subtle legacy state most likely to be "helpfully" migrated by mistake |
| 17 | Filters over a mix of legacy and new rows | Result-type and validation filters include legacy-resolved rows correctly and do not fail on null stored values | Lists are the operator's primary tool; null-handling bugs surface here |
| 18 | Third-party client built against the old response | Receives the envelope with the same status vocabulary; payload is the same content at the envelope payload location; format never silently changes per surface | Contract tightening must be field-level and actionable, not a breaking surprise |
| 19 | Unrepresentable source definition | Preserved and flagged, or rejected with a specific field path; never silently truncated on a tab switch or save | Explicit PRD requirement: no silent content loss |
| 20 | Contract mismatch at a script step | Fallback trigger with recorded reason; run completes on the LLM path; never a run failure | A script contract is a performance optimisation, not a correctness gate |
| 21 | Telemetry leakage | Guardrail/token/model facts in producer telemetry only; envelope-level business keys rejected | Business payloads must stay readable and collision-free |
| 22 | Deep/large source schema pasted | Rejected with the specific unsupported construct and path; guided view reports non-representability if preserved | Prevents an unbounded model from bypassing the one-level rule |

---

## 5. Acceptance Criteria Checklist

Status legend: `[ ]` planned, to be ticked when the referenced scenario passes in the named layer.

### One result shape on every execution path

- [ ] LLM, fully-scripted, delegated, conversational, and failed runs return the same envelope (status, declared result type, payload, contract metadata) — S1, S7–S17
- [ ] Business fields appear only inside the payload — S1, S7, S16, S17
- [ ] A failed run returns a failure envelope with a readable reason; failed conversational turns stay internal with the chat error surface unchanged — S14, S15
- [ ] Execution log, result repository, delegation hand-off, script result, and optimization preview show the same status/type/payload — S18, S12, S13, S49
- [ ] The declared result type is visible wherever a result is shown — S7, S18, S20

### Declared result type drives scriptability

- [ ] The result type is explicit on the agent type, not inferred — S2, S3, S36
- [ ] `typed` requires a data type and the rejection explains why — S33
- [ ] A data type on a non-typed result type is prevented, not silently converted — S34
- [ ] Delegation records the child's declared result type — S12, S13
- [ ] A markdown/text boundary is a semantic step and never yields a fully-scripted verdict — S50, S52
- [ ] An all-typed/JSON workflow may be declared fully scriptable — S51
- [ ] The optimizer receives the reference result and its contract — S49
- [ ] One result uses one format on every surface — S8, S9, S18, S48

### Data types are the single input and output contract

- [ ] One registry entry can serve as input contract, output contract, or both — S1, S37, S43
- [ ] No input contract preserves free-prompt behaviour; an input contract makes structured input mandatory — S40, S44
- [ ] Typed results are validated; failure still completes, is recorded, and shows the raw fallback — S19
- [ ] Input is validated before the run; invalid input names the offending field and starts no execution — S44, S47
- [ ] Improving a data type propagates to dialog, decision tools, and rendering without re-entry — S28, S37
- [ ] Third-party typed submissions use the same contract and receive the same result shape — S46–S48

### Child data types and list fields

- [ ] A field can reference another data type as a single value or a list — S22, S32
- [ ] Child references are one level only and deeper chains are rejected with a clear message — S23
- [ ] Child references are same-tenant only and cross-tenant references are rejected — S25, S56
- [ ] Child deletion is blocked and names the dependents — S26
- [ ] Editing a child is reflected wherever it is referenced, with a consumer warning — S27, S28
- [ ] Any field, primitive or child, can be a list — S22, S32
- [ ] A realistic passenger-style structure is modelled entirely in the registry — S22, S41
- [ ] CRUD basics are unchanged: immediate refresh, pre-filled edit, confirm before delete, name reusable, duplicate rejected, at least one field — S26, S32, S37

### Guided fields and schema source

- [ ] Two views over one definition, paste/copy capable — S29
- [ ] Switching views never silently discards content; unrepresentable definitions are preserved and flagged — S29, S30
- [ ] Unrepresentable definitions are rejected on save with a specific problem — S30, S31
- [ ] Saving from either view updates the same data type and every consumer on next load — S28, S29, S37
- [ ] Duplicate-name and required-field validation is identical from both views — S32

### In-dialog contract preview

- [ ] Input and output schemas can be previewed without leaving the dialog — S38
- [ ] The preview matches registry fields/types/allowed values/child-list structure and updates on selection change — S38, S39
- [ ] The preview is read-only with no extra navigation — S38

### Structured input entry

- [ ] An input contract yields a structured form instead of one free-text field — S40
- [ ] Child fields are nested groups and lists are repeatable rows with add/remove — S41
- [ ] Enum/date/number/boolean use type-appropriate controls — S42
- [ ] Required fields are indicated and enforced; invalid submission starts no run — S43, S44
- [ ] Agents without an input contract, and conversational agents, keep today's entry — S40

### Backward compatibility

- [ ] Existing agent types keep working and are presented in the new vocabulary — S2, S3, S36
- [ ] Legacy `auto` is readable and normalised to text; new configurations do not rely on it — S2, S36
- [ ] Existing data types (including `fields`-only and legacy free-text schema) remain readable and validate as today — S4, S29, S32, S61
- [ ] Previously recorded executions/results render unchanged and are not retroactively revalidated — S21, S55, S60
- [ ] The legacy schema migration path is documented for operators, with no review queue — §2.8, §7
- [ ] No recorded result or configured agent loses data — S21, S27, S55, S60, S61, §7

---

## 6. Test File References

Paths follow `easyspec-config.yaml` → `source.tests`. Existing suites are extended where the tech-spec's "Tests to extend" map names them; new files follow the folder's existing naming style (`test_<feature>.py`, `PascalCase.test.tsx`, `kebab-case.spec.ts`).

### Backend — unit (pure logic)

| File | Status | Focus |
|---|---|---|
| `backend/tests/unit/test_io_contract.py` | **New** | Declared-type normalisation (all four + unknown/absent); legacy adapter (`auto`, `typed`-without-data-type, legacy schema surfacing); snapshot resolution incl. one-level child expansion and list markers; envelope build/normalise/validate incl. business-key rejection; boundary classification incl. legacy and delegated; contract invariants |
| `backend/tests/unit/test_schema_canonicalizer.py` | **New** | Guided ↔ canonical round-trip (order, enum values, required, list, child id); guided-representability for nested/unsupported/recursive input; drift detection and repair direction; child extraction with field names and list flags |
| `backend/tests/unit/test_child_references.py` | **New** | One-level/self-reference/cross-tenant validation; wholesale idempotent sync per parent; dependents listing split by class; parent-delete semantics |
| `backend/tests/unit/test_agent_schemas.py` | Extended | Pydantic contract invariants: typed↔data type, data type↔typed, conversational exclusions, `auto` rejection on create/update, legacy tolerance on read |
| `backend/tests/unit/test_agent_runtime_executor.py` | Extended | Envelope built after the LLM loop for all four types; no business-field flattening; telemetry placement; typed persistence driven from payload; failed-run envelope |
| `backend/tests/unit/test_execution_log.py` | Extended | Result representation carries envelope facts; text vs typed payload extraction; no shape branching on stored output type |
| `backend/tests/unit/conversations/test_conversation_activity_schema.py` | Extended | Conversational turn envelope recorded internally only; chat surface and terminal vocabulary unchanged |

### Backend — API / service / integration

| File | Status | Focus |
|---|---|---|
| `backend/tests/test_data_types_api.py` | Extended | Canonical definition in list/detail; list flags; child create/update; one-level/self/cross-tenant rejection; delete protection with named dependents; usage split input/output + parents; validate-source writes nothing; CRUD basics unchanged |
| `backend/tests/test_agent_io_contract_api.py` | **New** | Agent-type create/update/read invariants on REST, normalised declared type, input data type identity, legacy markers, propagation after data-type edit |
| `backend/tests/test_output_validation.py` | Extended | Validation reused for input (pre-dispatch) and output (post-run); list/child payloads; status vocabulary echo |
| `backend/tests/test_agent_outputs_api.py` | Extended | Result-type column/filter; validation-status filter; export columns; legacy rows still listed |
| `backend/tests/test_results_envelope_api.py` | **New** | `GET /results` and `/results/{id}` return envelope facts; filters by type/validation; tenant scoping |
| `backend/tests/test_script_first_dispatcher.py` | Extended | Step contract match → scripted envelope; mismatch → fallback reason + LLM envelope; run never fails on contract mismatch; existing trigger semantics preserved |
| `backend/tests/test_dispatcher_script_context.py` | Extended | Required input keys derived from the input contract incl. child lists; legacy fallback when no data type |
| `backend/tests/api/v1/internal/test_session_status_envelope.py` | **New** | Completion/failure/termination persist envelope facts; late-completion guard preserved; payload-only legacy callers still complete; output-id extraction unchanged |
| `backend/tests/api/v1/internal/test_session_status_string_output.py` | Regression — must stay green | Raw string script result still completes; now envelope-wrapped without altering the stored payload |
| `backend/tests/test_optimization_io_contract.py` | **New** | `get_execution_log` reference result + contract; command-run exclusion; `generate_optimized_plan` step/hand-off validation; fully-scripted acceptance and rejection with named boundary; per-step declared types persisted; legacy plan read |
| `backend/tests/api/v1/internal/test_execute_script_sandbox_segregation.py` | Extended | Replay verifies result contract; still replay-only, no live calls, sandbox segregation unchanged |
| `backend/tests/test_integration_gateway.py` | Extended | Input contract exposure; invalid submit → field errors and no session; valid submit unchanged; envelope-shaped poll; in-flight poll |
| `backend/tests/integration/test_result_envelope_persistence.py` | **New** | One envelope per completed/failed/terminated session; typed output link; repository content type derived from declared type |
| `backend/tests/integration/test_result_surface_consistency.py` | **New** | S18/S20 across log, repository, outputs, session result API, export for typed-valid, typed-invalid, JSON, markdown-delegated, text-legacy, failed |
| `backend/tests/integration/test_delegation_io_contract.py` | **New** | Input validated before child dispatch; child envelope + declared type at parent; failed child → failed envelope; no bare payload dump |
| `backend/tests/communication_hub/test_a2a_envelope_relay.py` | **New** | Relay is byte-identical to the persisted result; failure relay shape; hub stores/interpret nothing |
| `backend/tests/integration/test_management_tool_full_field_parity.py` | Extended | Assistant-managed data type/agent type parity with REST for canonical definitions, child refs, input data type, invariants |
| `backend/tests/integration/test_agent_session_lifecycle.py` | Regression — extend only for envelope facts | Lifecycle statuses/terminal guards unchanged |

### Backend — DB schema and migration (`has_db_changes: true`)

| File | Status | Focus |
|---|---|---|
| `backend/tests/db/test_unified_agent_io_contract_migration.py` | **New** | `information_schema` checks: new `agent_data_types.schema`/`schema_version`/`is_guided_representable`, `agent_types.input_data_type_id`, `agent_jobs.result_type`/`result_validation_status`, `agent_outputs.result_type`, child-reference table columns; nullability/defaults match the additive contract; FK actions (child side restricts, parent side cascades); tenant-scoped unique constraint present; indexes on (tenant, result type) and (tenant, validation status); enum labels for declared result type and validation status; **negative constraint inserts** (cross-tenant child reference, duplicate parent+field, deleting a referenced child); backfill derived definitions; idempotent second run; downgrade then upgrade round-trip; legacy columns and values preserved |
| `backend/tests/db/test_agent_type_text_json_enum_migration.py` | **New** (may be merged into the file above if the revision is single-purpose) | Enum additive behaviour: old labels still valid, new labels present, no OID recreation of existing enums |
| `backend/tests/db/test_drop_execution_mode_migration.py` | Nearest-pattern reference | Real-Postgres, skip-gated migration test pattern to follow |
| `backend/tests/db/test_model_provider_enum_migration.py` | Nearest-pattern reference | Enum/column `information_schema` assertion style |

### Frontend — Vitest

| File | Status | Focus |
|---|---|---|
| `frontend/src/__tests__/dataTypeContract.test.ts` | **New** | `flattenContractFields` (one child level, list markers), `initialStructuredInput` (one row per required list), `validateStructuredInput` (required/enum/adult rule/empty list), type labels |
| `frontend/src/__tests__/DataTypeFormDialog.test.tsx` | Extended | Guided/source tabs keep one draft; list toggle on primitive and child; child picker excludes self/one-level candidates with visible reasons; consumer warning; blocked delete naming dependents; same save path from both tabs |
| `frontend/src/__tests__/DataTypeSchemaSourceEditor.test.tsx` | **New** | Paste/validate/apply/copy; invalid source shows field path; non-representable notice; no silent truncation; discard-and-reload action |
| `frontend/src/__tests__/DataTypesPage.test.tsx` | Extended | Consumers (parent + field + list marker), agent usage split input/output, legacy marker, empty-registry state |
| `frontend/src/__tests__/AgentTypeForm.test.tsx` | Extended | Input contract slot; explicit result type; output data type disabled unless typed and cleared on change; inline invariant errors; legacy `auto` opens as text with note; no `auto` option |
| `frontend/src/__tests__/DataTypeContractPreview.test.tsx` | **New** | Read-only preview shows fields/types/enums/required/list/one-level child; updates on selection change; no edit or navigation path |
| `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx` | Extended | Hosts the preview; preview matches registry for list-of-child; dialog needs no extra navigation |
| `frontend/src/__tests__/StructuredInputForm.test.tsx` | **New** | Passenger rows add/remove; nested child group; enum/date/number/boolean controls; required and at-least-one-adult messages; invalid submit starts no run; large-list row operations |
| `frontend/src/__tests__/AgentSessionLaunchDialog.test.tsx` | Extended | Structured form chosen when an input contract exists; free prompt unchanged otherwise; conversational entry unchanged; invalid submit blocked with field messages |
| `frontend/src/__tests__/OutputTypeResultTab.test.tsx` | Extended | Envelope-driven rendering for text/markdown/json/typed; visible result type; validation-failure raw fallback; failed run shows reason and no payload; no branch on stored output type |
| `frontend/src/__tests__/ResultTypeChip.test.tsx` | **New** | Same label/vocabulary for the four declared types across surfaces; legacy auto renders as text |
| `frontend/src/__tests__/TypedOutputRenderer.test.tsx` | Extended | List fields and one-level child fields render structurally; empty/null/missing distinction |
| `frontend/src/__tests__/AgentOutputsPage.test.tsx` | Extended | Result-type and validation columns/filters; export carries both |
| `frontend/src/__tests__/ResultRepositoryPage.test.tsx` | **New** (page exists, no test today) | Envelope-backed list, type/validation filters, failed result rendering, legacy result rendering |
| `frontend/src/__tests__/DecisionToolForm.test.tsx` | Extended | Child/list schema display; registry selection remains read-only; cross-tenant option absent |

### E2E — Playwright (mocked + one real backend)

| File | Status | Focus |
|---|---|---|
| `e2e/tests/data-types-crud.spec.ts` | Extended | Child reference creation, list toggle, delete blocked with named dependents, source tab round-trip; existing CRUD basics still pass |
| `e2e/tests/data-type-child-references.spec.ts` | **New** | Passenger-list authoring, one-level disabled reasons, unrepresentable source notice, consumer warning, rename survival |
| `e2e/tests/agent-io-contract-config.spec.ts` | **New** | Explicit result type; typed-requires-data-type inline error; data-type-on-non-typed blocked; legacy auto opens as text; in-dialog preview refreshes on selection |
| `e2e/tests/structured-input-launch.spec.ts` | **New** | Passenger rows, enum/date/number controls, required errors, at-least-one-adult, no run on invalid submit |
| `e2e/tests/result-envelope-surfaces.spec.ts` | **New** | One result type badge and payload format in execution log, repository, outputs page; validation-failure fallback; failed-run reason |
| `e2e/tests/agent-io-contract.real-backend.spec.ts` | **New — REQUIRED real backend** | Unmocked: create data types (parent + child list) via API → create agent type `typed` → submit structured input → poll to completion → assert envelope `result_type`/`validation_status`/payload; create a legacy `auto` agent type directly and assert its result renders as text; cleanup by deletion |
| `e2e/tests/agent-clients.real-backend.spec.ts` | Nearest-pattern reference / extend if a typed client fixture exists | Unmocked real-backend style, env-token gating |
| `e2e/tests/data-types-crud.spec.ts`, `agent-management.spec.ts`, `agent-outputs-query.spec.ts` | Regression | Pre-existing registry, agent-type, and output flows must remain green |

### Pre-test checklist (`has_db_changes: true`)

Run before any backend, integration, or E2E layer:

- [ ] `.change.yaml` reports `has_db_changes: true`; both revisions are present under `backend/alembic/versions/`.
- [ ] Before upgrade, `cd backend && python -m alembic current` reports the pre-change head `7b1e4c2d9f03`; after each revision it reports that revision (structure, then backfill).
- [ ] `python -m alembic upgrade head` completes with no error; `alembic current` afterwards reports the backfill head.
- [ ] The backfill is re-run and reports no changes (idempotency).
- [ ] Restart backend services so ORM metadata is reloaded (`./scripts/restart-backend.sh` on macOS; `parthenon.ps1 restart -Services backend` on Windows), then confirm health probes pass.
- [ ] The pytest `_migrate_postgres_test_db` fixture ran `alembic upgrade head` against the PostgreSQL test DB (it is session-scoped and autouse); confirm no "alembic upgrade skipped" warning.
- [ ] Real-Postgres DB tests are not skipped: `PARTHENON_DATABASE_URL` is set to a reachable `postgresql://` URL.
- [ ] For the real-backend E2E variant: `REAL_API_BASE_URL`, `REAL_API_TOKEN`, and a seeded typed agent type / input contract fixture are provided; the skip reason is captured in the report if not.
- [ ] Frontend tests run with the JSON reporter: `npx vitest run --reporter=json --outputFile=vitest_results.json`, then read `numPassedTests` / `numFailedTests`.
- [ ] Baseline: capture the current pass/fail counts per layer before the change so pre-existing failures are distinguishable from regressions.

---

## 7. Migration Verification

Two additive revisions on pre-change head **`7b1e4c2d9f03`** (verified as the current single head in this workspace on 2026-11-21). All checks below run against a real PostgreSQL database; a skip is reported, never treated as a pass.

### 7.1 Structure revision

| # | Check | Expected observable result | Covered by |
|---|---|---|---|
| 1 | Chain | `down_revision` points at `7b1e4c2d9f03`; `alembic current` reports the new structure revision after upgrade | `test_unified_agent_io_contract_migration.py` |
| 2 | Data type columns | `agent_data_types.schema`, `schema_version`, `is_guided_representable` exist; `schema`/`schema_version`/representability are nullable/defaulted so pre-cutover writes succeed | `information_schema.columns` assertions |
| 3 | Agent type columns | `agent_types.input_data_type_id` exists, nullable, FK to data types; stored result-type column keeps `auto`, `markdown`, `typed` and gains `text`, `json` | `information_schema` + enum label assertions |
| 4 | Session columns | `agent_jobs.result_type` and `result_validation_status` exist and are nullable; validation-status enum has exactly `not_applicable`, `valid`, `validation_error` | `information_schema` + enum label assertions |
| 5 | Output column | `agent_outputs.result_type` exists, nullable at this stage (backfill fills it) | `information_schema` |
| 6 | Child-reference entity | Table exists with tenant, parent, child, field name, list flag, timestamp; both FKs declared; tenant-scoped unique constraint on (parent, field name); child-side reference prevents deleting a referenced child; parent-side rows disappear with the parent | `information_schema` + FK action assertions |
| 7 | Same-tenant composite reference | The (data type id, tenant) uniqueness the composite reference points at exists | `information_schema.table_constraints` |
| 8 | Indexes | Indexes for (tenant, result type) and (tenant, validation status) exist on sessions; filtering queries use them | `information_schema.indexes` / query plan assertion |
| 9 | Negative constraint tests | Inserting a child reference whose child tenant differs from the parent tenant fails; a duplicate (parent, field name) fails; deleting a referenced child fails | direct constraint-violation tests |
| 10 | Inertness | With the structure revision applied but before any reader prefers the canonical definition, existing data-type/agent-type/output list endpoints still respond successfully | API smoke in the same suite |
| 11 | No removals | `agent_data_types.fields`, `agent_types.input_schema`/`output_schema`, and all legacy enum labels still exist | `information_schema` assertions |

### 7.2 Backfill revision

| # | Check | Expected observable result | Covered by |
|---|---|---|---|
| 12 | Ordering | Backfill `down_revision` points at the structure revision; it runs only after all new enum labels exist | chain assertion |
| 13 | Derivation | Every data type without a canonical definition gains one derived from `fields` with order, enum allowed values, required flags, and descriptions preserved; schema version and guided-representability set | row-level assertions after upgrade |
| 14 | Round-trip fidelity | A spot-checked legacy data type derives a definition that re-projects to the same guided field list (no reordering, no lost enum value, no required-flag flip) | canonicalizer round-trip on real rows |
| 15 | Typed outputs | Existing `agent_outputs` rows receive `result_type = typed` and keep their recorded validation verdict (no recomputation) | row-level assertions |
| 16 | Historical sessions | `agent_jobs.result_type` and `result_validation_status` remain **null** on historical rows so the read adapter applies legacy normalisation | row-level assertions |
| 17 | Child references | No child-reference rows are created by the backfill | count assertion |
| 18 | Idempotency | Re-running the backfill changes zero rows (identical row counts and values before/after) | second-run comparison |
| 19 | Projection consistency | The reconcile check reports zero drift immediately after backfill, and reports pre-change rows without a definition distinctly from drift | reconcile API/service assertion |
| 20 | Drift repair | A deliberately corrupted `fields` projection is detected and repaired from the canonical definition (definition is never regenerated from the projection) | targeted repair test |

### 7.3 Reversibility and legacy reads

| # | Check | Expected observable result | Covered by |
|---|---|---|---|
| 21 | Backfill downgrade | Downgrade is effectively a no-op; old rows keep working through defaults and read normalisation | downgrade + read assertions |
| 22 | Structure downgrade | Child-reference entity drops first, then the new columns; `fields` and legacy free-text schema columns are untouched at every step | downgrade + `information_schema` assertions |
| 23 | Re-upgrade | After downgrade, `alembic upgrade head` succeeds and reproduces the same schema and row state | full round-trip test |
| 24 | Enum residue | New result-type labels / validation-status enum may remain after downgrade and are unused — no error, no data loss | post-downgrade assertion |
| 25 | Legacy agent reads | `auto` reads as text; `typed` without data type reads as text; legacy free-text schema surfaces as `legacy_schema`; stored values byte-identical | API read test on migrated rows |
| 26 | Legacy result reads | Pre-change sessions and typed outputs render with their original payload in the log, repository, and export; declared type resolved on read; no retroactive validation | read-surface tests |
| 27 | Legacy plan reads | A plan stored without per-step declared types loads and resolves at read time | plan load test |
| 28 | No production loss | Row counts and payload hashes for data types, agent types, sessions, and outputs are unchanged by both revisions | before/after snapshot comparison |

---

## 8. Known Gaps and Escalation Points

1. **Real LLM-backed typed run in the real-backend E2E.** The canonical E2E environment cannot guarantee a live model provider. The real-backend variant therefore asserts the *contract, submit, persistence, and rendering* path end to end (typed submit → envelope → poll), and the content generation is stubbed only at the provider boundary. A fully live typed run remains a manual smoke step; it must be recorded as executed or explicitly deferred in the test report.
2. **Optimizer conversation quality.** The optimizer's *reasoning* about contract guidance in the mission prompt is not deterministically assertable. Tests assert the binding verdict from plan validation, the reference result/contract exposure, and the rejection message. Prompt-guidance effectiveness is a manual/exploratory check.
3. **Legacy free-text schema fidelity.** There is no defined oracle for "faithful enough" conversion because the PRD deliberately does not attempt automatic conversion where it would not be faithful. Tests assert readability, non-enforcement, and the presence of operator notes; they cannot assert a lossless conversion that the product does not perform.
4. **Large-payload performance.** Validation cost on very large payloads is covered functionally (large list submission), not as a performance benchmark. A regression budget can be added once a baseline exists.
