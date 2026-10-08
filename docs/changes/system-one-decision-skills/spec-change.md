# Spec Delta: System One Decision Tools

## Affected Spec Areas

- `docs/master/product/features/` — new Decision Tools capability (user-defined, system-tool-like)
- `docs/master/product/features/` — System Tools; extended to cover user-defined decision tools alongside built-in tools
- `docs/master/product/features/` — Agent Data Type Registry; extended as the source of decision tool input/output schemas
- `docs/master/product/features/` — Model Configurations; extended to cover System One providers
- `docs/master/product/features/` — MCP Hub; decision tools exposed as MCP tools
- `docs/master/product/features/` — SOPs; composition with decision tools
- `docs/master/product/features/` — Agent Roles & Permissions; decision tools as grantable units
- `docs/master/product/features/` — Multi-Tenancy; tenant-containment as a spec-level requirement for managed records
- `docs/master/data-model/` — New System One provider config entity; decision tool definition structures; tenant scoping for tool records
- `docs/master/ux/` — Decision tool management UI under the Agent module (definition flow); system configuration (provider credentials with connection test)
- `docs/master/reference/` — New reference doc for System One / Jev concepts (question types, confidence)

## New Capabilities

- **Decision Tools**
  - Users define their own "decision tools": a dedicated decision tool module managed by users, not predefined like system tools.
  - A decision tool bundles:
    - A question set of one or more atomic questions: **Choice** (options list; returns chosen option, probabilities, confidence), **Score** (ordered rubric legend; returns score, legend, probabilities, confidence), **Noul** (yes/no probability; returns noul value 0–1).
    - Per-question instructions and criteria/options.
    - A **state preset**: mapping of user input and/or agent data into the state evaluated by the model.
    - Input and output schemas selected from the **Agent Data Type registry** — authors choose existing Agent Data Types rather than hand-writing schema definitions. Chosen data types can be viewed read-only inside the definition dialog.
  - Definition form flow: tool name, then description, then input data type and output data type as the first definable rows, followed by questions and state mapping.
  - State mapping is guided: instruction text explains state injection, the system auto-detects the object/state path placeholders used in Jev question instructions (backtick-quoted dot/bracket paths such as `input.tier`), and after the input data type is selected, its properties automatically populate the mapping property selectors.
  - An AI generation button — the same mechanism used to generate instructions for agent skills — analyzes the description and chosen input/output data types and drafts questions and state mapping for the author to review and adjust.
  - The tool description is auto-generated from the definition and presented to skills, agents, and MCP clients — no manual documentation.
  - Decision tools behave like system tools in every consumer dimension:
    - Structured input/output aligned with the TypeSafe Jev API.
    - Auto-generated tool description.
    - Available to skills exactly like system tools — saved decision tools appear in the tool registry when defining skills.
    - Exposed as an MCP tool for invocation.
  - Decision tool names carry a "decision" prefix and are exposed as `decision____<name>` (four underscores), mirroring the `system____` convention of system tools. "decision" is reserved as an MCP slug namespace word (like "system") to prevent conflicts, distinguishing decision tools in listings, permission grants, and MCP tool lists.
  - Decision Tools administration lives under the Agent module, where users manage agents and skills — not under system configuration.
  - Names are unique within a tenant, not globally: a tool named "tool_a" can exist independently in tenant A, tenant B, and every other tenant.
  - When defining a decision tool, the system first verifies a System One model is configured; definition is blocked with a clear message if not. The definition form is driven by the configured model's API definition.
  - Questions are atomic snap judgments; complex judgments are decomposed by the author into multiple questions, composed downstream.

- **Decision tool execution**
  - Executing a decision tool sends the constructed state plus all predefined questions to the configured System One model and returns structured typed answers per question — values, probability distributions, and confidence.
  - Every result exposes confidence so consumers can gate behavior: high → act automatically, medium → proceed with caution/confirm, low → escalate to a human.
  - Executions are logged and auditable like other tool/skill executions.

- **Tenant containment for managed records**
  - Tools (decision tools and all other tools managed in the application) and all other data records are tenant-contained: uniqueness, visibility, permission resolution, and invocation all resolve within the caller's tenant.
  - Aligns with the platform's Multi-Tenancy model: one session = one tenant; permission grants apply only within the session's tenant.

- **System One provider configuration**
  - Administrators register a System One provider credential (currently only "typesafe" providing the "jev" model) with an encrypted API key.
  - For the initial release the base URL is preset to Jev's endpoint (https://api.typesafe.ai/v1) and is not editable; configuration requires no manual endpoint entry.
  - The provider configuration screen includes a "Test connection" action that validates the API configuration and reports success or a clear failure, so administrators never save-and-hope.
  - Credential management follows existing encrypted-credential behavior: write-only in UI, decrypted only at call time, never exposed via API.
  - Designed multi-provider: new System One providers can be added without changing the decision tool definition or execution model.

## Modified Capabilities

- **Model Configurations**
  - Before: Centrally managed LLM provider configs (API-key-based providers, two dispatch families) with encrypted credentials and enabled model lists; referenced by agent types.
  - After: Configuration scope extends to System One providers (currently typesafe/jev) with the same encrypted-credential handling; System One configuration is checked during decision tool definition and resolved at execution time.

- **System Tools**
  - Before: Only predefined system tools (e.g., save_data, get_data, query_result) available to skills and exposed via MCP.
  - After: User-defined decision tools appear alongside system tools with identical consumption behavior (structured schemas via Agent Data Types, auto-generated description, availability in the tool registry when defining skills, MCP exposure), identifiable by their `decision____` name prefix.

- **Agent Data Type Registry**
  - Before: A centralized catalogue of reusable typed schemas, used for typed outputs of non-conversational agent types.
  - After: Also the source of decision tool input/output schemas — authors select existing Agent Data Types when defining a decision tool instead of hand-writing schemas, reusing the registry's typed fields and its view/read experience.

- **MCP Hub**
  - Before: MCP interface exposes synced MCP server tools and system tools to permitted clients.
  - After: Decision tools are additionally exposed as MCP tools in the same interface, subject to the same permission model.

- **SOPs & Agent Roles**
  - Before: Compose and grant skills and system tools.
  - After: Decision tools participate identically — SOP steps may invoke decision tools; roles may grant them; no separate permission model.

## Removed Capabilities

- None.

## Spec Update Instructions

- Update the Decision Tools feature spec content to cover: user-defined tool definition under the Agent module, question types (Choice/Score/Noul), state preset with guided mapping (instruction text, auto-detected backtick path placeholders, property selectors populated from the input data type), input/output schemas via Agent Data Type selection with read-only in-dialog viewing, the AI generation button (same mechanism as agent skill instruction generation), fixed form field order (name → description → input/output data types → questions/state mapping), auto-generated description, `decision____<name>` naming with "decision" reserved as an MCP slug namespace word, execution semantics, and confidence-threshold behavior.
- Update the System Tools spec: note that user-defined decision tools behave like system tools (structured schemas via Agent Data Types, auto-generated description, availability in the tool registry when defining skills, MCP exposure) but are defined by users; names use the `decision____` prefix mirroring `system____`; names are tenant-unique.
- Update the Agent Data Type Registry spec: extend its purpose to cover decision tool input/output schema selection (read-only consumption within the decision tool dialog; registry management behavior unchanged).
- Update the Multi-Tenancy spec: add tenant-containment as a spec-level requirement — tools and all other data records managed in the application are scoped per tenant; the same record name (e.g., "tool_a") can exist independently in every tenant; uniqueness and resolution are per-tenant.
- Update the MCP Hub spec: document decision tools as MCP-exposed tools under the same permission model, with `decision` reserved as a slug namespace word (like `system`) and tools exposed as `decision____<name>`.
- Update the Model Configurations spec: extend scope to System One providers, note typesafe/jev as the initial provider with the base URL preset to https://api.typesafe.ai/v1, and document the definition-time configuration check plus the "Test connection" validation in provider configuration.
- Update the SOPs spec: note decision tools may appear as SOP steps and results are structured typed answers.
- Update the Agent Roles & Permissions spec: confirm decision tools are grantable units within the existing role/permission model.
- Update `docs/master/data-model/`: add the System One provider configuration entity (encrypted API key, provider type, preset base URL) and decision tool definition structures (questions, criteria/options, state preset, references to selected Agent Data Types for input and output) with tenant scoping on tool records.
- Update `docs/master/ux/` prototype: decision tool management flow within the Agent module (create/edit → configuration check → form in fixed order: name, description, input/output data type selection with read-only definition viewing, questions, state mapping with auto-populated property selectors; AI generation entry point; tenant-scoped listing) and provider credential management in system configuration with the preset base URL and "Test connection" button.
- Add a reference doc in `docs/master/reference/` summarizing System One / Jev concepts: question types, parallel independent evaluation, probability distributions, confidence gating (act / confirm / escalate).
- Explicitly do NOT modify the Skills spec — skills are unchanged by this change.
