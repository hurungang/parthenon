# Tech Spec: system-one-decision-skills

## Technical Overview

Parthenon gains a second decision-making pathway: a new `decision` skill type whose execution dispatches a predefined set of atomic typed questions (Choice, Score, Noul) — together with a state built from input/agent data via a state preset — to the TypeSafe Jev System One API, returning structured answers with probability distributions and per-question confidence. Confidence is gated against author-defined act/confirm thresholds into one of three outcomes (`act`, `confirm`, `escalate`). The TypeSafe API key is stored AES-256 encrypted and is held, decrypted, and used exclusively inside Control Center; Communication Hub only brokers invocations, Agent Runtime only receives structured results, and agents never see credentials. Decision skills are first-class members of the existing skill/permission/SOP model — no parallel permission system.

## Component Breakdown

### Database models (loaded by Control Center only)
- **`Skill.skill_type`** — discriminator (`tool_based` | `decision`, default `tool_based`) making decision skills ordinary Skills for permission, roles, and SOPs.
- **`SystemOneProviderConfig`** — per-provider credential row (initially `typesafe` with `jev-latest`); encrypted API key, base URL, enabled models, tenant scoping.
- **`DecisionSkillDefinition`** — one-to-one specialization of a `decision` Skill: state preset, act/confirm thresholds, active flag.
- **`DecisionQuestion`** — ordered child questions with type, instructions, type-appropriate criteria/options, required flag.
- **`DecisionExecutionResult`** — persisted execution: state snapshot, per-question answers (values, probabilities, confidence, legend), gate outcome, status, provider model.

### Control Center services
- **Provider Config Service** — CRUD over `SystemOneProviderConfig`; encrypts on write and decrypts only at call time via the existing `CredentialVault`; resolves the active enabled provider for execution and answers the configured-model status query used by the skill editor gate.
- **Decision Skill Service** — CRUD for definitions and their ordered questions; validates each question against its type's rules (Choice: non-empty options; Score: ordered legend; Noul: no criteria) and validates state preset mappings; enforces at least one question.
- **System One Client** — provider-agnostic outbound client interface with a `TypeSafeJevClient` implementation performing the authenticated POST (state, model, typed questions) with the key injected at call time; transport injected for testability.
- **Decision Execution Engine** — orchestrates one execution: resolve skill → apply state preset to input/agent data → single evaluation dispatch of all questions → normalize typed answers → compute the confidence gate (confidence ≥ act → `act`; ≥ confirm → `confirm`; else `escalate`) → persist a `DecisionExecutionResult`. OTEL-instrumented.
- **Skill Executor routing** — the existing skill executor delegates to the decision engine when the invoked skill's `skill_type` is `decision`, returning the structured result in the existing execution result shape; all other skill types unchanged.
- **Permission resolution** — unchanged; decision skills flow through the existing role → skill permission path.

### Communication Hub
- **Skill invocation routing** — recognizes decision skills on the existing agent/SOP invocation path and forwards to Control Center; holds no credentials and makes no external calls.

### Frontend
- **System One provider config UI** — system-configuration section managing the TypeSafe provider; write-only API key field; standard dialog error handling.
- **Skill editor decision flow** — type selector → configured-model check (blocking message when unconfigured) → question builder for the three question types → state preset mapper → confidence thresholds.
- **Decision results view** — renders per-question answers, probabilities, confidence, and gate outcome within the existing results browsing area.
- **Resource type mirror** — `system::system_one` registered in the frontend manifest so permissions are grantable in the UI.

## API Changes

| Route | Change | Description |
|---|---|---|
| `GET /api/v1/system-one/providers` | New | List System One provider configs (no key material in responses). |
| `POST /api/v1/system-one/providers` | New | Create a provider config; API key accepted on write only, stored encrypted. |
| `PATCH /api/v1/system-one/providers/{id}` | New | Update display/base URL/default model/enabled flag/enabled models; optional new API key. |
| `DELETE /api/v1/system-one/providers/{id}` | New | Remove a provider config. |
| `GET /api/v1/system-one/status` | New | Whether an enabled System One model is configured (used by the skill editor gate); returns provider/model identifiers only. |
| `POST /api/v1/skills` | Modified | Accepts `skill_type=decision`; when decision, requires an active definition payload and returns a structured error if no System One model is configured. |
| `PATCH /api/v1/skills/{id}` | Modified | Same decision-type handling for updates. |
| `GET /api/v1/skills/{id}` | Modified | Skill detail includes the decision definition (questions, state preset, thresholds) when `skill_type=decision`. |
| `POST /api/v1/skills/{id}/execute` (existing invocation path) | Modified | For decision skills, executes the decision engine and returns structured per-question answers with confidence and gate outcome. |
| `GET /api/v1/results/decision` | New | Query persisted decision execution results, filterable by skill, session, date range; used by the results view. |
| Internal CC decision execution route (existing CC internal surface) | Modified | Communication Hub forwards decision-skill invocations to Control Center's decision execution path; request/response contract mirrors existing skill invocation plus structured decision payload. |

All new routes are JWT-protected and permission-checked against the registered resource types (`system::system_one` for provider config; the existing skill resource type for authoring/invocation).

## State Management

Frontend state additions (local component state and existing API-layer patterns; no new global store required):

- **Provider config form state** — provider fields plus `dialogError` (standard dialog error handling pattern) and a write-only `apiKey` field that is never pre-filled from fetched data.
- **Skill editor state** — `skillType` selection; `systemOneStatus` (fetched status result and loading state) controlling the configured-model gate; `questions` array with per-question type, instructions, criteria/options; `statePreset` mapping; `actThreshold` / `confirmThreshold`.
- **Results view state** — fetched decision result rows plus expanded-question selection for probability rendering; standard loading/error states.
- **Resource type constants** — static additions to the frontend resource type manifest (constants, not runtime state).

## Data Access Patterns

- **All database access is server-side in Control Center** — per top-priority rules, only Control Center connects to PostgreSQL; the frontend never queries the database and calls only REST endpoints.
- **Provider credentials** — written encrypted, decrypted only at call time inside Control Center when the decision engine dispatches to TypeSafe; never serialized into any API response, log, or agent-visible payload.
- **Decision definitions** — read by Control Center at authoring (via skills API) and at execution time; questions are child rows managed transactionally with the definition.
- **Execution results** — written by Control Center after each execution; read by the frontend through the results query endpoint for browsing/audit.
- **TypeSafe API** — server-to-server from Control Center only; Agent Runtime and Communication Hub have no outbound access to it and never receive the key or the raw request.

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `Skill` (skill_type) | model (modified) | Adds `tool_based` \| `decision` discriminator | `backend/app/db/models/skills.py` |
| `SystemOneProviderConfig` | model | Provider credential config with encrypted API key | `backend/app/db/models/system_one_provider_config.py` |
| `DecisionSkillDefinition` | model | One-to-one decision specialization of a Skill | `backend/app/db/models/decision_skills.py` |
| `DecisionQuestion` | model | Ordered typed question child of a definition | `backend/app/db/models/decision_skills.py` |
| `DecisionExecutionResult` | model | Persisted decision execution with answers and gate outcome | `backend/app/db/models/results.py` |
| model registration | module (modified) | Registers new model modules for Alembic/ORM | `backend/app/db/models/__init__.py` |
| `system_one_provider_configs` migration | migration | Autogenerated migration for all new entities and `skill_type` | `backend/alembic/versions/` (generated file) |
| `SystemOneProviderCreate` / `SystemOneProviderUpdate` / `SystemOneProviderRead` | schema | Provider config DTOs, key write-only | `backend/app/schemas/system_one.py` |
| `SystemOneStatus` | schema | Configured-model status response for the authoring gate | `backend/app/schemas/system_one.py` |
| `DecisionSkillDefinitionCreate` / `DecisionQuestionCreate` / `DecisionExecutionResultRead` | schema | Definition, question, and result DTOs with per-type validation models | `backend/app/schemas/decision_skills.py` |
| `SkillCreate` / `SkillUpdate` / `SkillRead` (decision fields) | schema (modified) | Skill DTOs extended with `skill_type` and nested decision payload | `backend/app/schemas/skills.py` |
| `SystemOneProviderConfigService` | service | CRUD + vault-encrypted key handling; resolves active provider | `backend/app/services/system_one/provider_config_service.py` |
| `DecisionSkillService` | service | Definition/question CRUD and type validation | `backend/app/services/system_one/decision_skill_service.py` |
| `SystemOneClient` | interface | Provider-agnostic outbound client contract | `backend/app/services/system_one/client.py` |
| `TypeSafeJevClient` | class | TypeSafe Jev implementation of the System One client | `backend/app/services/system_one/client.py` |
| `DecisionExecutionEngine` | service | State build, dispatch, response normalization, result persistence | `backend/app/services/system_one/decision_engine.py` |
| `compute_confidence_gate` | function | Maps confidences + thresholds to act/confirm/escalate | `backend/app/services/system_one/decision_engine.py` |
| skill executor decision routing | function (modified) | Delegates `decision` skills to the engine | `backend/app/services/skills/executor.py` |
| decision invocation routing | function (modified) | Forwards decision-skill invocations CC-ward, no credentials | `backend/app/communication_hub/` (skill invocation module) |
| provider config router | router | Provider CRUD + `/status` endpoints | `backend/app/api/v1/system_one.py` |
| skills router (decision handling) | router (modified) | Decision type gate on create/update; definition in detail | `backend/app/api/v1/skills.py` |
| decision results router | router | Query endpoint for persisted decision results | `backend/app/api/v1/results.py` |
| `ResourceTypeManifest` + `MODULE_GROUPS` | constant (modified) | Registers `system::system_one` resource type | `backend/app/core/resource_types.py` |
| `SystemOneProviderConfigPage` | component | Admin provider config UI with write-only key field | `frontend/src/pages/system/SystemOneProviderConfigPage.tsx` |
| `DecisionSkillForm` | component | Decision authoring form: type gate, question builder, state preset, thresholds | `frontend/src/components/skills/DecisionSkillForm.tsx` |
| `DecisionQuestionEditor` | component | Per-question typed editing (Choice/Score/Noul) | `frontend/src/components/skills/DecisionQuestionEditor.tsx` |
| `DecisionResultView` | component | Renders answers, probabilities, confidence, gate outcome | `frontend/src/components/results/DecisionResultView.tsx` |
| `systemOneApi` | api module | Frontend REST client for provider config and status | `frontend/src/api/systemOneApi.ts` |
| skills API client (decision fields) | api module (modified) | Skill CRUD/execute payloads extended for decision type | existing frontend skills API module under `frontend/src/api/` |
| `RESOURCE_TYPE_MANIFEST` + `MODULE_GROUPS` | constant (modified) | Mirrors `system::system_one` for permission UI | `frontend/src/constants/resourceTypes.ts` |
| i18n resources | resource files (modified) | All new UI strings via i18next | `frontend/src/i18n/` |
| `useDialogErrorHandler` | hook (reused) | Standard dialog error handling in new forms | `frontend/src/hooks/useDialogErrorHandler.ts` |
| decision skills backend integration tests | tests | Migration verification, encryption, validation, execution, routing | `backend/tests/integration/test_system_one_decision_skills.py` |
| decision frontend tests | tests | Provider form, authoring form, results view | `frontend/src/__tests__/` (new decision-skill specs) |
| decision e2e specs | tests | Mocked variants + real-backend variant | `e2e/tests/` (new system-one specs) |
