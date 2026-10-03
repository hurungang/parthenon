# Data Model Changes: System One Decision Skills

> Technology-agnostic business entity model. No SQL, ORM, or storage details.

## 1. New Entities

### SystemOneProviderConfig

Stores credentials for a System One model provider (initially only TypeSafe/Jev), following the existing encrypted-credential pattern (as used by identity provider configs).

```mermaid
erDiagram
    SystemOneProviderConfig {
        uuid id
        uuid tenant_id "FK to Tenant, nullable"
        enum provider_type "typesafe (extensible)"
        string display_name
        string base_url
        string default_model "e.g. jev-latest"
        string encrypted_api_key "AES-256 encrypted, never returned in plaintext"
        boolean enabled
        json enabled_models
        datetime created_at
        datetime updated_at
    }
    Tenant ||--o{ SystemOneProviderConfig : "scopes"
```

### DecisionSkillDefinition

Defines the authoring-time payload for a skill of the `decision` type. Extends the existing Skill entity (one-to-one) rather than overloading Skill, because question sets and state presets are large structured payloads only relevant to decision skills — keeping them separate avoids null-heavy columns on ordinary LLM skills.

```mermaid
erDiagram
    DecisionSkillDefinition {
        uuid id
        uuid skill_id "FK to Skill, unique"
        json state_preset "mapping of input/agent data to state fields"
        enum act_threshold "confidence >= act → auto-act"
        enum confirm_threshold "confidence >= confirm → proceed with caution"
        boolean is_active
        datetime created_at
        datetime updated_at
    }
    DecisionQuestion {
        uuid id
        uuid definition_id "FK to DecisionSkillDefinition"
        int order
        string question_key
        enum question_type "choice | score | noul"
        string instructions
        json criteria_options "criteria/options appropriate to type"
        boolean is_required
    }
    DecisionSkillDefinition ||--o{ DecisionQuestion : "contains"
    Skill ||--o| DecisionSkillDefinition : "specializes as decision skill"
```

### DecisionExecutionResult

Persists each decision skill execution: state snapshot, per-question typed answers with probabilities and confidence, and the computed gate outcome. Auditable alongside existing skill executions.

```mermaid
erDiagram
    DecisionExecutionResult {
        uuid id
        uuid tenant_id "FK to Tenant, nullable"
        uuid skill_id "FK to Skill"
        uuid definition_id "FK to DecisionSkillDefinition"
        uuid conversation_session_id "FK to ConversationSession, nullable"
        json input_state_snapshot
        json answers "per question: typed value, probabilities, confidence"
        enum outcome "act | confirm | escalate"
        enum status "succeeded | failed"
        string provider_model "e.g. jev-latest"
        datetime created_at
    }
    DecisionSkillDefinition ||--o{ DecisionExecutionResult : "produces"
    Skill ||--o{ DecisionExecutionResult : "executed as"
    Tenant ||--o{ DecisionExecutionResult : "scopes"
    ConversationSession ||--o{ DecisionExecutionResult : "records"
```

## 2. Modified Entities

- **Skill** (existing) — gains a `skill_type` discriminator (`enum`: `tool_based` | `decision`, default `tool_based`) so decision skills are first-class members of the existing skill/permission/SOP model. No other Skill behavior changes; decision skill specifics live in `DecisionSkillDefinition`.
- **DecisionQuestion as child entity (chosen over json attribute)** — questions are repeated, ordered, individually editable in the authoring form, and need per-question type validation; a child entity keeps the authoring API and audit story clean. State preset and answers, by contrast, are stored as `json` since they are opaque mappings/snapshots.

```mermaid
erDiagram
    Skill {
        uuid id
        uuid tenant_id "FK to Tenant, nullable"
        string name
        string description
        string instructions
        enum skill_type "tool_based | decision (NEW)"
        boolean is_active
        boolean is_system
        datetime created_at
        datetime updated_at
    }
```

## 3. Removed Entities/Fields

None.

## 4. Schema File References

Files under `backend/app/db/models/` to update:

- `skills.py` — add `skill_type` to `Skill`; add `DecisionSkillDefinition` and `DecisionQuestion` models (or a new `decision_skills.py` if a separate file is preferred, registered in `__init__.py`).
- `system_one_provider_config.py` — **new file** for `SystemOneProviderConfig`.
- `results.py` — add `DecisionExecutionResult` (or new `decision_results.py`).
- `__init__.py` — register any new model modules.

## 5. Master Data Model Update Instructions

- `docs/master/data-model/overview.md` — add `SystemOneProviderConfig`, `DecisionSkillDefinition`, `DecisionQuestion`, and `DecisionExecutionResult` to the ER diagram; show Skill → DecisionSkillDefinition specialization; show Skill `skill_type` attribute.
- `docs/master/data-model/modules/skills/entities.md` — add the decision skill entities (names and one-line purposes only, no schema code) to the skills module entity list.
- If a tenancy/system-config module entity list exists, add `SystemOneProviderConfig` there; note the encrypted API key attribute (write-only, never returned in plaintext).
