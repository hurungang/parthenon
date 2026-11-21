# Spec Change: Unified Agent I/O Contract

## Affected Spec Areas

| Master spec area | Impact |
|---|---|
| [Agent Data Type Registry](../../master/product/features/agent-data-types.md) | Contract unit for input and output; one-level child references; list fields; schema source view; expanded deletion/edit safeguards. |
| [Agent Outputs](../../master/product/features/agent-outputs.md) | Typed payload inside the universal envelope; consistent content type and validation reporting. |
| [Agent Execution](../../master/product/features/agent-execution.md) | One result envelope on every execution path, including failure. |
| [Agent Types](../../master/product/features/agent-types.md) | Explicit, enforced result type; assignable input data type. |
| [Agent Management](../../master/product/features/agent-management.md) | In-dialog schema preview; input slot as a data type; structured input entry at launch. |
| [Agent Session Logs](../../master/product/features/agent-session-logs.md) | Result tab renders from the envelope and declared result type. |
| [Software 3.0 Agent Framework](../../master/product/features/software-3-0-agent-framework.md) | Result-type-aware scriptability verdict; optimizer sees the reference run's result and contract. |
| [Sandboxed Scripting & Model-Authored Composition](../../master/product/features/sandboxed-scripting.md) | Script results and steps declared in the envelope; fully-scripted claim requires typed or JSON boundaries. |
| [Agent Plan Mode](../../master/product/features/agent-plan-mode.md) | Plan contracts record the declared result type per step and per hand-off. |
| [Decision Tools](../../master/product/features/decision-tools.md) | Inherits child references, list fields, and the source view; still read-only registry selection. |
| [Third-Party Agent Integration](../../master/product/features/third-party-agent-integration.md) | Typed submissions validate against the input data type; responses use the envelope. |
| [Control Center Assistant](../../master/product/features/control-center-assistant.md) | Conversational data type management at parity with the expanded definition model. |
| [Data Model — Agents](../../master/data-model/modules/agents/entities.md) | `AgentDataType` becomes an input-and-output contract with child references and list flags; `AgentType` gains input data type and explicit result type; `AgentOutput` records result type and envelope context. |
| [UX — Master Prototype](../../master/ux/README.md) | Data type editor (guided + source), in-dialog preview, structured input entry, result rendering. |
| [UX — Agent Session Log UI](../../master/ux/agent-session-log-ui.md) | Result rendering shows the declared result type and reads the payload from the envelope. |

## New Capabilities

- **Universal result envelope.** Every execution path returns execution status, declared result type, result payload, and contract metadata; business fields live only inside the payload, and failures return the envelope.
- **Explicit result type.** Text, markdown, JSON, or typed is a deliberate setting; "typed" requires a data type and a data type requires "typed".
- **Input contracts.** A registry data type assignable to a non-conversational agent type as its input contract, validated before the run starts.
- **One level of child data types.** A field may reference another data type as a single value or a list; deeper nesting is rejected and a referenced child cannot be deleted.
- **List fields.** Any field — primitive or child reference — can be a list.
- **Schema source view.** A source view alongside the guided field editor, over one definition, with explicit handling of definitions the guided view cannot display.
- **In-dialog contract preview.** Read-only preview of the selected input and output data type schemas inside the agent type dialog.
- **Structured input entry.** A form derived from the input data type — nested groups, repeatable rows, allowed-value choices, field-level validation.
- **Result-type-aware scriptability.** Delegation records the delegated result type, optimization receives the reference result and contract, and a workflow is only fully scriptable when every boundary is typed or JSON.

## Modified Capabilities

| Capability | Before | After |
|---|---|---|
| Result shape per execution path | LLM, fully-scripted, delegated, conversational, and failed runs each returned a different shape; consumers guessed the structure | One envelope for every path, with status, declared result type, payload, and contract metadata; failures return the same shape |
| Result type determination | Inferred from a combination of the output-type setting, the presence of a data type, a legacy free-text schema, and the path that ran; "typed" without a data type was prompt-only and "auto" with a data type produced typed output silently | Declared explicitly as text, markdown, JSON, or typed; typed requires a data type and a data type requires typed — impossible states cannot be saved |
| Data type role | Output-only schemas referenced by non-conversational agent types | Single contract unit used for input and output on non-conversational agent types |
| Data type field model | Flat fields only: string, number, boolean, date, enum with allowed values; nested/composite types out of scope | Same primitives plus one level of child data type reference (same tenant only) and list fields on any field |
| Data type editing | Guided field form only; schemas could not be pasted or copied | Guided field editor and schema source view over one definition, with explicit handling of non-representable content |
| Contract confirmation in the agent type dialog | Output data type selected without seeing its schema; no way to inspect the input contract | Selected input and output data type schemas previewed read-only inside the dialog, updating on selection |
| Typed input authoring | Hand-authored free-form input schema; a multi-part value such as a passenger list had to be one comma-separated, unvalidated string | Input defined by a registry data type; entered as structured groups and repeatable rows, validated before the run starts |
| Delegation hand-off | Parent received an untyped value (often markdown) with no way to know whether it was parseable | Hand-off carries the declared result type and typed envelope, so the parent and optimizer can distinguish parseable payloads from free text |
| Optimization's view of a reference run | Optimizer lacked the reference execution's result and contract, so it predicted the final format and scriptability from assumptions | Optimizer receives the reference result and its declared contract; markdown/free-text boundaries are semantic and never count as fully scriptable |
| Content type consistency | The same result was described as plain text in one layer and JSON in another | One content type per result across execution logs, the result repository, delegation, and third-party delivery |
| Result repository and rendering | Typed, auto, and markdown results were handled by separate render paths keyed off the output-type setting | All results render from the envelope and its declared result type, with the type visible to the operator |
| Third-party typed submission | Input validated against a hand-authored free-form schema; response shape mirrored internal path quirks | Input validated against the agent's input data type; delivered response uses the same envelope with result type and validation status |
| Data type lifecycle safeguards | Deletion blocked while referenced by agent types or decision tools | Deletion also blocked while referenced as a child by a parent data type, with dependents named; editing a child warns that all consumers are affected |

## Removed Capabilities

- **Implicit result-type inference.** The output type is no longer derived from the presence or absence of a data type, nor from a legacy free-text schema.
- **Legacy free-text output schema as an enforcement mechanism.** It remains readable for compatibility, but it no longer defines or enforces the result contract; operators are directed to a data type.
- **Free-text-only typed input.** Hand-authored free-form input schemas are no longer the primary way to define an input contract; structured data types take their place (legacy definitions remain readable).
- **Unqualified "fully scriptable" verdicts.** A workflow may no longer be declared fully scriptable while any boundary returns markdown or free text.

## Compatibility Rules

- **Legacy `auto` is readable, not offered.** Existing agents keep `auto`; it is normalised on read to text (free text; a markdown-looking body is not reclassified). New agent configurations choose an explicit result type and do not rely on implicit `auto`.
- **Failed conversational turns add no new chat UX.** The envelope is carried internally and in logs; the existing conversational error surfaces are unchanged.
- **Legacy free-text schemas stay readable.** No review queue, approval step, or triage backlog is introduced; operators get a documented migration path and a read-only migration note where conversion is not faithful.
- **Child data types are same-tenant only.** A child reference may only target a data type in the same tenant; cross-tenant references are rejected.

## Spec Update Instructions

- Update **Agent Data Type Registry**: reframe data types as the single input-and-output contract unit; add one-level child references (single and list, same-tenant only), list fields on any field, the schema source view with its consistency and rejection rules, the child-reference deletion safeguard, and the child-edit warning. Remove "support for nested or composite field types" from its Out of Scope and restate it as "one level only, no deeper nesting".
- Update **Agent Outputs**: describe typed results as the typed payload inside the universal envelope; state that validation status and content type are reported identically across execution logs, the result repository, delegation, and third-party delivery.
- Update **Agent Execution**: add a section stating the universal result envelope applies to LLM, fully-scripted, delegated, conversational, and failed runs; tie typed-output validation to the declared result type; state that a failed conversational turn carries the envelope internally and in logs while its user-facing error surface is unchanged.
- Update **Agent Types**: replace the `output_type` (auto / markdown / typed) enforcement wording with the explicit result types (text, markdown, JSON, typed) and the rule that typed requires a data type; state that `auto` remains accepted as a legacy value and is normalised on read to text (free text; not reclassified as markdown), that new configurations do not rely on implicit auto, and that a result type other than typed cannot carry a data type; document the optional assignable input data type.
- Update **Agent Management**: document in-dialog schema preview for input and output data types, the input slot showing a data type instead of a free-text schema, and structured input entry at launch (groups, repeatable rows, enum choices, field-level validation) for non-conversational agents with an input data type.
- Update **Agent Session Logs**: state that the Result tab renders from the envelope and the declared result type, shows the result type, and uses one content type per result.
- Update **Software 3.0 Agent Framework**: document the result-type-aware scriptability verdict, markdown/free-text boundaries as semantic steps, and that the optimizer receives the reference execution's result and contract.
- Update **Sandboxed Scripting**: state that script results and steps are declared in the envelope and that a fully-scripted claim requires every boundary to be typed or JSON.
- Update **Agent Plan Mode**: record the declared result type per step and per hand-off in plan contracts so semantic bridges are explicit.
- Update **Decision Tools**: note that tool input/output schemas inherit child references, list fields, and the source view while remaining read-only registry selections.
- Update **Third-Party Agent Integration**: state that typed submissions validate against the agent's input data type and that delivered responses use the envelope with result type and validation status.
- Update **Control Center Assistant**: extend the conversational data type capability set to the expanded definition model at UI parity.
- Update **Data Model — Agents**: `AgentDataType` gains input/output usage, same-tenant child reference and list flags, and the expanded reference rules; `AgentType` gains an optional input data type assignment and an explicit result type replacing the inferred output type; `AgentOutput` records the result type with envelope context; update the ER relationships for child references and input assignment.
- Update **UX docs** (`README`, `agent-session-log-ui`): reflect the data type editor with guided and source views, the in-dialog schema preview, structured input entry, and result-type-labelled rendering.
- Explicitly do NOT modify: agent identity and permission semantics, tenant isolation rules, data type review/approval workflows (none introduced), sandboxing and script lifecycle, guardrails or execution-preference/fallback rules, optimization trigger and approval rules, MCP tool naming, or conversation turn durability and chat UX — all unchanged by this epic.
