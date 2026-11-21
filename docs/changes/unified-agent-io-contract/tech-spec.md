# Technical Specification — Unified Agent I/O Contract

Change: `unified-agent-io-contract`
Source of truth: [`prd.md`](prd.md) · [`spec-change.md`](spec-change.md) · [`architecture.md`](architecture.md) · [`data-model.md`](data-model.md) · [`prototype/index.html`](prototype/index.html)

---

## 1. Technical Overview

Two ideas carry this change. First, **one envelope**: every producer (Agent Runtime LLM loop, fully-scripted run, delegated step, conversational turn, failure path) hands its raw outcome to a single normaliser that emits an Agent Result Envelope — execution status, declared result type, payload, validation status, contract metadata, error, producer metadata. Second, **one contract unit**: the registry data type defines input and output, is stored as a canonical JSON Schema with the guided field list as a regenerated projection, and is the only thing a contract is resolved from.

Control Center owns contract truth (registry, resolution, validation, persistence, plan validation). Agent Runtime consumes a read-only contract snapshot obtained at dispatch, builds the envelope in memory, and calls Control Center for validation and persistence — it never touches the database. Communication Hub relays the envelope unchanged and never inspects payload semantics.

Three properties make the migration safe: (a) every schema addition is nullable or defaulted and lands before any reader prefers it; (b) the legacy read path is a single adapter that normalises `auto` to text, normalises typed-without-data-type to text, and keeps legacy free-text schemas readable but non-enforcing; (c) no stored value, result, or definition is rewritten by this change.

---

## 2. Component Breakdown

### 2.1 Control Center — contract ownership

| Component | Responsibility | Where |
|---|---|---|
| **Schema Canonicalizer** | Pure conversion between the guided field list and the canonical object schema; child-reference extraction; guided-representability; projection drift detection. No database access. | `backend/app/services/data_types/schema_canonicalizer.py` (new) |
| **Child Reference Service** | Persists and validates the child-reference projection: same-tenant, one-level, no self-reference, dependents for deletion protection, wholesale regeneration per parent in the same transaction. | `backend/app/services/data_types/child_references.py` (new) |
| **Data Type Service** | Registry writes: accepts either editor view, makes the canonical definition authoritative, regenerates the projection, blocks deletion with named dependents, exposes reconcile/repair. | `backend/app/services/data_types/service.py` (extended) |
| **Contract Module** | The single origin of contract truth: declared result type, legacy normalisation, resolution to a contract snapshot (with one-level child expansion), envelope build/normalise/validate, scriptability classification, invariant checks. Pure; imported by both services. | `backend/app/services/agents/io_contract.py` (new) |
| **Envelope Schemas** | Pydantic models for the envelope and the internal persistence requests, so the shape is validated at the service boundary. | `backend/app/schemas/result_envelope.py` (new) |
| **Output Validation** | Existing schema validation re-used for both input (pre-dispatch) and output (post-run) payloads, against the resolved data type. | `backend/app/api/v1/internal/outputs.py`, `backend/app/services/validation/schema_validation_service.py` |
| **Result Persistence** | Session completion writes payload + declared result type + validation status; typed results additionally write an output record. | `backend/app/api/v1/internal/session_data.py`, `backend/app/services/outputs/service.py` |
| **Result Repository** | Stores one content type per result derived from the declared result type. | `backend/app/services/results/store.py` |
| **Plan Validation** | Validates per-step and per-hand-off contracts and is the binding authority on a `fully_scripted` claim. | `backend/app/api/v1/internal/optimization_tools.py`, `backend/app/services/agents/optimized_plan_service.py` |
| **Management Serialisation** | Exposes resolved contracts and legacy markers to the management panel and the assistant. | `backend/app/api/v1/internal/management_tools.py` |

### 2.2 Agent Runtime — envelope production

| Component | Responsibility | Where |
|---|---|---|
| **Envelope Builder / Result Normalizer** | One normalisation entry point used by every path; converts a raw outcome plus snapshot into the envelope. | `backend/app/services/agents/io_contract.py` (shared, pure) |
| **LLM Executor** | Produces the raw outcome for normal LLM runs, builds the envelope, drives typed validation and persistence, and stops flattening business fields. | `backend/app/services/agents/runtime_executor.py` |
| **Script-First Dispatcher** | Checks each script step result against its declared contract; a mismatch is a fallback trigger; builds the envelope from the script result. | `backend/app/agent_runtime/scripts/dispatch.py` |
| **Script Runner** | Executes steps and reports step-level telemetry; gains declared input/output contract attachment. | `backend/app/agent_runtime/scripts/runner.py`, `backend/app/agent_runtime/scripts/schemas.py` |
| **Delegation Tool** | Returns the child envelope with its declared result type to the parent instead of a bare payload dump. | `backend/app/services/agents/langchain_tool_wrapper.py` |
| **Runtime Data Client** | Carries envelope facts to Control Center on completion/failure and calls validation endpoints. | `backend/app/agent_runtime/data_client.py` |

### 2.3 Communication Hub — transport only

| Component | Responsibility | Where |
|---|---|---|
| **A2A Result Relay** | Waits for and forwards the child envelope unchanged, including failures. Stores nothing, interprets nothing. | `backend/app/communication_hub/api/a2a.py` |
| **Integration Gateway** | Third-party submit/poll; forwards input for validation and returns the envelope-shaped result. | `backend/app/communication_hub/api/integration_gateway.py` |

### 2.4 Frontend — contract authoring and result reading

| Component | Responsibility | Where |
|---|---|---|
| **Data Type Editor** | Two tabs over one definition (guided + schema source), live resolved-schema preview, list toggle, child picker with one-level constraints, non-representable handling, consumer warning. | `frontend/src/components/agents/DataTypeFormDialog.tsx` (extended), `DataTypeSchemaSourceEditor.tsx` (new) |
| **Contract Preview** | Read-only input/output schema preview inside the agent type dialog, updating on selection change. | `frontend/src/components/agents/DataTypeContractPreview.tsx` (new) |
| **Agent Type Form** | Input contract slot and explicit declared result type with the invariant rules enforced client-side. | `frontend/src/pages/agents/AgentTypeForm.tsx` |
| **Structured Input Form** | Form generated from the input contract: nested child groups, repeatable list rows, typed controls, field-level validation. | `frontend/src/components/agents/StructuredInputForm.tsx` (new) |
| **Contract Utilities** | Shared field flattening (one child level), initial value construction, client-side pre-validation, type labels. | `frontend/src/utils/dataTypeContract.ts` (new) |
| **Result Rendering** | Envelope-driven rendering with a visible result type and the raw fallback on validation failure. | `frontend/src/components/executions/OutputTypeResultTab.tsx` (extended), `ResultTypeChip.tsx` (new) |

### 2.5 New versus modified files

| Status | File |
|---|---|
| New | `backend/app/services/agents/io_contract.py` |
| New | `backend/app/schemas/result_envelope.py` |
| New | `backend/app/services/data_types/schema_canonicalizer.py` |
| New | `backend/app/services/data_types/child_references.py` |
| New | `frontend/src/components/agents/DataTypeSchemaSourceEditor.tsx` |
| New | `frontend/src/components/agents/DataTypeContractPreview.tsx` |
| New | `frontend/src/components/agents/StructuredInputForm.tsx` |
| New | `frontend/src/components/executions/ResultTypeChip.tsx` |
| New | `frontend/src/utils/dataTypeContract.ts` |
| Modified | Models, migrations, services, internal APIs, and UI listed in the Code Reference Map |

---

## 3. API Changes

All routes below already exist unless marked **new**. Descriptions only — payload shapes belong to the schemas listed in the Code Reference Map.

### 3.1 Public / management API (Control Center)

| Route | Change |
|---|---|
| `GET /api/v1/data-types` | Response gains, per item, the canonical definition, guided-representability, and child-reference count. The `usage=true` variant additionally reports parent data types (with field name and list flag) and agent types split into input and output consumers. |
| `GET /api/v1/data-types/{id}` | Response gains the canonical definition, guided-representability, child references, and named dependents sufficient to render both editor views and the delete dialog in one call. |
| `POST /api/v1/data-types` | Accepts either a guided field list or a canonical definition (source mode). Validates child rules, list flags, duplicate names, and at least one field. |
| `PUT /api/v1/data-types/{id}` | Same acceptance and validation; regenerates the guided projection and child references; returns the dependent parents when the edited data type is used as a child. |
| `DELETE /api/v1/data-types/{id}` | Rejection extended to child-reference, input-contract, output-contract, and decision-tool dependents, each named in a structured conflict body. |
| `POST /api/v1/data-types/validate-source` | **new** — parse and validate a source-mode definition without persisting; returns field-specific problems and the guided-representability verdict. Declared before the identifier route so the literal path is not captured as an identifier. |
| `GET /api/v1/agents/types`, `GET /api/v1/agents/types/{id}` | Response gains the normalised declared result type, the input data-type identity and name, and legacy markers (legacy auto, legacy free-text schema present, legacy typed-without-data-type). |
| `POST /api/v1/agents/types`, `PUT /api/v1/agents/types/{id}` | Accepts an optional input data type and enforces the contract invariants: typed requires an output data type; a non-typed result type must not carry one; conversational agents carry neither; `auto` is rejected for new and edited configurations. Rejections name the field to change. |
| `GET /api/v1/results`, `GET /api/v1/results/{id}` | Response carries the envelope (status, declared result type, payload, validation status) so the repository renders without inference. |
| `GET /api/v1/agent-outputs`, `GET /api/v1/agent-outputs/auto`, `GET /api/v1/agent-outputs/export` | Gains result-type and validation-status columns and filters; export carries both. |
| `GET /api/v1/agents/sessions/{id}/result`, `GET /api/v1/agents/sessions/{id}` | Result read returns the envelope; typed outputs remain linked by identifier. |

### 3.2 Internal API (service certificate + signed tenant headers)

| Route | Change |
|---|---|
| `GET /api/v1/internal/data/agent-types/{id}/context` | Returns a resolved contract snapshot: declared result type, input contract, output contract (resolved schema with one-level children), scriptability verdict per boundary, and the schema prompt block. Legacy fields such as the raw output schema and data-type identifiers stay populated as deprecated aliases for one release. |
| `POST /api/v1/internal/validate-output` | Unchanged route and semantics; used for both input (pre-dispatch) and output (post-run) payloads. Response additionally echoes the validation status vocabulary used by the envelope. |
| `POST /api/v1/internal/agent-outputs` | Accepts the declared result type alongside the payload and validation status. |
| `GET /api/v1/internal/agent-outputs` | Returns the declared result type; supports result-type and validation-status filters. |
| `PATCH /api/v1/internal/data/sessions/{id}/status` | Accepts the envelope facts (declared result type, validation status, and an envelope payload) on completed and failed transitions. Existing guard behaviour (late running, operator-terminated completion) is unchanged. |
| `POST /api/v1/internal/data/sessions/{id}/result` | Same envelope facts on the result-write path; keeps the repository side effect and hub dispatch. |
| `GET /api/v1/internal/data/sessions/{id}` | Returns the persisted envelope facts so A2A waiters and the runtime can relay without inspecting the payload. |
| `POST /api/v1/internal/data/a2a/request` | Resolves the delegation request and now validates the supplied input against the child agent's resolved input contract, returning field-level errors instead of preparing a run when the contract is not met. |
| `POST /api/v1/internal/system-tools/get-execution-log` | Response adds the reference execution's result payload, declared result type, and resolved contract beside the existing input, input schema, transcript, and text log. |
| `POST /api/v1/internal/system-tools/execute-script` | Replay verification additionally checks the produced result against the declared output contract and returns field-level mismatches. Remains replay-only. |
| `POST /api/v1/internal/system-tools/generate-optimized-plan` | Validates every step contract and hand-off, and rejects a `fully_scripted` claim when any boundary resolves to text or markdown. Existing status allow-list unchanged. |
| `GET /api/v1/internal/scripts/...` (serving version, optimized plan) | Carries the per-step declared contracts in the plan payload; no route shape change. |

### 3.3 Third-party integration (Communication Hub gateway)

| Route | Change |
|---|---|
| `GET /integrate/config` | Returns the resolved input contract (identity, slug, schema, structured-input-required flag) instead of an opaque input schema. |
| `POST /integrate/submit` | Input is validated against the agent's input data type before enqueue; invalid input returns field-level errors and starts no execution. Credential classes, origin allowlist, rate limits, and the non-conversational restriction are unchanged. |
| `GET /integrate/session/{id}` | Returns the envelope (status, declared result type, payload, validation status, error). The retired chat route is untouched. |

### 3.4 Assistant (Control Center MCP management tools)

| Tool | Change |
|---|---|
| `data_types` create / update | Accepts the canonical definition, list flags, and child references; returns structured, correctable validation errors. Preview-and-approval and the no-deletion rule are unchanged. |
| `agent_types` create / update | Accepts the input data type and enforces the same invariants as the REST API. |
| `agent_types` read | Returns the declared result type, input contract, and legacy markers. |

---

## 4. State Management

### 4.1 Server state (React Query)

| Query key | Owner | Invalidation rule |
|---|---|---|
| `['data-types']` (list, usage, detail) | registry | Invalidated on any data-type create/update/delete. Because agent-type forms, the contract preview, and decision-tool forms render the same definition, every data-type mutation also invalidates `['agent-types']` and the decision-tool list. |
| `['agent-types']` (list, detail) | agent configuration | Invalidated on agent-type create/update/delete. Also invalidated after a data-type mutation, because the resolved contract display changes. |
| Session/result queries | execution surfaces | Invalidated on completion events (existing behaviour); they are not client-side derived from the agent type, so a later agent-type edit cannot retroactively change a rendered historical result. |

No optimistic updates are introduced: "immediate list refresh after save" and "edit pre-filled with current values" stay as they are today.

### 4.2 Local component state

| Surface | State |
|---|---|
| Data type editor | Active tab; guided draft; source text; a source-dirty flag; a blocked flag when the source cannot be displayed by the guided view; validation errors. Leaving a tab never mutates the draft unless the user applies or saves. |
| Agent type form | Draft values including input contract kind, input data type, declared result type, output data type; inline invariant errors computed from the draft, not from the server. |
| Structured input form | Draft values keyed by field path; per-field error map; a "submitted once" flag controlling when errors become visible; repeatable-row collection per list field. |
| Delete dialog | Loaded dependents; deletion disabled while any dependent exists. |
| Result tab | No derived type state: the declared result type is read from the server payload, never re-inferred from the payload's appearance. |

### 4.3 Error handling

Every dialog with an API call follows the project dialog error standard: a dialog-scoped error state, try/catch around the mutation, cleared on open/close, and the permission alert rendered first in the dialog body. This matters here because data-type and agent-type saves can return 403, 409 (named dependents), and 422 (contract errors), and all three must be visible without closing the dialog.

---

## 5. Data Access Patterns

### 5.1 Ownership and boundaries

| Concern | Owner | Rule |
|---|---|---|
| Reading/writing data types, agent types, sessions, outputs, results | Control Center | Only Control Center holds a database session. |
| Contract resolution | Control Center | Performed when the execution is dispatched; the result is a snapshot. |
| Envelope assembly | Agent Runtime | In memory only. No datastore, no registry access. |
| Envelope persistence | Control Center | Via internal endpoints carrying payload plus envelope facts. |
| Envelope relay | Communication Hub | Forward-only. Holds no contract, no payload state, interprets nothing. |
| Input validation | Control Center | Both for in-product submit and third-party submit, before dispatch. |
| Output validation | Control Center, invoked by Agent Runtime | After the run, before completion is reported. |

### 5.2 Contract snapshot

The snapshot is resolved once per execution and is immutable for that run. It contains the declared result type, the resolved input and output schemas (with one-level children expanded and list markers applied), data-type identity and slug, schema version, and the per-boundary scriptability verdict. A data type edited mid-run is therefore evaluated consistently for that run; the design deliberately refuses mid-execution re-resolution.

Agent Runtime calls Control Center over the existing internal client (service certificate plus signed tenant headers). No new credential, no DB credential, and no identity token ever appears in the snapshot.

### 5.3 Tenant scoping

| Access | Scoping |
|---|---|
| Data type read/write | Tenant from the request context; name and slug unique per tenant. |
| Child reference | Parent and child must share a tenant; enforced by a composite reference and by the application rule. |
| Agent type input/output assignment | The assigned data type must resolve inside the calling tenant; a foreign identifier is a reference error, not a lookup miss. |
| Contract snapshot | Built only from rows resolved in the calling tenant. |
| Envelope persistence | Session, output, and result rows are tenant-stamped as today; the internal endpoints continue to fail closed without signed headers. |

### 5.4 Read/write summary

| Data | Read by | Written by |
|---|---|---|
| Canonical definition + projection + child references | Control Center (registry API, contract resolution, validation, plan validation, decision tools) | Control Center only, in one transaction |
| Agent type contract configuration | Control Center (management API, assistant, contract resolution) | Control Center only |
| Envelope (status, type, payload, validation) | Control Center read APIs, Communication Hub relay, third-party gateway | Control Center persistence endpoints (payload supplied by Agent Runtime) |
| Typed output record | Control Center read APIs, result rendering | Control Center, on Agent Runtime request |
| Reference execution for optimization | Control Center optimization tools | Control Center |

---

## 6. Envelope Field Dictionary

The envelope is the only result shape. Business fields appear only inside the payload.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `status` | enum: `queued`, `running`, `waiting_for_human`, `completed`, `failed`, `terminated` | yes | Execution status. Reuses the session lifecycle vocabulary; there is no separate result-status field. |
| `result_type` | enum: `text`, `markdown`, `json`, `typed` | yes | Declared result type as recorded at execution time, after legacy normalisation. |
| `payload` | JSON value (object for `typed` and `json`, string for `text` and `markdown`) | unless failed before payload | The business result. Never merged into the envelope level. |
| `validation_status` | enum: `not_applicable`, `valid`, `validation_error` | yes | Contract verdict for this result. `not_applicable` for text, markdown, and for JSON with no data type. |
| `contract.source` | enum: `data_type`, `legacy_schema`, `none` | yes | Where the contract came from; `legacy_schema` marks a read-only legacy definition. |
| `contract.data_type_id` | identifier | when source is `data_type` | The assigned output data type. |
| `contract.data_type_slug` | string | when known | Runtime identifier used by clients and by `query_result`. |
| `contract.data_type_name` | string | when known | Display name for result surfaces. |
| `contract.schema_version` | integer | when known | Distinguishes backfilled rows from authored rows; not a schema history. |
| `contract.errors` | list of field-and-message pairs | when `validation_status` is `validation_error` | Field-level mismatches, in product language. |
| `contract.raw_payload` | string | when `validation_error` | The unparsed result kept as the rendering fallback. |
| `contract.typed_output_id` | identifier | when a typed record exists | Link to the typed output record. |
| `error.message` | string | when failed or terminated | Human-readable reason. |
| `error.category` | enum: `provider_error`, `validation_error`, `guardrail_stop`, `script_failure`, `timeout`, `terminated`, `internal_error` | when failed or terminated | Failure family, used for filtering. |
| `error.stop_reason`, `error.stop_details` | enum, object | when terminated | Existing termination attribution, carried unchanged. |
| `producer.path` | enum: `llm`, `fully_scripted`, `script_tool`, `delegated`, `conversational` | yes | Which path produced the result. Derived from existing lineage, not a new column. |
| `producer.agent_type_id` | identifier | yes | Producer agent type. |
| `producer.session_id` | identifier | yes for sessions | Execution session; for conversational turns the turn identifier where one exists. |
| `producer.parent_session_id` | identifier | when delegated | Delegation provenance. |
| `producer.plan_id` | identifier | when a plan drove the run | Implementation or optimized plan evidence. |
| `producer.script_version_id` | identifier | when a script drove the run | Script evidence. |
| `producer.duration_ms` | integer | when known | Wall-clock duration. |
| `producer.telemetry` | object | when known | Runtime bookkeeping that previously leaked into the payload: guardrail usage, token usage, model identifier. Never business data. |

Invariants enforced by validation: `result_type = typed` requires `contract.data_type_id`; `result_type` other than typed must not carry `contract.data_type_id`; `validation_status` is `not_applicable` when no contract applies; a failed result carries no payload; no envelope-level key may be a business field name.

---

## 7. Contract Resolution Matrix

"Data type" below means a registry data type assigned to the agent type. A result type of `auto` is only reachable on a stored legacy row and always resolves through the adapter first.

| Mode | `input_type` | Declared result type (stored) | Input data type | Output data type | Outcome |
|---|---|---|---|---|---|
| Non-conversational | `none` | `text` | — | — | Allowed. Free prompt; free-text result. |
| Non-conversational | `none` | `markdown` | — | — | Allowed. |
| Non-conversational | `none` | `json` | — | — | Allowed. Parseable but unvalidated (no data type). |
| Non-conversational | `none` | `typed` | — | assigned | Allowed. Result validated against the output data type. |
| Non-conversational | `none` | `typed` | — | none | **Rejected** on save: typed requires an output data type. |
| Non-conversational | `none` | `text` / `markdown` / `json` | — | assigned | **Rejected** on save: a data type requires typed. No silent conversion. |
| Non-conversational | `typed` | `text` / `markdown` / `json` | assigned | — | Allowed. Structured input mandatory; input validated before dispatch; result unvalidated. |
| Non-conversational | `typed` | `typed` | assigned | assigned | Allowed. Input validated pre-dispatch, result validated post-run. The two data types may differ. |
| Non-conversational | `typed` | any | none | any | **Rejected** on save (legacy `input_schema` rows remain readable and are treated as structured input without a data-type contract). |
| Conversational | `conversation` | `text` | — | — | Allowed. Turns are semantic bridges. |
| Conversational | `conversation` | `markdown` | — | — | Allowed. |
| Conversational | `conversation` | `json` | — | — | Allowed as a declared type (per approved prototype); turns are still never a scriptable workflow boundary and are never validated against a data type. |
| Conversational | `conversation` | `typed` | — | any | **Rejected** on save, and the data-type selector is not offered. |
| Conversational | `none` / `typed` | any | any | any | **Rejected** on save: conversation is the only input type for a conversational agent. |
| Any | `none` | `text` / `markdown` / `json` | any data type in another tenant | — | **Rejected**: reference error naming the foreign identifier. |
| Any | any | any | a data type that does not exist in the tenant | same | **Rejected**: reference error, not a silent null. |
| Legacy row | `none` | stored `auto` | — | maybe attached | **Reads as `text`.** The attached data type is presented as legacy and is not enforced. Not rewritten. |
| Legacy row | `none` | stored `typed` with no data type | — | none | **Reads as `text`.** Not rewritten; the row becomes saveable once an explicit value is chosen. |

---

## 8. Scriptability Rules

Classification is from the **declared** result type, never from the payload's appearance. The per-boundary verdict is advisory input; the binding verdict on a `fully_scripted` claim is issued only by plan validation in Control Center.

| Boundary | Classification | Evidence | Consequence |
|---|---|---|---|
| `typed` | Scriptable | Declared type + resolved data type; confirmed by plan validation | A script step may produce or consume it; `fully_scripted` permitted if every boundary qualifies. |
| `json` | Scriptable | Declared type; confirmed by plan validation | Same as typed, without contract validation. |
| `markdown` | Semantic bridge | Declared type; plan validation | No script step may parse it; an LLM step must interpret it; a `fully_scripted` claim is rejected. |
| `text` | Semantic bridge | Declared type; plan validation | Same as markdown. |
| Legacy `auto` | Semantic bridge | Adapter resolves to text first | Never silently becomes scriptable. |
| Conversational turn | Not a workflow boundary | Turn vocabulary only | A conversational agent has no plans; a turn can never make a workflow scriptable. |
| Delegated hand-off | Follows the child's declared type | Child envelope + declared type | The parent's boundary is classified from the contract, not from the payload. |

Rules that must hold:

- A claim of `fully_scripted` is rejected if **any** step or hand-off resolves to `text` or `markdown`, including a legacy `auto` that resolves to text.
- A contract mismatch at a script step is an enumerated **fallback trigger** that routes to the LLM path and records the reason — it is never a run failure.
- The optimizer is given the reference execution's actual result and contract, so the predicted final format is evidence-based.
- Agent Runtime never asserts scriptability; it only reports per-boundary verdicts.

---

## 9. Migration and Backfill Approach

### 9.1 Revisions

Two additive revisions on the current head `7b1e4c2d9f03`, autogenerated and hand-reviewed.

| Revision | Contents | Why this order |
|---|---|---|
| **Structure** | New nullable/defaulted columns on data types, agent types, sessions, and outputs; new declared-result-type values; the validation-status enumeration; the child-reference entity with tenant-scoped uniqueness and its composite reference; indexes for filtering by result type and validation status. Existing free-text schema columns untouched. | Every addition is inert before cutover, so the running application is unaffected. |
| **Backfill** | Derive a canonical definition for data types without one (order, enum values, required flags, descriptions preserved) and mark schema version and guided-representability; set `result_type = typed` on existing output records; leave historical session result types null so the read adapter applies legacy normalisation; create no child references. | Readers must not prefer the canonical definition before it exists; enums must exist before anything persists them. |

### 9.2 Apply and verify (operator steps)

1. Confirm the pre-migration head reports `7b1e4c2d9f03`.
2. Apply the structure revision; confirm the reported current revision is the new head.
3. Apply the backfill revision; confirm the reported current revision is the backfill head.
4. Re-run the backfill and confirm it changes nothing (idempotency).
5. Run the projection reconcile check and confirm zero drift.
6. Restart the Control Center service so ORM metadata is reloaded, then start the remaining services in the documented order.
7. Smoke-check: data-type list and detail, agent-type list and detail, one typed run, one legacy result.

### 9.3 Reversibility

Both revisions have downgrades. Dropping the child-reference entity and then the new columns restores the previous shape; the legacy field list and the legacy free-text schema columns are untouched at every step. The backfill downgrade is effectively a no-op: defaults and read normalisation keep old rows working. Removed enum values cannot be withdrawn from a live database, so the new result-type values and the validation-status enumeration may remain unused after a downgrade — harmless.

### 9.4 What is deliberately not migrated

- No rewrite of stored `auto`, `typed`, or free-text schemas.
- No retroactive revalidation of historical results; the recorded verdict stands even if the data type changes later.
- No review queue, approval step, or triage backlog for legacy definitions.
- No schema versioning or history beyond the version marker.

---

## 10. Backward-Compatibility Adapters

There is exactly one legacy read path, inside the contract module. No consumer implements its own fallback.

| Legacy item | Adapter behaviour | Never does |
|---|---|---|
| `agent_types.output_type = auto` | Resolves to `text`. A markdown-looking body stays text. An attached data type is surfaced as legacy and not enforced. | Rewrite the stored value, or offer `auto` on a new configuration. |
| `agent_types.output_type = typed` with no data type | Resolves to `text` on read. | Block reads, or rewrite the row. The invariant applies on save only. |
| `agent_types.input_schema` / `output_schema` | Surfaced as a read-only legacy contract (`contract.source = legacy_schema`); the legacy output schema may still be rendered into the prompt as advisory guidance. | Enforce it for validation, send it as provider structured output, or drop it. |
| `agent_types.input_type = typed` with a legacy input schema and no data type | Keeps structured input behaviour; input is passed through without data-type validation. | Require a data type retroactively. |
| `agent_data_types.fields` only | Read as if the canonical definition were derived from the fields. The row gains a real definition on its first save. | Drop the column or require a rewrite. |
| `agent_jobs.output_data` history | Read as envelope payload with a resolved declared type and validation status; a stored value with no facts resolves through the adapter. | Rewrite, or revalidate. |
| `agent_outputs` rows without a result type | Backfilled as typed; their recorded validation verdict is preserved. | Recompute the verdict. |
| Decision tool assignment | Follows the same definition; selection remains a read-only registry choice. | Allow ad-hoc schema authoring. |
| Third-party clients built against the old response | Receive the envelope with the same status vocabulary and the declared type; the payload is the same content at the same place in the envelope's payload field. | Silently change a result's format between surfaces. |

---

## 11. Behaviours That Must Not Change

| Area | Must remain exactly as today |
|---|---|
| Guardrails and the repeated-call loop | Thresholds, counters, stop categories, stop reasons, token accounting, and the surfaced stop payloads. |
| Sandboxing and script lifecycle | RestrictedPython baseline, guard layering, the draft → verified → compiled → retired lifecycle, promotion rules, and the replay-only verification default. |
| Execution preference and fallback | Optimized plan first, then serving script, then LLM; a script failure never fails the run; live-test approval is per script and single-use. |
| Optimization triggers and approval | When optimize is offered, the successful-execution and authoring-model gates, and the approval intervention. Nothing re-optimizes unattended. |
| Conversation durability and chat UX | Persisted activity state, resume index and checkpoints, the answerable window, terminal vocabulary, and the chat error surface (including for failed turns). |
| Tenant isolation and permissions | Signed internal headers, fail-closed data-plane endpoints, tenant-scoped uniqueness, and all permission checks. |
| Identity and credentials | Agent identity resolution, certificate classes, token injection, and the rule that no token or credential appears in a contract snapshot. |
| Data-type CRUD basics | Immediate list refresh, edit pre-filled with current values, confirmation before delete, name available again after delete, duplicate names rejected, at least one field required. |
| MCP tool naming and routing | Namespaces, slugs, per-call token injection, and the MCP protocol surface. |
| Result validation on failure | A typed validation failure still completes the run, is recorded, and shows the raw result as the fallback. |
| Historical rendering | Previously recorded results render with their original payload; nothing is reinterpreted or retroactively validated. |

---

## 12. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **Consumers migrate out of step** | A half-migrated consumer re-introduces a per-surface result shape, defeating the epic. | Phase 3 migrates all consumers; Phase 7 adds a cross-surface consistency test that fails on divergence. |
| **Projection drift** (`fields` disagrees with the canonical definition) | Two definitions that disagree; readers see stale structure. | The definition is authoritative; the projection is regenerated in the same transaction; a reconcile check detects and repairs drift by regenerating from the definition. |
| **Legacy fidelity limit** | An exotic free-text schema cannot be expressed losslessly. | It stays readable and non-enforcing; the operator path is documented; nothing is blocked, and no queue or approval step is added. |
| **Snapshot freshness** | A data type edited mid-run produces an inconsistent evaluation. | The snapshot is immutable for the run; mid-execution re-resolution is explicitly refused; the next run picks up the change. |
| **Declared-type misconfiguration** | A genuinely typed workflow declared as text costs an optimization opportunity; free text declared as typed fails validation and falls back to raw rendering. | Misconfiguration is visible (validation status, declared type on every result), never silently repaired. In-dialog previews reduce mistakes. |
| **Legacy `typed` + legacy schema behaviour shift** | Agents that previously got provider structured output from a free-text schema now declare text and lose provider-level enforcement. | This is the approved removal of the legacy schema as an enforcement mechanism. The schema stays readable and can still inform the prompt, and operators are directed to a data type. |
| **Envelope leaking runtime bookkeeping into the payload** | Business payloads become unreadable and collide with envelope keys. | Guardrail usage, token usage, and model identifiers move to producer telemetry; envelope validation rejects business-level keys. |
| **Validation cost on large payloads** | Slower completion for big lists. | Validation runs once per result against the resolved schema; no per-field round trips; indexes support filtering. |
| **Double write on data-type save** | A partial write could leave the registry inconsistent. | Definition, projection, and child rows are written in one transaction; failure rolls back all three. |
| **Third-party contract tightening** | Clients sending payloads that were previously accepted now get 422. | Only agents with an input data type are affected (that was already a "typed" submit surface); errors are field-level and actionable; agents without a contract are unchanged. |
| **UI complexity in the editor** | Users cannot tell which definition will be saved. | The save path is single; a blocked banner names what the guided view cannot display; the resolved preview always shows the definition that will be written. |

---

## 13. Code Reference Map

### 13.1 New backend modules

| Symbol | Type | Description | File |
|---|---|---|---|
| `io_contract` | module | Pure contract layer: resolution, legacy adapter, snapshot, envelope build/normalise, scriptability, invariants. No datastore access. | `backend/app/services/agents/io_contract.py` |
| `DeclaredResultType` | enum | Product vocabulary for the declared result type (`text`, `markdown`, `json`, `typed`). | `backend/app/services/agents/io_contract.py` |
| `ContractSource` | enum | Origin of a resolved contract (`data_type`, `legacy_schema`, `none`). | `backend/app/services/agents/io_contract.py` |
| `ContractSnapshot` | model | Read-only snapshot handed to Agent Runtime: declared type, resolved input/output schema, data-type identity, schema version, boundary verdicts, schema prompt block. | `backend/app/services/agents/io_contract.py` |
| `resolve_contract` | function | Resolves an agent configuration plus its data types into a contract snapshot. | `backend/app/services/agents/io_contract.py` |
| `normalize_declared_result_type` | function | Maps a stored value to a declared result type, including legacy `auto`. | `backend/app/services/agents/io_contract.py` |
| `normalize_legacy_contract` | function | The single legacy read path: auto→text, typed-without-data-type→text, legacy schema surfacing. | `backend/app/services/agents/io_contract.py` |
| `build_contract_snapshot` | function | Assembles the snapshot, expanding one level of child references. | `backend/app/services/agents/io_contract.py` |
| `expand_child_references` | function | Expands the child-reference projection into resolved properties and list markers. | `backend/app/services/agents/io_contract.py` |
| `build_output_json_schema` | function | Builds the provider structured-output schema from the resolved contract (replaces the field-list-only builder). | `backend/app/services/agents/io_contract.py` |
| `build_output_schema_prompt` | function | Builds the system-prompt schema block from the resolved contract. | `backend/app/services/agents/io_contract.py` |
| `build_result_envelope` | function | Normalises a path outcome plus snapshot into the envelope. | `backend/app/services/agents/io_contract.py` |
| `normalize_result_envelope` | function | Normalises an already-shaped or legacy outcome into the canonical envelope. | `backend/app/services/agents/io_contract.py` |
| `validate_envelope` | function | Rejects business fields at envelope level and enforces envelope invariants. | `backend/app/services/agents/io_contract.py` |
| `assert_contract_invariants` | function | Enforces typed↔data-type, conversational, and tenant reference invariants on save. | `backend/app/services/agents/io_contract.py` |
| `is_scriptable_result_type` | function | Scriptable vs semantic bridge for a declared result type. | `backend/app/services/agents/io_contract.py` |
| `classify_boundary` | function | Boundary classification including legacy and delegated cases. | `backend/app/services/agents/io_contract.py` |
| `boundaries_allow_fully_scripted` | function | Advisory check that every boundary is typed or JSON. | `backend/app/services/agents/io_contract.py` |
| `ResultEnvelope` | model | Envelope model (status, result type, payload, validation status, contract, error, producer). | `backend/app/schemas/result_envelope.py` |
| `EnvelopeContractMetadata` | model | Contract block of the envelope. | `backend/app/schemas/result_envelope.py` |
| `EnvelopeError` | model | Error block of the envelope. | `backend/app/schemas/result_envelope.py` |
| `EnvelopeProducer` | model | Producer metadata and telemetry block. | `backend/app/schemas/result_envelope.py` |
| `schema_canonicalizer` | module | Guided field list ↔ canonical object schema conversion, child extraction, representability, drift detection. | `backend/app/services/data_types/schema_canonicalizer.py` |
| `fields_to_schema` | function | Projects the guided field list into the canonical definition. | `backend/app/services/data_types/schema_canonicalizer.py` |
| `schema_to_fields` | function | Projects the canonical definition into the guided field list. | `backend/app/services/data_types/schema_canonicalizer.py` |
| `extract_child_references` | function | Derives child-reference rows from a canonical definition. | `backend/app/services/data_types/schema_canonicalizer.py` |
| `is_guided_representable` | function | Reports whether the guided editor can fully display a definition. | `backend/app/services/data_types/schema_canonicalizer.py` |
| `detect_projection_drift` | function | Compares canonical definition and guided projection; returns field-level differences. | `backend/app/services/data_types/schema_canonicalizer.py` |
| `child_references` | module | Child-reference persistence and integrity rules. | `backend/app/services/data_types/child_references.py` |
| `ChildReferenceService` | class | Regenerates the projection for a parent and enforces same-tenant / one-level / no-self-reference. | `backend/app/services/data_types/child_references.py` |
| `sync_for_parent` | method | Wholesale, idempotent rewrite of one parent's child rows in the caller's transaction. | `backend/app/services/data_types/child_references.py` |
| `assert_insertable` | method | Validates a proposed child reference before it is written. | `backend/app/services/data_types/child_references.py` |
| `list_dependents` | method | Returns parent data types (with field names), agent types (input/output), and decision tools for a data type. | `backend/app/services/data_types/child_references.py` |

### 13.2 Backend — models and schemas

| Symbol | Type | Description | File |
|---|---|---|---|
| `AgentDataType` | model | Registry entity; gains the canonical definition, schema version, guided-representability, and child relationships; keeps the field list as a projection. | `backend/app/db/models/agent_data_type.py` |
| `AgentDataTypeChildReference` | model | Projection entity for one-level child references (parent, child, field name, list flag, tenant). | `backend/app/db/models/agent_data_type.py` |
| `AgentInputType` | enum | Input type vocabulary (`none`, `typed`, `conversation`); unchanged. | `backend/app/db/models/agents.py` |
| `AgentOutputType` | enum | Stored declared-result-type column vocabulary; gains `text` and `json`, keeps `auto`, `markdown`, `typed`. | `backend/app/db/models/agents.py` |
| `AgentType` | model | Gains the optional input data-type reference and relationship; keeps the declared-result-type column and legacy schema columns. | `backend/app/db/models/agents.py` |
| `AgentJob` | model | Session entity; gains the recorded declared result type and the result validation status; payload stays in the existing output column. | `backend/app/db/models/agents.py` |
| `AgentResultValidationStatus` | enum | Persisted validation vocabulary (`not_applicable`, `valid`, `validation_error`). | `backend/app/db/models/agents.py` |
| `AgentOutput` | model | Typed result record; gains the declared result type; keeps validation status, raw fallback, field values. | `backend/app/db/models/agent_output.py` |
| `AgentOutputValidationStatus` | enum | Existing typed-record validation vocabulary; unchanged. | `backend/app/db/models/agent_output.py` |
| `DataTypeFieldType` | enum | Primitive field types; gains the child-reference type. | `backend/app/schemas/data_types.py` |
| `DataTypeFieldCreate` | model | Field definition; gains list flag and child reference identifier. | `backend/app/schemas/data_types.py` |
| `DataTypeFieldResponse` | model | Field projection in responses; gains list flag and child identity. | `backend/app/schemas/data_types.py` |
| `DataTypeCreate` | model | Create payload; accepts a canonical definition or a guided field list. | `backend/app/schemas/data_types.py` |
| `DataTypeUpdate` | model | Update payload; same acceptance rules. | `backend/app/schemas/data_types.py` |
| `DataTypeResponse` | model | Detail response; gains canonical definition, guided-representability, and child references. | `backend/app/schemas/data_types.py` |
| `DataTypeUsageInfo` | model | Usage response; gains parent data types and agent types split by input and output. | `backend/app/schemas/data_types.py` |
| `DataTypeListResponse` | model | Paginated list; carries usage and referencing maps. | `backend/app/schemas/data_types.py` |
| `AgentTypeCreate` | model | Create payload; gains the input data-type identifier and invariant validation. | `backend/app/schemas/agents.py` |
| `AgentTypeUpdate` | model | Update payload; same. | `backend/app/schemas/agents.py` |
| `AgentTypeRead` | model | Read payload; gains the normalised declared result type, input data-type identity, and legacy markers. | `backend/app/schemas/agents.py` |
| `ValidateOutputRequest` | model | Payload validation request (data type + payload), used for input and output. | `backend/app/schemas/agent_outputs.py` |
| `ValidationResult` | model | Validation outcome (valid flag, field-level errors, status vocabulary). | `backend/app/schemas/agent_outputs.py` |
| `AgentOutputCreate` | model | Typed output write payload; gains the declared result type. | `backend/app/schemas/agent_outputs.py` |
| `AgentOutputResponse` | model | Typed output read payload; gains the declared result type. | `backend/app/schemas/agent_outputs.py` |

### 13.3 Backend — services

| Symbol | Type | Description | File |
|---|---|---|---|
| `DataTypeService` | class | Registry CRUD; becomes the single write path for definition + projection + child rows. | `backend/app/services/data_types/service.py` |
| `DataTypeService.create` | method | Creates a data type from either editor view and regenerates the projection. | `backend/app/services/data_types/service.py` |
| `DataTypeService.update` | method | Updates a data type, regenerates the projection, returns dependent parents. | `backend/app/services/data_types/service.py` |
| `DataTypeService.delete` | method | Deletion with the extended dependent checks. | `backend/app/services/data_types/service.py` |
| `DataTypeService.reconcile_projection` | method | Detects and repairs drift by regenerating from the canonical definition. | `backend/app/services/data_types/service.py` |
| `DataTypeService._get_referencing_agent_types` | method | Dependent agent types; extended to input assignments and named field detail. | `backend/app/services/data_types/service.py` |
| `DataTypeService._get_referencing_decision_tools` | method | Dependent decision tools; unchanged semantics, included in named errors. | `backend/app/services/data_types/service.py` |
| `DataTypeConflictError` | exception | Carries the named dependents for a 409 response. | `backend/app/services/data_types/service.py` |
| `SchemaValidationService` | class | Field-level payload validation against a data type; re-used for input and output. | `backend/app/services/validation/schema_validation_service.py` |
| `OutputService` | class | Typed output persistence and querying; gains the declared result type. | `backend/app/services/outputs/service.py` |
| `ResultStore` | class | Result repository writes; content type derived from the declared result type. | `backend/app/services/results/store.py` |
| `OptimizedPlanService` | class | Plan persistence; validates step contracts and carries per-step declared types. | `backend/app/services/agents/optimized_plan_service.py` |
| `OptimizedPlanService.generate_optimized_plan` | method | Upserts the optimized plan after step-contract validation. | `backend/app/services/agents/optimized_plan_service.py` |
| `OptimizedPlanService._upsert_optimized_plan` | method | Stores the plan payload including per-step declared result types. | `backend/app/services/agents/optimized_plan_service.py` |

### 13.4 Backend — internal APIs

| Symbol | Type | Description | File |
|---|---|---|---|
| `get_agent_context` | endpoint | Returns the execution context including the contract snapshot. | `backend/app/api/v1/internal/agent_data.py` |
| `AgentContextResponse` | model | Context response; gains the contract snapshot, keeps deprecated aliases. | `backend/app/api/v1/internal/agent_data.py` |
| `_build_output_json_schema` | function | Existing field-list-only builder; delegates to the contract module or is removed. | `backend/app/api/v1/internal/agent_data.py` |
| `_build_output_schema_prompt` | function | Existing prompt builder; delegates to the contract module or is removed. | `backend/app/api/v1/internal/agent_data.py` |
| `_build_agent_delegation_tool_definition` | function | Builds the delegation tool schema; input schema now resolved from the input contract. | `backend/app/api/v1/internal/agent_data.py` |
| `validate_output` | endpoint | Payload validation against a data type (input and output). | `backend/app/api/v1/internal/outputs.py` |
| `create_internal_output` | endpoint | Typed output write; accepts the declared result type. | `backend/app/api/v1/internal/outputs.py` |
| `query_internal_outputs` | endpoint | Typed output query; supports result-type and validation-status filters. | `backend/app/api/v1/internal/outputs.py` |
| `post_session_result` | endpoint | Result-write completion; persists envelope facts and repository content type. | `backend/app/api/v1/internal/session_data.py` |
| `update_session_status` | endpoint | Completion/failure transition; persists envelope facts, keeps terminal-state guards. | `backend/app/api/v1/internal/session_data.py` |
| `_dispatch_result_to_comm_hub` | function | Relays the envelope to the hub after commit. | `backend/app/api/v1/internal/session_data.py` |
| `prepare_a2a_request` | endpoint | Prepares a delegation request; now validates the delegated input against the child's resolved input contract before preparing the child run. | `backend/app/api/v1/internal/session_data.py` |
| `SessionResultRequest` | model | Result payload; gains declared result type and validation status. | `backend/app/api/v1/internal/session_data.py` |
| `SessionStatusUpdateRequest` | model | Status payload; gains declared result type, validation status, and envelope payload. | `backend/app/api/v1/internal/session_data.py` |
| `get_execution_log_tool` | endpoint | Returns reference result and contract in addition to input/transcript/text. | `backend/app/api/v1/internal/optimization_tools.py` |
| `generate_optimized_plan_tool` | endpoint | Validates step contracts and rejects untruthful fully-scripted claims. | `backend/app/api/v1/internal/optimization_tools.py` |
| `execute_script_tool` | endpoint | Replay verification with result-contract checking; remains replay-only. | `backend/app/api/v1/internal/optimization_tools.py` |
| `_validate_script_input_context` | function | Resolves required input keys from the input contract, with legacy fallback. | `backend/app/api/v1/internal/optimization_tools.py` |
| `_reference_input` | function | Existing reference-input extraction (internal routing keys stripped); unchanged. | `backend/app/api/v1/internal/optimization_tools.py` |
| `_tool_calls_from_entries` | function | Existing replay-transcript extraction; unchanged. | `backend/app/api/v1/internal/optimization_tools.py` |
| `_serialize_agent_type` | function | Management-panel serialisation; gains declared result type, contracts, and legacy markers. | `backend/app/api/v1/internal/management_tools.py` |
| `_serialize_data_type` | function | Management serialisation; gains the canonical definition and child references. | `backend/app/api/v1/internal/management_tools.py` |
| `_validate_data_type_fields` | function | Management-side data-type validation; extended for the canonical definition and child rules. | `backend/app/api/v1/internal/management_tools.py` |
| `_validate_conversational_output_conflict` | function | Existing conversational conflict rule; extended to the new invariants (the create/update paths call it with the resolved declared result type and both data-type identifiers). | `backend/app/api/v1/internal/management_tools.py` |
| `_build_create` | function | Assistant create builder; passes the new fields through. | `backend/app/api/v1/internal/management_tools.py` |
| `_update_resource` | function | Assistant update path; applies the new fields and invariants. | `backend/app/api/v1/internal/management_tools.py` |
| `validate_client_internal` | endpoint | Client validation; returns the resolved input contract to the gateway. | `backend/app/api/v1/internal/agent_client_validation.py` |
| `invoke_client_agent` | endpoint | Validates typed input against the input contract before enqueue. | `backend/app/api/v1/internal/agent_client_invoke.py` |
| `get_client_session` | endpoint | Returns the envelope-shaped result for polling clients. | `backend/app/api/v1/internal/agent_client_invoke.py` |
| `query_result_tool` | endpoint | Existing typed-output query tool; reads the declared result type. | `backend/app/api/v1/internal/system_tools.py` |

### 13.5 Backend — public APIs

| Symbol | Type | Description | File |
|---|---|---|---|
| `DataTypeRouter` | router | Registry routes under `/data-types`. | `backend/app/api/v1/data_types.py` |
| `list_data_types` | endpoint | List with canonical definition summary and expanded usage. | `backend/app/api/v1/data_types.py` |
| `create_data_type` | endpoint | Create from either editor view. | `backend/app/api/v1/data_types.py` |
| `get_data_type` | endpoint | Detail with canonical definition, representability, and dependents. | `backend/app/api/v1/data_types.py` |
| `update_data_type` | endpoint | Update with projection regeneration and child-rule validation. | `backend/app/api/v1/data_types.py` |
| `delete_data_type` | endpoint | Delete with named dependents. | `backend/app/api/v1/data_types.py` |
| `validate_data_type_source` | endpoint | **new** — validate-only source definition; no persistence. | `backend/app/api/v1/data_types.py` |
| `create_agent_type` | endpoint | Create with contract invariants. | `backend/app/api/v1/agents.py` |
| `update_agent_type` | endpoint | Update with contract invariants and legacy-row tolerance. | `backend/app/api/v1/agents.py` |
| `get_agent_type` | endpoint | Read with resolved contract and legacy markers. | `backend/app/api/v1/agents.py` |
| `list_agent_types` | endpoint | List with declared result type and contracts. | `backend/app/api/v1/agents.py` |
| `list_results` | endpoint | Result repository list, envelope-backed, filterable by result type and validation status. | `backend/app/api/v1/results.py` |
| `get_result` | endpoint | Result detail, envelope-backed. | `backend/app/api/v1/results.py` |
| `list_agent_outputs` | endpoint | Typed output list with result type and validation filters. | `backend/app/api/v1/agent_outputs.py` |
| `list_auto_agent_outputs` | endpoint | Envelope-backed non-typed result list. | `backend/app/api/v1/agent_outputs.py` |
| `export_agent_outputs_csv` | endpoint | Export including result type and validation status. | `backend/app/api/v1/agent_outputs.py` |
| `AdminAgentClientRouter` | router | Client management routes under `/clients`; unchanged except contract exposure in read payloads. | `backend/app/api/v1/agent_clients.py` |

### 13.6 Agent Runtime and Communication Hub

| Symbol | Type | Description | File |
|---|---|---|---|
| `AgentRuntimeExecutor` | class | Executes sessions; every path normalises into the envelope. | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor.run` | method | Entry point; builds the envelope after the LLM loop and drives typed persistence. | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._run_task_loop_ar` | method | LLM loop; returns the raw outcome to the normaliser instead of path-specific shapes. | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._run_task_loop` | method | Legacy in-process loop used by the Control Center path; same normalisation contract. | `backend/app/services/agents/runtime_executor.py` |
| `_extract_structured_output` | function | Existing structured-output extraction; feeds the normaliser. | `backend/app/services/agents/runtime_executor.py` |
| `_raw_output_for_failed_validation` | function | Raw fallback extraction for a failed validation; reused unchanged. | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._format_user_prompt` | method | Prompt composition; output instruction derived from the resolved contract instead of the legacy schema. | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._resolve_content_type` | method | Content-type derivation; aligned to the declared result type (or removed in favour of the repository rule). | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor.execute_conversation_turn` | method | Conversational turn entry; builds the internal-only envelope. | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._run_conversation_turn` | method | Turn execution; envelope recorded in logs and diagnostics only. | `backend/app/services/agents/runtime_executor.py` |
| `ControlCenterDataClient` (AR) | class | Internal HTTP client used by Agent Runtime; no datastore access. | `backend/app/agent_runtime/data_client.py` |
| `ControlCenterDataClient.validate_typed_output` | method | Calls payload validation for input and output. | `backend/app/agent_runtime/data_client.py` |
| `ControlCenterDataClient.persist_typed_output` | method | Persists the typed output record with the declared result type. | `backend/app/agent_runtime/data_client.py` |
| `ControlCenterDataClient.mark_session_completed` | method | Reports completion with the envelope. | `backend/app/agent_runtime/data_client.py` |
| `ControlCenterDataClient.mark_session_failed` | method | Reports failure with the envelope error block. | `backend/app/agent_runtime/data_client.py` |
| `ControlCenterDataClient.save_output` | method | Alternate result-write path; envelope-aware. | `backend/app/agent_runtime/data_client.py` |
| `run_session_script_first` | function | Script-first entry; routes to scripted or LLM path. | `backend/app/agent_runtime/scripts/dispatch.py` |
| `_run_script_path` | function | Script execution; checks step contracts, treats mismatch as fallback, builds the envelope. | `backend/app/agent_runtime/scripts/dispatch.py` |
| `_run_sandboxed_script_path` | function | Sandboxed script path; same envelope and contract handling. | `backend/app/agent_runtime/scripts/dispatch.py` |
| `_attempt_script` | function | One script attempt; returns the raw result and telemetry. | `backend/app/agent_runtime/scripts/dispatch.py` |
| `_report_success_execution` | function | Script execution accounting; unchanged except the envelope is persisted by the caller. | `backend/app/agent_runtime/scripts/dispatch.py` |
| `ScriptRunner` | class | Executes steps; reports step telemetry and contract-checkable results. | `backend/app/agent_runtime/scripts/runner.py` |
| `BaseStep` | model | Step definition; gains declared input/output contract fields. | `backend/app/agent_runtime/scripts/schemas.py` |
| `StepGraph` | model | Composition of steps; validation path for declared step contracts. | `backend/app/agent_runtime/scripts/schemas.py` |
| `build_langchain_tools_for_ar_path` | function | Builds runtime tools; the delegation branch returns the child envelope with its declared type. | `backend/app/services/agents/langchain_tool_wrapper.py` |
| `_wait_for_receiver_result` | function | Waits for the child result and returns the envelope unchanged, including failures. | `backend/app/communication_hub/api/a2a.py` |
| `submit` | endpoint | Third-party typed submit; forwards input for contract validation. | `backend/app/communication_hub/api/integration_gateway.py` |
| `get_session` | endpoint | Third-party poll; returns the envelope. | `backend/app/communication_hub/api/integration_gateway.py` |
| `get_config` | endpoint | Client configuration; returns the resolved input contract. | `backend/app/communication_hub/api/integration_gateway.py` |

### 13.7 Prompt assets

| Symbol | Type | Description | File |
|---|---|---|---|
| `OPTIMIZE_AND_VERIFY_COMMAND` | constant | Optimizer mission text; gains contract and semantic-bridge guidance. | `backend/app/services/agents/command_prompts.py` |
| `build_command_mission` | function | Builds the command mission; appends the reference result and contract guidance. | `backend/app/services/agents/command_prompts.py` |
| `OPTIMIZATION_CONVERSATION_RULES` | constant | Optimization-mode conversation rules; gains the same guidance. | `backend/app/services/agents/optimization_mode.py` |
| `require_subject_match` | function | Subject-scope guard for optimization tools; unchanged. | `backend/app/services/agents/optimization_mode.py` |

### 13.8 Frontend

| Symbol | Type | Description | File |
|---|---|---|---|
| `AgentDataType` | interface | Registry type; gains canonical definition, representability, child references, list flags. | `frontend/src/types/index.ts` |
| `AgentDataTypeField` | interface | Field type; gains the list flag and child reference. | `frontend/src/types/index.ts` |
| `DataTypeFieldType` | type | Field type union; gains the child-reference member. | `frontend/src/types/index.ts` |
| `ReferencingAgentType` | interface | Consumer reference; extended with the reference kind (input, output, child) and field name. | `frontend/src/types/index.ts` |
| `DataTypeCreate` / `DataTypeUpdate` | interface | Mutation payloads; accept the canonical definition or source mode. | `frontend/src/types/index.ts` |
| `DataTypeListResponse` | interface | List response; carries expanded usage maps. | `frontend/src/types/index.ts` |
| `AgentType` | interface | Agent type; gains `input_data_type_id`, `input_data_type_name`, legacy markers. | `frontend/src/types/index.ts` |
| `AgentJob` | interface | Session; gains declared result type and validation status. | `frontend/src/types/index.ts` |
| `AgentOutputResponse` | interface | Typed output; gains the declared result type. | `frontend/src/types/index.ts` |
| `useDataTypes` | hook | Registry list query. | `frontend/src/hooks/useDataTypes.ts` |
| `useDataTypesWithUsage` | hook | Registry list with usage. | `frontend/src/hooks/useDataTypes.ts` |
| `useDataType` | hook | Registry detail query. | `frontend/src/hooks/useDataTypes.ts` |
| `useCreateDataType` | hook | Create mutation; invalidates data types, agent types, decision tools. | `frontend/src/hooks/useDataTypes.ts` |
| `useUpdateDataType` | hook | Update mutation; same invalidation. | `frontend/src/hooks/useDataTypes.ts` |
| `useDeleteDataType` | hook | Delete mutation; same invalidation. | `frontend/src/hooks/useDataTypes.ts` |
| `fetchDataTypeUsage` | function | Loads dependents for the delete dialog. | `frontend/src/hooks/useDataTypes.ts` |
| `useAgentTypes` | hook | Agent-type list query; invalidated by data-type mutations. | `frontend/src/hooks/useAgentTypes.ts` |
| `useAgentType` | hook | Agent-type detail query; invalidated by data-type mutations. | `frontend/src/hooks/useAgentTypes.ts` |
| `DataTypesPage` | component | Registry list with consumers, usage, legacy markers, empty state. | `frontend/src/pages/data-types/DataTypesPage.tsx` |
| `DataTypeFormDialog` | component | Registry editor: tabs, list toggle, child picker, preview, consumer warning, blocked delete. | `frontend/src/components/agents/DataTypeFormDialog.tsx` |
| `DataTypeSchemaSourceEditor` | component | **new** — source view: paste, validate, apply to guided fields, copy, non-representable notice. | `frontend/src/components/agents/DataTypeSchemaSourceEditor.tsx` |
| `DataTypeContractPreview` | component | **new** — read-only contract preview (fields, types, allowed values, required, list, one child level) used by the agent type dialog. | `frontend/src/components/agents/DataTypeContractPreview.tsx` |
| `EnumValuesEditor` | component | Allowed-value editor; unchanged behaviour, used for list fields too. | `frontend/src/components/agents/EnumValuesEditor.tsx` |
| `JsonSchemaBuilder` | component | Legacy free-text input-schema builder; retained for read-only legacy display only. | `frontend/src/components/JsonSchemaBuilder.tsx` |
| `AgentTypeForm` | component | Input contract slot, explicit declared result type, invariant validation. | `frontend/src/pages/agents/AgentTypeForm.tsx` |
| `AgentTypeFormValues` | interface | Form draft shape; gains the input data-type identifier. | `frontend/src/pages/agents/AgentTypeForm.tsx` |
| `defaultAgentTypeFormValues` | constant | Defaults; no longer default to `auto`. | `frontend/src/pages/agents/AgentTypeForm.tsx` |
| `AgentTypeDetailsDialog` | component | Hosts the contract preview and the result tab. | `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` |
| `AgentJobLaunchDialog` | component | Launch surface; renders the structured input form when an input contract exists. | `frontend/src/pages/agents/AgentJobLaunchDialog.tsx` |
| `StructuredInputForm` | component | **new** — contract-derived form: nested child groups, repeatable list rows, typed controls, field-level validation. | `frontend/src/components/agents/StructuredInputForm.tsx` |
| `flattenContractFields` | function | Flattens a contract to renderable rows with one child level expanded. | `frontend/src/utils/dataTypeContract.ts` |
| `initialStructuredInput` | function | Builds the empty draft for a contract, including one row per required list. | `frontend/src/utils/dataTypeContract.ts` |
| `validateStructuredInput` | function | Client-side pre-validation mirroring the server rules; the server stays authoritative. | `frontend/src/utils/dataTypeContract.ts` |
| `ResultTypeChip` | component | **new** — consistent result-type badge across execution log, repository, outputs, and launch result. | `frontend/src/components/executions/ResultTypeChip.tsx` |
| `OutputTypeResultTab` | component | Result rendering driven by the envelope and declared result type. | `frontend/src/components/executions/OutputTypeResultTab.tsx` |
| `badgeForType` | function | Badge derivation; replaced by the declared result type rather than the stored output type. | `frontend/src/components/executions/OutputTypeResultTab.tsx` |
| `extractResultText` | function | Payload text extraction; reads the envelope payload. | `frontend/src/components/executions/OutputTypeResultTab.tsx` |
| `normalizeRawOutput` | function | Raw fallback normalisation for validation failures; retained. | `frontend/src/components/executions/OutputTypeResultTab.tsx` |
| `TypedOutputRenderer` | component | Structural rendering of a typed payload against field definitions; supports list and child fields. | `frontend/src/components/executions/TypedOutputRenderer.tsx` |
| `MarkdownRenderer` | component | Markdown rendering for the markdown result type; unchanged. | `frontend/src/components/common/MarkdownRenderer.tsx` |
| `ResultRepositoryPage` | component | Repository list with result-type and validation filters. | `frontend/src/pages/results/ResultRepositoryPage.tsx` |
| `AgentOutputsPage` | component | Typed and non-typed output lists with result-type and validation columns. | `frontend/src/pages/agent-outputs/AgentOutputsPage.tsx` |
| `AgentOutputDetailDrawer` | component | Output detail; shows the declared result type and validation status. | `frontend/src/pages/agent-outputs/AgentOutputDetailDrawer.tsx` |
| `AgentExecutionDetailsDialog` | component | Execution log result tab host; passes envelope facts to the renderer. | `frontend/src/components/agents/AgentExecutionDetailsDialog.tsx` |
| `DecisionToolForm` | component | Decision-tool configuration; schema display inherits child/list/source; selection stays read-only. | `frontend/src/components/decisionTools/DecisionToolForm.tsx` |
| `PermissionDeniedAlert` | component | Inline 403 surface rendered first in a dialog body, per the project dialog error standard. | `frontend/src/components/permissions/PermissionDeniedAlert.tsx` |

### 13.9 Tests to extend

| Symbol | Type | Description | File |
|---|---|---|---|
| `test_data_types_api` | suite | Registry CRUD; extend for canonical definitions, child rules, list fields, source validation, delete protection. | `backend/tests/test_data_types_api.py` |
| `test_output_validation` | suite | Payload validation; extend for input validation and expanded types. | `backend/tests/test_output_validation.py` |
| `test_agent_outputs_api` | suite | Typed outputs; extend for the declared result type and filters. | `backend/tests/test_agent_outputs_api.py` |
| `test_script_first_dispatcher` | suite | Dispatcher behaviour; extend for step contracts and fallback triggers. | `backend/tests/test_script_first_dispatcher.py` |
| `test_dispatcher_script_context` | suite | Script context binding; extend for input-contract-derived keys. | `backend/tests/test_dispatcher_script_context.py` |
| `test_execute_script_sandbox_segregation` | suite | Sandbox segregation; extend to assert replay still performs no live calls. | `backend/tests/api/v1/internal/test_execute_script_sandbox_segregation.py` |
| `test_session_status_string_output` | suite | String payload completion; must stay passing (raw script result). | `backend/tests/api/v1/internal/test_session_status_string_output.py` |
| `DataTypesPage.test` | suite | Registry page; extend for consumers, usage, legacy markers, empty state. | `frontend/src/__tests__/DataTypesPage.test.tsx` |
| `DataTypeFormDialog.test` | suite | Editor; extend for tabs, source-only handling, child constraints, list toggle, consumer warning. | `frontend/src/__tests__/DataTypeFormDialog.test.tsx` |
| `AgentTypeForm.test` | suite | Agent type form; extend for input contract and declared result type invariants. | `frontend/src/__tests__/AgentTypeForm.test.tsx` |
| `AgentTypeDetailsDialog.test` | suite | Details dialog; extend for the contract preview. | `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx` |
| `AgentSessionLaunchDialog.test` | suite | Launch dialog; extend for structured input and field-level validation. | `frontend/src/__tests__/AgentSessionLaunchDialog.test.tsx` |
| `OutputTypeResultTab.test` | suite | Result rendering; extend for every declared result type, validation fallback, and failure. | `frontend/src/__tests__/OutputTypeResultTab.test.tsx` |
| `AgentOutputsPage.test` | suite | Outputs page; extend for result-type and validation columns. | `frontend/src/__tests__/AgentOutputsPage.test.tsx` |
| `DecisionToolForm.test` | suite | Decision tools; extend for child/list schema display and read-only selection. | `frontend/src/__tests__/DecisionToolForm.test.tsx` |
| `AgentExecutionDetailsDialog.test` | suite | Execution log; extend for envelope-driven rendering. | `frontend/src/__tests__/AgentExecutionDetailsDialog.test.tsx` |
