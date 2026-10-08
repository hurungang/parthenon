# PRD: System One Decision Tools

## Epic Overview

Today, every decision an agent makes flows through LLM text generation: prompts in, prose out, and a human or downstream parser has to interpret whether the answer is reliable. Many operational decisions don't need prose at all — they need a fast, structured snap judgment: which option to pick, how to rate something against a rubric, or a yes/no with a probability. Parthenon will integrate TypeSafe AI's "Jev", the first "System One" model, which evaluates typed questions against a state and returns structured answers directly — typed values, probability distributions, and confidence — without generating text. This change lets users configure encrypted System One provider credentials and define their own "decision tools": user-managed tools that predefine a question set, a state preset, and input/output schemas built from the platform's Agent Data Type Registry, and that behave exactly like Parthenon's built-in system tools — automatically described for consumers, available to skills, agents, and SOPs like any system tool, and exposed as MCP tools for invocation. Decision tools are named with a "decision" prefix to distinguish them from system tools, and all tools are tenant-contained: the same tool name can exist independently in every tenant. Skills themselves are unchanged, giving the platform a second, faster decision-making pathway alongside LLM-based skills.

## Business Goals

- Reduce decision latency and cost for high-volume, structured judgments by routing them to a System One model instead of LLM generation.
- Increase trust and automation coverage: every decision result carries confidence, enabling safe auto-acting on high-confidence results and controlled escalation on low-confidence ones.
- Empower users to extend the platform themselves: decision tools are defined by users (not predefined), so business owners capture their own snap judgments without platform code changes.
- Keep the tooling model unified: decision tools behave like system tools, so skills, agents, SOPs, permissions, and MCP exposure work with no new consumption model.
- Establish a provider-agnostic System One integration today with Jev/TypeSafe, without rework when additional System One providers arrive.
- Support multi-tenant operations safely: tool names and all managed records are unique within a tenant, letting independent teams reuse natural names without collision.

## Users & Personas

- **Platform Administrator** — Configures the TypeSafe AI API key (encrypted, like existing credentials) and enables/disables System One decision-making for the deployment.
- **Decision Tool Author / Power User** — Defines and manages decision tools within their tenant: atomic questions (Choice, Score, Noul) with instructions and criteria, a state preset mapping input data, and input/output schemas built from the platform's Agent Data Type registry.
- **Agent Operator** — Associates decision tools with agent roles/agent types and SOPs; monitors execution results including confidence.
- **Enterprise Consumer / Downstream System** — Consumes structured typed answers (values, probabilities, confidence) to act automatically, confirm, or escalate to a human.

## User Stories

- As a platform administrator, I want to store my TypeSafe AI API key securely, so that System One decision-making is available without exposing credentials.
- As a platform administrator, I want the base URL preset to Jev's endpoint (https://api.typesafe.ai/v1) for now, so that provider setup requires no guesswork.
- As a platform administrator, I want a "Test connection" button when configuring the System One provider, so that I can validate the API configuration before relying on it.
- As a decision tool author, I want the system to warn me when no System One model is configured, so that I understand why I cannot create a decision tool.
- As a decision tool author, I want Decision Tools administration to live under the Agent module, so that tool definition sits where I already manage agents and skills rather than in system configuration.
- As a decision tool author, I want a guided form for defining decision questions (Choice, Score, Noul) with instructions and criteria, so that I can capture snap judgments without technical knowledge.
- As a decision tool author, I want to pick an existing Agent Data Type for my tool's input and output instead of hand-writing schemas, so that definition stays simple and reuses the platform's typed-schema catalogue (the Agent Data Type Registry).
- As a decision tool author, I want to view the input and output data type definitions read-only in the form, so that I can recall their exact fields without leaving the dialog.
- As a decision tool author, I want instruction text explaining state injection, plus automatic detection of the object/state path placeholders in my Jev question instructions (backtick-quoted paths like `input.tier`), so that mapping feels guided rather than manual.
- As a decision tool author, I want the mapping property selectors to populate automatically from the input data type I chose, so that I map the right fields without typing paths by hand.
- As a decision tool author, I want a state preset that maps input and agent data into the decision state, so that executions send the right context to the model.
- As a decision tool author, I want the form to follow a natural order — name, description, then input/output data types as the first definable rows, then questions and state mapping — so that definition flows from intent to detail.
- As a decision tool author, I want an AI generation button (like the one used for agent skill instructions) that drafts questions and state mapping from my description and chosen data types, so that I start from a good draft instead of a blank form.
- As a decision tool author, I want the tool description generated for me from my definition, so that skills and agents can select and use the tool correctly without manual documentation.
- As a decision tool author, I want tool names to be unique within my tenant only, so that my team can name a tool "tool_a" even when other tenants already use that name.
- As an agent operator, I want saved decision tools to appear in the tool registry when defining skills, just like system tools, so that I can attach them to skills without any extra step.
- As an agent operator, I want decision tools to appear alongside system tools and be grantable via roles and associable to agents and SOPs, so that I manage one permission and invocation model.
- As an agent operator, I want decision tool executions to return structured answers with probabilities and confidence, so that results are immediately interpretable and auditable.
- As a downstream consumer (agent, SOP, or external MCP client), I want decision tools exposed as MCP tools, so that I can invoke them through the same channel as other tools.
- As a downstream consumer, I want confidence on every decision, so that I can act automatically, confirm with caution, or escalate to a human.
- As a decision tool author, I want complex judgments broken into multiple predefined questions, so that each question remains an atomic snap judgment and composition happens at the consumer level.

## Acceptance Criteria

- A user can save, update, and remove a TypeSafe AI API key; the key is stored encrypted at rest and never returned in plaintext by any UI or API response.
- For the initial release, the System One provider base URL is preset to Jev's endpoint (https://api.typesafe.ai/v1) and is not editable; the provider configuration screen includes a "Test connection" button that validates the API configuration (key + endpoint) and reports success or a clear failure before saving is relied upon.
- Decision Tools administration is part of the Agent module: users create and manage decision tools where they manage agents and skills, not in system configuration.
- When creating or editing a decision tool, the system checks for a configured System One model:
  - If none is configured, the user is clearly informed and cannot proceed with decision tool definition.
  - If configured, a form (driven by the configured model's API definition) is shown.
- The decision tool form presents fields in a fixed order: tool name, description, then input data type and output data type as the first definable rows, followed by questions and state mapping.
- Input and output schemas are not hand-written: the form asks the author to select an existing Agent Data Type (the platform's typed-schema registry) for input and for output. Chosen data types can be viewed read-only inside the dialog so authors can confirm exact field definitions without leaving the form.
- The form provides instruction text on state injection and auto-detects object/state path placeholders used in Jev question instructions (backtick-quoted dot/bracket paths such as `input.tier`); after the author selects the input data type, its properties automatically populate the mapping property selectors.
- The form includes an AI generation button — the same mechanism used to generate instructions for agent skills — that analyzes the description and chosen input/output data types and drafts questions and state mapping for the author to review and adjust.
- The decision tool form supports one or more questions, each with a type (Choice, Score, Noul), instructions, and criteria/options appropriate to the type, plus a state preset defining how input/agent data maps into the state sent to the model.
- Input and output for a decision tool are defined through the selected Agent Data Types, aligned with the platform's system tool conventions, so the tool is consumed like a system tool.
- The tool description is auto-generated from the decision tool's definition (questions, schemas, and purpose) and is what skills, agents, and MCP clients see.
- Decision tool names are prefixed with "decision" — exposed as `decision____<name>` (four underscores), mirroring the `system____` convention of system tools — and "decision" is reserved as an MCP slug namespace word (like "system") so no other MCP server slug can conflict with it. Decision tools are distinguishable from system tools in every listing, permission grant, and MCP tool list.
- Saved decision tools appear in the tool registry when defining skills, alongside system tools, so they can be selected for skills exactly like system tools.
- Decision tools appear alongside system tools: invocable by skills, agents, and SOPs, and grantable through roles/permissions exactly like system tools.
- Decision tools are exposed as MCP tools and invocable by external MCP clients through the platform's MCP interface.
- Tool names are unique within a tenant: the same name can exist independently in different tenants, and all lookups, permissions, and invocations resolve within the caller's tenant. All other tool and data records managed in the application are likewise tenant-contained.
- Executing a decision tool sends the constructed state plus all predefined questions in a single evaluation and returns structured typed answers per question, including probabilities and confidence.
- Confidence is exposed on every result so consumers can apply threshold behavior: high → act automatically, medium → proceed with caution/confirm, low → escalate to a human.
- Decision tool executions are logged and auditable like existing tool/skill executions.
- The provider configuration model supports multiple System One providers, with Jev/TypeSafe as the only one initially available.

## Out of Scope

- Additional System One providers beyond Jev/TypeSafe (design only, no implementation).
- Automatic decomposition of complex judgments into question sets (authors define questions manually).
- LLM-based fallback when the System One provider is unavailable.
- Real-time editing of questions during execution — question sets are fixed at definition time.
- Cost analytics or billing dashboards for System One usage.
- Any change to skills — skill types, skill authoring, and skill behavior remain exactly as they are today.

## Dependencies & Constraints

- Requires a valid TypeSafe AI account and API key; availability and pricing are external to Parthenon.
- Must follow Parthenon's existing encrypted-credential patterns (as used for MCP server credentials and model configurations).
- Must respect platform top-priority rules: all System One calls originate from Control Center-managed flows; agents never hold the API key or any sensitive credential.
- Decision tools must integrate with the existing system tool / permission / SOP model — no parallel permission system and no new invocation pathway.
- Tenant containment must align with the platform's multi-tenancy model (root tenant, per-tenant permission scoping, session-based tenant resolution).
- Only "jev-latest" model (typesafe provider) is supported in this release.
