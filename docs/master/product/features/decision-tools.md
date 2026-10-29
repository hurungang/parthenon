# Decision Tools

## Overview
Decision Tools let users define their own fast, structured snap-judgment tools that behave exactly like built-in system tools. Instead of relying on text-generating language models for every operational decision, a decision tool evaluates a predefined set of atomic questions against a prepared context and returns structured typed answers — chosen options, scores, or yes/no values — each with a probability distribution and a confidence level. Decision tools are defined entirely by users (not platform code), are administered under the Agent module alongside agents and skills, and are consumed through the same channels as system tools: available in the tool registry when defining skills, grantable through roles, invocable by agents and SOPs, and exposed as MCP tools to external clients. Each decision tool explicitly selects an enabled model from the [Decision Model Providers](decision-model-providers.md) catalogue. Skills themselves are unchanged, giving the platform a second, faster decision-making pathway alongside LLM-based skills.

## Business Goals
- Reduce decision latency and cost for high-volume, structured judgments by routing them to a decision model instead of text generation.
- Increase automation coverage safely: every result carries confidence, enabling auto-acting on high-confidence answers and controlled escalation on low-confidence ones.
- Let business owners extend the platform themselves — capturing snap judgments without platform code changes.
- Keep one unified tooling model: skills, agents, SOPs, permissions, and MCP exposure all work with decision tools exactly as they do with system tools.

## Who Uses It
- **Decision Tool Authors / Power Users**: Define and manage decision tools within their tenant — questions, criteria, state mapping, and input/output schemas.
- **Platform Administrators**: Manage the decision model providers, credentials, and enabled models the tools rely on.
- **Agent / SOP Operators**: Associate decision tools with agent roles, agent types, and SOPs; monitor execution results including confidence.
- **Enterprise Consumers / External MCP Clients**: Invoke decision tools and act on structured answers using confidence-based thresholds.

## What It Does
- Provides a dedicated Decision Tools administration area within the Agent module, where users manage agents and skills — not in system configuration.
- A decision tool bundles:
  - **Questions** — one or more atomic questions, each of type **Choice** (options list; returns chosen option, probabilities, confidence), **Score** (ordered rubric legend; returns score, legend, probabilities, confidence), or **Yes/No probability** (returns a probability value).
  - **Per-question instructions and criteria/options** appropriate to the question type.
  - **State preset** — a guided mapping of user input and/or agent data into the context evaluated by the model.
  - **Input and output schemas selected from the [Agent Data Type Registry](agent-data-types.md)** — authors choose existing data types rather than hand-writing schemas; chosen types can be viewed read-only inside the definition dialog.
- Definition follows a natural order: tool name, description, then input/output data types as the first definable rows, followed by questions and state mapping.
- State mapping is guided: instruction text explains context injection, the system auto-detects context path placeholders used in question instructions, and selecting the input data type automatically populates the mapping property selectors.
- An AI generation button — the same mechanism used to draft agent skill instructions — produces a first draft of questions and state mapping from the tool description and chosen data types, for the author to review and adjust.
- The tool description is auto-generated from the definition and is what skills, agents, and MCP clients see — no manual documentation.
- Definition requires a configured decision model: if no enabled model exists in the [Decision Model Providers](decision-model-providers.md) catalogue, the author is clearly informed and cannot proceed.
- Executing a decision tool sends the constructed context plus all predefined questions in a single evaluation and returns structured typed answers per question — values, probabilities, and confidence.
- Confidence supports threshold behavior on every result: high → act automatically, medium → proceed with caution/confirm, low → escalate to a human.
- Executions are logged and auditable like other tool and skill executions.
- Complex judgments are decomposed by the author into multiple predefined questions; each question remains an atomic snap judgment and composition happens at the consumer level.

## Key Concepts
- **Decision Tool**: A user-defined snap-judgment tool bundling questions, criteria, a state preset, and typed input/output schemas.
- **Question Type**: Choice, Score, or Yes/No probability — each an atomic judgment with its own result shape.
- **State Preset**: The mapping that assembles user input and agent data into the context the model evaluates.
- **Confidence Gating**: Using the confidence on every result to decide between automatic action, confirmation, or human escalation.
- **decision Name Prefix**: Decision tool names are distinguished from system tools in every listing, permission grant, and MCP tool list via a reserved "decision" naming prefix (mirroring the "system" prefix), and "decision" is reserved as an MCP slug namespace word so no other MCP server can conflict with it.
- **Tenant Containment**: Decision tool names are unique within a tenant, not globally — the same name can exist independently in every tenant, and all lookups, permissions, and invocations resolve within the caller's tenant.

## User Stories
- As a **decision tool author**, I want a guided form for defining questions with instructions and criteria, so that I can capture snap judgments without technical knowledge.
- As a **decision tool author**, I want to pick existing Agent Data Types for input and output instead of hand-writing schemas, so that definition stays simple and reuses the platform's typed-schema catalogue.
- As a **decision tool author**, I want an AI generation button that drafts questions and state mapping from my description, so that I start from a good draft instead of a blank form.
- As a **decision tool author**, I want the tool description generated for me, so that skills and agents can select and use the tool correctly.
- As a **decision tool author**, I want tool names unique within my tenant only, so that my team can use natural names even when other tenants use the same ones.
- As an **agent operator**, I want saved decision tools to appear in the tool registry when defining skills, just like system tools, so that I can attach them without any extra step.
- As an **agent operator**, I want decision tools grantable through roles and associable to agents and SOPs, so that I manage one permission and invocation model.
- As a **downstream consumer**, I want confidence on every decision, so that I can act automatically, confirm with caution, or escalate to a human.
- As an **external MCP client**, I want decision tools exposed as MCP tools, so that I can invoke them through the same channel as other tools.

## Acceptance Criteria
- Users can create, edit, and delete decision tools from the Decision Tools area within the Agent module; after each operation the tools list refreshes automatically without a manual page reload.
- Tool names are unique within the tenant; duplicate names are rejected with a clear message, and a name freed by deletion can be reused.
- When creating or editing a decision tool, the system verifies an enabled decision model exists in the Decision Model Providers catalogue; if none exists, the user is clearly informed and cannot proceed. The definition form reflects the configured model's interface requirements.
- The definition form presents fields in a fixed order: tool name, description, input data type, output data type, then questions and state mapping.
- Input and output schemas are selected from existing Agent Data Types; chosen data types can be viewed read-only inside the dialog without leaving the form.
- Question instructions support context path placeholders, which the form auto-detects; after selecting the input data type, its properties populate the mapping property selectors automatically.
- The AI generation button drafts questions and state mapping from the description and chosen data types; drafts are always shown for author review and adjustment before saving.
- Each question has a type (Choice, Score, or Yes/No probability) with instructions and criteria/options appropriate to the type; at least one question is required.
- The tool description is auto-generated from the definition and shown consistently in the tool registry, permission grants, and MCP tool lists.
- Decision tools are visually distinguishable from system tools in every listing, permission grant, and MCP tool list via the reserved "decision" naming prefix; no other MCP server slug can use the "decision" namespace word.
- Saved decision tools appear in the tool registry when defining skills, alongside system tools, and are selectable exactly like system tools.
- Decision tools are grantable through roles and invocable by agents and SOPs under the existing permission model — no separate permission system.
- Decision tools are exposed as MCP tools and invocable by external MCP clients under the same permission model.
- Executing a decision tool returns structured typed answers per question — values, probability distributions, and confidence — in a single evaluation of all predefined questions.
- Confidence is exposed on every result, enabling threshold behavior: high → automatic action, medium → confirmation, low → human escalation.
- Decision tool executions are logged and auditable like existing tool and skill executions, identifying the provider and model used.
- Two tenants can each define a decision tool with the same name; each tenant's skills, roles, and agents resolve only their own tenant's tool.

## Out of Scope
- Adding new decision vendor integrations (covered by [Decision Model Providers](decision-model-providers.md))
- Automatic decomposition of complex judgments into question sets — authors define questions manually
- Fallback to text-generation models when a decision model is unavailable
- Real-time editing of questions during execution — question sets are fixed at definition time
- Cost analytics or billing dashboards for decision model usage
- Any change to [Skill Management](skill-management.md) — skill types, authoring, and behavior remain unchanged

## Dependencies & Constraints
- Requires at least one enabled model in the [Decision Model Providers](decision-model-providers.md) catalogue; provider availability and pricing are external to Parthenon.
- Must follow the platform's encrypted-credential handling; decision model credentials never reach agents or end users.
- Must integrate with the existing system tool / permission / SOP model — no parallel permission system and no new invocation pathway.
- Tenant containment aligns with the platform's [Multi-Tenancy](multi-tenancy.md) and [Strict Tenant Isolation](strict-tenant-isolation.md) model: one session equals one tenant, and permission grants apply only within the session's tenant.
