# PRD: System One Decision Skills

## Epic Overview

Today, every decision an agent makes flows through LLM text generation: prompts in, prose out, and a human or downstream parser has to interpret whether the answer is reliable. Many operational decisions don't need prose at all — they need a fast, structured snap judgment: which option to pick, how to rate something against a rubric, or a yes/no with a probability. Parthenon will integrate TypeSafe AI's "Jev", the first "System One" model, which evaluates typed questions against a state and returns structured answers directly — typed values, probability distributions, and confidence — without generating text. This change lets users configure encrypted System One provider credentials, author new "decision skills" that predefine a question set and state mapping, and invoke those skills exactly like existing skills from agents and SOPs, giving the platform a second, faster decision-making pathway alongside LLM-based skills.

## Business Goals

- Reduce decision latency and cost for high-volume, structured judgments by routing them to a System One model instead of LLM generation.
- Increase trust and automation coverage: every decision result carries confidence, enabling safe auto-acting on high-confidence results and controlled escalation on low-confidence ones.
- Extend the platform's skill catalog with a new skill category, keeping Parthenon's single permission model for all invocable units.
- Establish a provider-agnostic System One integration today with Jev/TypeSafe, without rework when additional System One providers arrive.
- Reduce human review burden by letting confidence thresholds determine when confirmation or human escalation is required.

## Users & Personas

- **Platform Administrator** — Configures the TypeSafe AI API key (encrypted, like existing credentials) and enables/disables System One decision-making for the deployment.
- **Skill Author / Power User** — Creates and edits decision skills: defines atomic questions (Choice, Score, Noul) with instructions and criteria, and maps agent/input data into the state sent to the model.
- **Agent Operator** — Associates decision skills to agent roles/agent types and SOPs; monitors execution results including confidence.
- **Enterprise Consumer / Downstream System** — Consumes structured typed answers (values, probabilities, confidence) to act automatically, confirm, or escalate to a human.

## User Stories

- As a platform administrator, I want to store my TypeSafe AI API key securely, so that System One decision-making is available without exposing credentials.
- As a skill author, I want the system to warn me when no System One model is configured, so that I understand why I cannot create a decision skill.
- As a skill author, I want a guided form for defining decision questions (Choice, Score, Noul) with instructions and criteria, so that I can capture snap judgments without technical knowledge.
- As a skill author, I want to define a state preset that maps input and agent data into the decision state, so that executions send the right context to the model.
- As an agent operator, I want decision skills to be grantable via roles and associable to agents and SOPs like any other skill, so that I manage one permission model.
- As an agent operator, I want decision skill executions to return structured answers with probabilities and confidence, so that results are immediately interpretable and auditable.
- As a downstream consumer (agent, SOP, or human reviewer), I want confidence on every decision, so that I can act automatically, confirm with caution, or escalate to a human.
- As a skill author, I want complex judgments broken into multiple predefined questions, so that each question remains an atomic snap judgment and composition happens at the consumer level.

## Acceptance Criteria

- A user can save, update, and remove a TypeSafe AI API key; the key is stored encrypted at rest and never returned in plaintext by any UI or API response.
- When creating or editing a skill and selecting the "decision skill" type, the system checks for a configured System One model:
  - If none is configured, the user is clearly informed and cannot proceed with decision-skill authoring.
  - If configured, a form (driven by the configured model's API definition) is shown.
- The decision skill form supports one or more questions, each with a type (Choice, Score, Noul), instructions, and criteria/options appropriate to the type, plus a state preset defining how input/agent data maps into the state sent to the model.
- Decision skills appear alongside existing skills: invocable, associable to agents and SOPs, and grantable through roles/permissions.
- Executing a decision skill sends the constructed state plus all predefined questions in a single evaluation and returns structured typed answers per question, including probabilities and confidence.
- Confidence is exposed on every result so consumers can apply threshold behavior: high → act automatically, medium → proceed with caution/confirm, low → escalate to a human.
- Decision skill executions are logged and auditable like existing skill executions.
- The provider configuration model supports multiple System One providers, with Jev/TypeSafe as the only one initially available.

## Out of Scope

- Additional System One providers beyond Jev/TypeSafe (design only, no implementation).
- Automatic decomposition of complex judgments into question sets (authors define questions manually).
- LLM-based fallback when the System One provider is unavailable.
- Real-time editing of questions during execution — question sets are fixed at authoring time.
- Cost analytics or billing dashboards for System One usage.
- Changes to existing LLM-based skill types or their behavior.

## Dependencies & Constraints

- Requires a valid TypeSafe AI account and API key; availability and pricing are external to Parthenon.
- Must follow Parthenon's existing encrypted-credential patterns (as used for MCP server credentials and model configurations).
- Must respect platform top-priority rules: all System One calls originate from Control Center-managed flows; agents never hold the API key or any sensitive credential.
- Decision skills must remain first-class members of the existing skill/permission/SOP model — no parallel permission system.
- Only "jev-latest" model (typesafe provider) is supported in this release.
