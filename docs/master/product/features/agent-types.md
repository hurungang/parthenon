# Agent Types

## Overview
Agent Types define how organizations standardize agent behavior, governance, and accountability across different business use cases. Each Agent Type carries its own execution guardrail profile so teams can apply predictable limits, reduce runaway execution risk, and maintain cost-aware operations.

## Who Uses It
- Platform Administrators: Configure and govern Agent Type policies
- AI Operations Leads: Monitor policy outcomes and operational reliability
- Business Process Owners: Ensure automation behaves predictably for each use case

## What It Does
- Defines distinct execution policy boundaries per Agent Type
- Applies cycle prevention for delegated execution chains
- Applies bounded execution policy for iteration, delegation, and timeout controls
- Supports token-budget policy behavior for supported non-conversational and automated runs
- Supports clear visibility of guardrail usage and policy outcomes in execution summaries
- Validates SOP/delegation configuration for **recursive delegation risk** at create and update entry points, blocking recursion-prone submissions
- Validates **recursion/dead-loop risk** at run initiation and prevents execution when risk conditions are detected
- The model picker in the Agent Type form is sourced from the centrally managed [Model Configurations](./model-configurations.md) catalogue and grows automatically as new providers and models are configured
- The configured `output_type` (`auto`, `markdown`, `typed`) is actively enforced for non-conversational agents via system prompt injection — markdown agents receive formatting instructions, typed agents receive schema-driven JSON instructions, auto agents receive no extra guidance
- Supports binding multiple SOPs and skills to an Agent Type as an ordered list of entries, where each entry references either an SOP or a skill; bindings define the curated capability set used for system instruction generation and Agent Plan Mode
- Non-conversational agent types can optionally be assigned an output data type from the [Agent Data Type Registry](./agent-data-types.md). When a data type is selected, the agent type's output is validated against that schema at execution time, stored with the schema reference, and rendered as a structured field-by-field view in execution logs. Conversational agent types do not support data type assignment

## SOP & Skill Binding
- Agent Types store an ordered list of binding entries, each referencing either an SOP or a skill
- Bindings must reference SOPs and skills that are accessible through the agent's assigned role; invalid bindings are rejected with clear error messages
- The binding order is context for AI-generated system instructions and Agent Plan Mode — not an execution sequence
- The binding list replaces the legacy single-primary-SOP field; existing entries are migrated automatically
- System instruction generation and Agent Plan Mode use only the explicitly bound SOPs and skills; if no bindings are defined, they fall back to all role-assigned items (current behaviour)

### Binding Validation & Enforcement
- **Backend validation on every save**: Every agent type create or update calls `validate_bindings()` which checks each SOP and skill binding against the assigned role's granted permissions. Invalid references are rejected with per-entry error messages. Duplicate bindings are also rejected. Bindings cannot be set without an assigned role
- **At-least-one requirement**: Agent types must specify at least one SOP or Skill binding — save is blocked with a clear error when both lists are empty
- **Frontend orphan detection**: When the selected role changes and previously bound SOPs/skills are no longer accessible, the form displays a warning banner listing orphaned items with a "Remove All" button. Each orphaned row gets a warning border. This is advisory — the server enforces the check on save
- **Save button disabled**: The save button is disabled when no bindings exist, preventing submission of an invalid configuration
- **Role-scoped add dropdown**: The add-binding dropdown only shows SOPs/skills that are accessible through the currently selected role. Already-bound items are hidden from the picker. The add button is disabled when no role is selected
- **Empty state hint**: When no bindings are defined, italic hint text shows "At least one SOP or Skill binding is required"

## Recursion and Dead-Loop Prevention
- Agent Type create and update flows **validate recursive delegation risk** in SOP and delegation configuration
- Recursion-prone configurations are **blocked before submission** with a clear user-visible error
- Run initiation **validates recursion/dead-loop risk** and prevents execution when risk conditions are detected
- Validation outcomes are reflected in execution logs and configuration error messages

## Acceptance Criteria
- Each Agent Type has a distinct guardrail profile
- Delegation cycle prevention applies to direct and indirect recursion paths
- Iteration, delegation boundary, and timeout policies are enforced per Agent Type
- Conversational runs keep current-session token usage visible
- Conversational runs are not hard-stopped solely by token budget thresholds
- Non-conversational and automated runs enforce token budgets when supported, with transparent fallback when unsupported
- **Recursive delegation risk is validated during agent create and update, and invalid submissions are blocked**
- **Recursion/dead-loop risk is validated during run initiation, and execution is prevented when risk conditions are detected**
- **Agent Types support binding multiple SOPs and skills in an ordered list**
- **Bound SOPs and skills must be accessible through the agent's assigned role; invalid bindings are rejected with 422 and per-entry error messages**
- **At-least-one binding is enforced — save blocked with 400 when both lists are empty**
- **Orphan detection warns when role swap leaves stale bindings; "Remove All" button clears them**
- **Add-binding picker is role-scoped — only shows role-accessible SOPs/skills**
- **Save button is disabled when no bindings are defined**
- **System instruction generator and Agent Plan Mode use only explicitly bound SOPs and skills**
- **Binding list is visible and editable in the Agent Type editor UI**
- **Non-conversational agent types include an output data type selector sourced from the Agent Data Type Registry**
- **Conversational agent types do not show the output data type field**
- **When an output data type is assigned, the agent type's output type badge in list views displays the data type name**
- **After selecting a data type, the output type is set to `typed` and the schema is linked for validation at execution time**

## Out of Scope
- Technical implementation design or service internals
- Provider-specific model optimization strategy

## Dependencies & Constraints
- Requires consistent policy governance in Control Center
- Depends on clear policy-outcome visibility in execution and monitoring views
- Must align with enterprise segregation and audit requirements
- Recursion validation depends on a stable SOP and delegation step graph; configuration changes that would create cycles must be rejected at create/update and again at run initiation
- SOP/skill binding validation depends on accurate role-permission resolution
- Binding UI must be keyboard-accessible and internationalised
- The output data type selector depends on the [Agent Data Type Registry](./agent-data-types.md); data types must exist before they can be assigned to agent types
- Only non-conversational agent types support output data type assignment; conversational types are excluded by design
