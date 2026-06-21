# Specification Delta: Enhance Agent Output System

## Affected Spec Areas

| Spec Area | Description of Change |
|-----------|----------------------|
| Agent Types (`docs/master/product/features/agent-types.md`) | Add data type assignment to Agent Type configuration; output type field now links to a registry data type instead of inline enum; agent types gain optional "Output Data Type" selection |
| Agent Execution (`docs/master/product/features/agent-execution.md`) | Update execution flow for typed outputs — schema validation on completion; update `save_result` tool behavior; add `query_result` system tool |
| Agent Session Logs (`docs/master/product/features/agent-session-logs.md`) | Execution log Result tab must render typed outputs using schema-driven field-by-field display; add data type name badge to Result tab label |
| Result Management (`docs/master/product/features/result-management.md`) | Extend from simple save/query to include typed result storage, schema-linked persistence, and the `query_result` tool; add Agent Outputs admin page |
| Navigation / Admin UI (`docs/master/product/features/agent-management.md` or product README) | New "Agent Outputs" page accessible from admin navigation with filtering and data type schema-based table display |

---

## New Capabilities

1. **Agent Data Type Registry** — A centralized, reusable data type catalogue where administrators define flat-typed schemas (string, number, boolean, date, enum fields). Data types are created, edited, and deleted independently of agent types. The registry is managed via a dedicated UI page with full CRUD lifecycle.

2. **Typed Agent Output Assignment** — The Agent Type create/edit form gains an "Output Data Type" selector. When a data type is assigned, the agent type becomes a typed-output agent. Conversational agent types do not show this field. The agent type's output type badge in list views displays the assigned data type name.

3. **Schema-Validated Agent Execution** — When a non-conversational agent with an assigned output type completes, its result is validated against the data type schema before persistence. If validation passes, the typed result is saved with a schema reference. If validation fails, the execution completes but a validation error is recorded and surfaced in the execution log.

4. **Schema-Aware Execution Log Rendering** — The execution log Result tab renders typed outputs as a structured field-by-field view. Fields display labels and values formatted by their defined type (booleans as toggles, dates as formatted dates, enums as chips, etc.). A data type name badge appears in the tab label. Schema validation errors are shown prominently with a raw-output fallback.

5. **Agent Outputs Admin Page** — A dedicated page listing all saved agent outputs with filtering by data type, date range, and agent type. Results display in a configurable table that adapts its columns to the selected data type's schema. CSV export is available for filtered results. Clicking a row opens a detail view with full schema-based field rendering.

6. **`query_result` System Tool** — A new `system____query_result` tool exposed to all agents, accepting a data type name and optional filters. It returns matching typed results conforming to the requested schema. This enables result-analysis agent types that reason across past outputs.

---

## Modified Capabilities

| Capability | Before | After |
|------------|--------|-------|
| Agent Type Output Configuration | Output type is an inline enum (`auto`, `markdown`, `typed`) with no schema linkage | Output type can optionally link to a registry data type; when linked, the `typed` option carries the schema reference and drives validation and rendering |
| `save_result` System Tool | Persists results as opaque blobs without schema context | Persists results with a reference to the data type schema; typed results are stored with their individual field values queryable by schema |
| Execution Log Result Tab | Displays raw agent output as text/JSON regardless of output type | Detects typed output and renders a field-by-field structured view following the data type schema; untyped outputs continue to display as plain text |
| Result Management | Simple save/query with no type discoverability; results are opaque | Results are typed and linked to a data type schema; queryable by data type, date range, and agent type; exposed via both UI and the `query_result` tool |
| Agent Execution Completion | Result is saved as-is without validation | Result is validated against the data type schema; validation errors are recorded and surfaced in the execution log without aborting the execution |

---

## Removed Capabilities

None. All existing capabilities are preserved and extended. Untyped agent types and their execution workflows remain fully functional — only agent types with an explicitly assigned data type are affected by the new validation and rendering behavior.

---

## Spec Update Instructions

1. **`docs/master/product/features/agent-types.md`**:
   - Add the "Output Data Type" assignment capability to the "What It Does" section — describe how administrators select a data type from the registry for each non-conversational agent type.
   - Update the acceptance criteria to include: data type selection in the agent type form, non-conversational-only enforcement, and the data type name badge on agent type list views.

2. **`docs/master/product/features/agent-execution.md`**:
   - Update the "Explicit Result Saving" section to describe the enhanced `save_result` tool that persists typed outputs with schema references.
   - Add a new section describing schema validation on execution completion — what happens on validation pass vs. failure.
   - Add a new section describing the `query_result` system tool, its purpose, and the explicit-trigger pattern.

3. **`docs/master/product/features/agent-session-logs.md`**:
   - Update the acceptance criteria around the Result tab to describe schema-driven field-by-field rendering for typed outputs.
   - Add: the data type name badge on the Result tab label, validation error display, and the behavior for untyped output fallback.

4. **`docs/master/product/features/result-management.md`**:
   - Rewrite the overview to include typed outputs, schema-linked persistence, and the Agent Outputs admin page.
   - Add the new Agent Outputs page with filtering and CSV export to the "What It Does" section.
   - Add user stories for: querying results by data type, browsing the Agent Outputs page, and analysis agents using `query_result`.
   - Update acceptance criteria to cover: schema-linked result persistence, filtered queries, CSV export, and the `query_result` tool availability.

5. **Admin Navigation (product README or `docs/master/product/features/agent-management.md`)**:
   - Add "Agent Outputs" as a new navigation entry under the Agents group in the admin sidebar.
   - Describe the page's purpose: browse, filter, and export typed agent outputs.

6. **Master architecture docs** (`docs/master/architecture/`):
   - Add a new "Agent Data Type Registry" component under Control Center's responsibility with read-only access from Agent Runtime for schema validation.
   - Add the `query_result` tool as a new system tool routed through the existing MCP tool flow.

7. **Master data model docs** (`docs/master/data-model/`):
   - Add new entities for Data Type (name, description, field definitions) and Typed Result (data type reference, field values, agent type reference, session reference, status).

8. **Master tech spec updates** (`docs/master/technology/`):
   - Add code reference map entries for: new data type CRUD endpoints/forms, updated agent type form with output data type selector, typed result validation service, schema-aware execution log renderer, Agent Outputs page components, `query_result` tool implementation.
   - Mark the enhanced `save_result` tool with updated reference paths.
