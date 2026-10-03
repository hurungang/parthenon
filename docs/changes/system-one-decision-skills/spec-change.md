# Spec Delta: System One Decision Skills

## Affected Spec Areas

- `docs/master/product/features/` — Skills & skill types; new decision skill capability
- `docs/master/product/features/` — Model Configurations; extended to cover System One providers
- `docs/master/product/features/` — SOPs; composition with decision skills
- `docs/master/product/features/` — Agent Roles & Permissions; decision skills as grantable units
- `docs/master/data-model/` — New System One provider config entity; decision skill definition structures
- `docs/master/ux/` — Skill editor (new decision-skill authoring flow); system configuration (provider credentials)
- `docs/master/reference/` — New reference doc for System One / Jev concepts (question types, confidence)

## New Capabilities

- **System One provider configuration**
  - Administrators register a System One provider credential (currently only "typesafe" providing the "jev" model) with an encrypted API key.
  - Credential management follows existing encrypted-credential behavior: write-only in UI, decrypted only at call time, never exposed via API.
  - Designed multi-provider: new System One providers can be added without changing the skill authoring or execution model.

- **Decision skill type**
  - Skills gain a new type: "decision skill", alongside existing skill types.
  - When authoring a decision skill, the system first verifies a System One model is configured; authoring is blocked with a clear message if not.
  - Authoring form (driven by the configured model's API definition) lets users predefine:
    - A question set of one or more atomic questions: **Choice** (options list; returns chosen option, probabilities, confidence), **Score** (ordered rubric legend; returns score, legend, probabilities, confidence), **Noul** (yes/no probability; returns noul value 0–1).
    - Per-question instructions and criteria/options.
    - A **state preset**: mapping of user input and/or agent data into the state evaluated by the model.
  - Questions are atomic snap judgments; complex judgments are decomposed by the author into multiple questions, composed downstream.

- **Decision skill execution**
  - Executing a decision skill sends the constructed state plus all predefined questions to the configured System One model and returns structured typed answers per question — values, probability distributions, and confidence.
  - Every result exposes confidence so consumers can gate behavior: high → act automatically, medium → proceed with caution/confirm, low → escalate to a human.
  - Executions are logged and auditable like other skill executions.

## Modified Capabilities

- **Skills (skill types)**
  - Before: Skills wrap one or more MCP tool calls; permission-grantable units for agents.
  - After: Skills additionally include the "decision skill" type — invocable, associable to agents and SOPs, and permission-grantable exactly like existing skills, but executing a predefined System One evaluation instead of MCP tool calls.

- **Model Configurations**
  - Before: Centrally managed LLM provider configs (API-key-based providers, two dispatch families) with encrypted credentials and enabled model lists; referenced by agent types.
  - After: Configuration scope extends to System One providers (currently typesafe/jev) with the same encrypted-credential handling; System One configuration is checked during decision-skill authoring and resolved at execution time.

- **Skill editor (authoring UX)**
  - Before: Skill create/edit supports existing skill types only.
  - After: Selecting the decision skill type triggers a System One configuration check, then presents a model-API-driven form for questions and state preset. Existing skill-type flows unchanged.

- **SOPs & Agent Roles**
  - Before: Compose and grant existing skills.
  - After: Decision skills participate identically — SOP steps may invoke decision skills; roles may grant them; no separate permission model.

## Removed Capabilities

- None.

## Spec Update Instructions

- Add a decision-skills feature spec under `docs/master/product/features/` covering: skill type, question types (Choice/Score/Noul), state preset, execution semantics, and confidence-threshold behavior.
- Update the Skills spec: list "decision skill" as a new skill type; note it is invocable, associable, and permission-grantable like other skills.
- Update the Model Configurations spec: extend scope to System One providers, note typesafe/jev as the initial provider, and document the authoring-time configuration check.
- Update the SOPs spec: note decision skills may appear as SOP steps and results are structured typed answers.
- Update the Agent Roles & Permissions spec: confirm decision skills are grantable units within the existing role/permission model.
- Update `docs/master/data-model/`: add the System One provider configuration entity (encrypted API key, provider type) and decision skill definition structures (questions, criteria/options, state preset).
- Update `docs/master/ux/` prototype: skill editor decision-skill flow (type selection → configuration check → question/state form) and provider credential management in system configuration.
- Add a reference doc in `docs/master/reference/` summarizing System One / Jev concepts: question types, parallel independent evaluation, probability distributions, confidence gating (act / confirm / escalate).
