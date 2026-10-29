# Tech Spec: system-one-decision-skills

## Technical Overview

Parthenon gains a second decision-making pathway delivered as a user-definable **decision tool** module — not a skill type. Decision tools behave like Parthenon's built-in system tools: their input and output contracts are references to the platform's Agent Data Type Registry (`input_data_type_id` / `output_data_type_id` FKs to `AgentDataType` — no inline schema storage; referenced data types are protected from deletion while referenced), they carry an auto-generated tool description derived from their definition, and they are available to skills and agents exactly like system tools (`save_data`, `get_data`, `query_result`, …). Each decision tool wraps a predefined set of atomic typed questions (Choice, Score, Noul) — together with a state built from input/agent data via a guided state preset (property selectors populated from the chosen input data type; backtick-quoted state paths in question instructions auto-detected) — dispatched to the TypeSafe Jev System One API (base URL preset to `https://api.typesafe.ai/v1`; validated via a provider Test-connection endpoint), returning structured answers with probability distributions and per-question confidence. Confidence is gated against author-defined act/confirm thresholds into one of three outcomes (`act`, `confirm`, `escalate`). Decision tools are exposed as MCP tools through the Communication Hub MCP tool registry bridge with the canonical `decision____<name>` name built via the shared tool-naming convention (`TOOL_SEPARATOR` `"____"`; `decision` added to `RESERVED_SERVER_NAMES` next to `system`, mirrored in the frontend `toolNaming.ts`), mirroring how system tools are bridged with the `system____` prefix; the MCP hub reserved-slug rejection is extended to `decision`. Saved decision tools also appear in the tool registry listing when authoring skills, exactly like system tools. Authoring is AI-assisted: a generation endpoint reuses `workflow_authoring_service` (the same mechanism behind the skill editor's generation button) to draft questions and state mapping from the tool description and chosen data types. Decision Tools administration lives under the Agent module, alongside agents and skills. The TypeSafe API key is stored AES-256 encrypted and is held, decrypted, and used exclusively inside Control Center; Communication Hub only brokers invocations, Agent Runtime only receives structured results, and agents never see credentials. Skills are unchanged — the existing Skill model, authoring, and execution paths are reverted to their original state. Tenant containment applies to all managed data records: tool names are unique per tenant (each tenant may have its own `tool_a`).

## Component Breakdown

### Database models (loaded by Control Center only)
- **`DecisionTool`** — tenant-scoped user-defined decision tool mirroring system-tool entity conventions (name, description, is_active/enabled, tenant scoping); state preset, act/confirm thresholds, `input_data_type_id` / `output_data_type_id` nullable FKs to `AgentDataType` (no inline input/output schema storage), auto-generated description, provider model, status. Unique `(tenant_id, name)`. Referenced data types are protected from deletion (an `AgentDataType` cannot be deleted while referenced by a decision tool, mirroring the existing agent-type reference rule).
- **`DecisionToolQuestion`** — ordered child questions of a tool with type, instructions, type-appropriate criteria/options, required flag; unique `(decision_tool_id, question_key)`.
- **`SystemOneProviderConfig`** — per-provider credential row (initially `typesafe` with `jev-latest`); encrypted API key, base URL, enabled models, tenant scoping.
- **`DecisionExecutionResult`** — persisted execution keyed to the decision tool: state snapshot, per-question answers (values, probabilities, confidence, legend), gate outcome, status, provider model.
- **`Skill`** — unchanged/reverted; the previously added `skill_type` discriminator is removed.

### Control Center services
- **Provider Config Service** — CRUD over `SystemOneProviderConfig`; encrypts on write and decrypts only at call time via the existing `CredentialVault`; base URL preset to `https://api.typesafe.ai/v1` (non-editable for now); resolves the active enabled provider for execution and answers the configured-model status query used by the tool authoring gate; performs the Test-connection validation probe (lightweight outbound call with the stored key, following the existing `test_connection` router pattern of `system_config.py` / `mcp_hub.py` `test_mcp_session_connection`) — status-only response, the key is never returned.
- **Tool naming & reservation** — `decision` added to `RESERVED_SERVER_NAMES` in `backend/app/services/agents/tool_naming.py` (the shared `TOOL_SEPARATOR` `"____"` convention); decision tools surface canonically as `decision____<name>` through `build_tool_name`. The frontend mirror in `frontend/src/utils/toolNaming.ts` is updated to match. The MCP hub reserved-slug rejection in `backend/app/api/v1/mcp_hub.py` (currently 409 on `slug == "system"`) is extended to reject `decision`.
- **Decision Tool Service** — CRUD for decision tools and their ordered questions; per-tenant name uniqueness enforcement; per-type question validation (Choice: non-empty options; Score: ordered legend; Noul: no criteria); state preset mapping validation against the chosen input data type's properties; input/output data type reference validation (nullable, must resolve to existing `AgentDataType` records visible to the tenant — platform-level shared types allowed); deletion protection for referenced data types; enforces at least one question; tenant containment on all lookups and mutations.
- **Tool description generation** — auto-generates the tool description from the definition (purpose, questions, referenced input/output data types) and stores it on the entity; the generated description is what skills, agents, and MCP clients see.
- **AI-assisted authoring** — `POST /decision-tools/generate` reuses `workflow_authoring_service.generate_workflow_text` (the backend mechanism behind the skill editor's `POST /skills/workflow/generate`): input is the tool description plus the chosen input/output data types; output is drafted questions and state mapping for the author to review and adjust.
- **System One Client** — provider-agnostic outbound client interface with a `TypeSafeJevClient` implementation performing the authenticated POST (state, model, typed questions) with the key injected at call time; the preset base URL `https://api.typesafe.ai/v1` is used for both execution calls and the test-connection probe; transport injected for testability.
- **Decision Execution Engine** — orchestrates one execution: resolve decision tool (within tenant) → apply state preset to input/agent data → single evaluation dispatch of all questions → normalize typed answers → compute the confidence gate (confidence ≥ act → `act`; ≥ confirm → `confirm`; else `escalate`) → persist a `DecisionExecutionResult`. OTEL-instrumented. Re-keyed from skills to tools.
- **System-tools execution path** — the existing internal system-tools route resolves decision tools alongside built-in system tools; a `decision____`-prefixed dispatch executes the engine instead of an LLM tool call.
- **Tool registry listing** — the existing tool listing used when authoring skills (`GET /mcp/tools`, consumed by the skill editor's tool picker via `useMcpServers`) includes saved decision tools as `decision____<name>` alongside system tools, so authors attach them to skills with no extra step.
- **Permission resolution** — decision tools are granted like system tools through the existing role → tool permission path; no parallel permission system.

### Communication Hub
- **MCP tool registry bridge** — registers decision tools in the MCP `tools/list` catalog alongside system tools, with the canonical `decision____<name>` prefix built via `build_tool_name`, AgentDataType-derived input schema, and the auto-generated description (mirroring how system tools are bridged with the `system____` prefix); `tools/call` for `decision____`-prefixed names is forwarded to Control Center's system-tools execution path. Tenant-scoped catalog: tool names resolve within the caller's tenant, so identical names in different tenants never collide. CH holds no credentials and makes no external calls.

### Frontend
- **System One provider config UI** — system-configuration section managing the TypeSafe provider; base URL preset read-only (`https://api.typesafe.ai/v1`); write-only API key field; **Test connection** button calling the new provider test-connection endpoint with clear success/failure feedback; standard dialog error handling.
- **Decision Tools admin page** — decision-tool authoring flow under the **Agent module** navigation (where agents and skills are managed, not system configuration): configured-model check (blocking message when unconfigured) → name (with `decision` prefix convention) and description/purpose → input data type and output data type selectors (first definable rows) with read-only data type viewers in the dialog → question builder for the three question types → guided state preset mapper (property selectors populated from the chosen input data type; backtick-quoted state paths like `` `input.tier` `` auto-detected in question instructions and surfaced as suggested mappings; state-injection instruction text) → AI generation button (mirroring the skill editor's) → auto-generated description preview → confidence thresholds.
- **Skill authoring tool picker** — the existing tool registry listing (`/mcp/tools` via `useMcpServers`) lists saved decision tools as `decision____<name>` alongside system tools; canonicalization in `frontend/src/utils/toolNaming.ts` covers the `decision` server slug.
- **Decision results view** — renders per-question answers, probabilities, confidence, and gate outcome within the existing results browsing area.
- **Skill editor** — reverted to its original form; no decision-specific authoring UI.
- **Resource type mirror** — `system::system_one` registered in the frontend manifest so permissions are grantable in the UI.

## API Changes

| Route | Change | Description |
|---|---|---|
| `GET /api/v1/system-one/providers` | New | List System One provider configs (no key material in responses). |
| `POST /api/v1/system-one/providers` | New | Create a provider config; API key accepted on write only, stored encrypted. |
| `PATCH /api/v1/system-one/providers/{id}` | New | Update display/default model/enabled flag/enabled models; optional new API key; base URL is preset (`https://api.typesafe.ai/v1`) and non-editable for now. |
| `POST /api/v1/system-one/providers/{id}/test` | New | Provider Test-connection: Control Center performs a lightweight validation call to the preset base URL with the stored key (following the existing `test_connection` router pattern); returns success/failure status only — key never returned. |
| `DELETE /api/v1/system-one/providers/{id}` | New | Remove a provider config. |
| `GET /api/v1/system-one/status` | New | Whether an enabled System One model is configured (used by the tool authoring gate); returns provider/model identifiers only. |
| `GET /api/v1/decision-tools` | New | List decision tools within the caller's tenant, filterable by status. |
| `POST /api/v1/decision-tools` | New | Create a decision tool; input/output via `input_data_type_id` / `output_data_type_id` (nullable references to existing `AgentDataType` records) instead of inline schemas; enforces per-tenant name uniqueness and per-type question validation; rejects creation when no System One model is configured; the auto-generated description is returned in the response (and included in Read responses). |
| `GET /api/v1/decision-tools/{id}` | New | Tool detail including questions, referenced input/output data types, state preset, thresholds, and the auto-generated description. |
| `PUT /api/v1/decision-tools/{id}` | Modified | Update definition (data type references replace inline schema fields); re-validates references, questions, and state mapping against the chosen input data type, and regenerates the stored description. |
| `DELETE /api/v1/decision-tools/{id}` | New | Remove a decision tool and its questions. |
| `GET /api/v1/decision-tools/{id}/description` | New | Returns the auto-generated tool description (also included in Read responses). |
| `POST /api/v1/decision-tools/generate` | New | AI-assisted authoring: reuses `workflow_authoring_service` (the skill editor's generation mechanism); input is description + chosen input/output data types; output is drafted questions + state mapping for review. |
| `GET /api/v1/mcp/tools` | Modified | The tool registry listing used by the skill authoring tool picker now includes saved decision tools as `decision____<name>` alongside system tools. |
| `DELETE /api/v1/data-types/{id}` (Agent Data Type registry) | Modified | Deletion protection extended: returns 409 when the data type is referenced by a decision tool's `input_data_type_id` / `output_data_type_id` (in addition to the existing agent-type reference rule). |
| `POST /internal/system-tools/decision/execute` (system-tools path) | New | Internal CC route, re-keyed to decision tools; Communication Hub forwards `decision____`-prefixed tool calls here; request/response contract mirrors the existing system-tool execution contract plus structured decision payload. |
| MCP `tools/list` | Modified | Catalog includes decision tools with the canonical `decision____<name>` prefix, auto-generated description, and AgentDataType-derived input schema, alongside system tools. |
| `GET /api/v1/results/decision` | New | Query persisted decision execution results, filterable by tool, session, date range; used by the results view. |

Skills API routes are unchanged (reverted to original behavior). All new routes are JWT-protected, permission-checked against the registered resource types (`system::system_one` for provider config; the system-tool resource path for decision tools), and tenant-scoped.

## State Management

Frontend state additions (local component state and existing API-layer patterns; no new global store required):

- **Provider config form state** — provider fields with a read-only preset base URL (`https://api.typesafe.ai/v1`), plus `dialogError` (standard dialog error handling pattern), a write-only `apiKey` field that is never pre-filled from fetched data, and `testConnectionState` (idle/running/success/failure + message) driving the **Test connection** button.
- **Decision Tools admin page state** — tool list and selection; `systemOneStatus` (fetched status result and loading state) controlling the configured-model gate; tool form state with `name`, `description`/`purpose`, `inputDataTypeId` / `outputDataTypeId` selections (with fetched data type definitions for the read-only viewers), questions array (per-question type, instructions, criteria/options), `detectedStatePaths` (backtick-quoted paths auto-detected from question instructions), `statePreset` mapping whose property selectors are populated from the chosen input data type's fields, AI-generation request/loading state and drafted-results review state, generated-description preview, `actThreshold` / `confirmThreshold`, and `dialogError`.
- **Skill editor tool picker state** — unchanged mechanics; the fetched `/mcp/tools` listing now includes `decision____<name>` entries, grouped under the `decision` server slug like any other server.
- **Results view state** — fetched decision result rows plus expanded-question selection for probability rendering; standard loading/error states.
- **Resource type constants** — static additions to the frontend resource type manifest (constants, not runtime state).

## Data Access Patterns

- **All database access is server-side in Control Center** — per top-priority rules, only Control Center connects to PostgreSQL; the frontend never queries the database and calls only REST endpoints.
- **Provider credentials** — written encrypted, decrypted only at call time inside Control Center when the decision engine dispatches to TypeSafe; never serialized into any API response, log, or agent-visible payload.
- **Decision tool definitions** — read by Control Center at authoring (via the decision-tools API) and at execution time; questions are child rows managed transactionally with the tool; input/output contracts are resolved through `AgentDataType` lookups (nullable, tenant-visible: platform-level shared types or the caller's own tenant-scoped types); all reads/writes are tenant-filtered. Deletion of an `AgentDataType` referenced by any decision tool is rejected (409).
- **AgentDataType registry** — read at authoring time to populate the input/output data type selectors and the read-only type viewers, to populate the state-mapping property selectors from the chosen input type, and at execution time to build the structured input/output payloads; accessed only through Control Center (the frontend uses the existing data-types REST API).
- **Provider test-connection** — performed server-side by Control Center against the preset base URL with the stored key; the frontend only receives a status result; the key is never returned by any endpoint.
- **AI-assisted authoring** — the generate endpoint reads the tool description and the chosen data types server-side, calls the workflow-generation model via the existing `workflow_authoring_service` path, and returns a draft payload; no schema code is stored beyond the reviewed definition.
- **Execution results** — written by Control Center after each execution; read by the frontend through the results query endpoint for browsing/audit; always tenant-filtered.
- **TypeSafe API** — server-to-server from Control Center only; Agent Runtime and Communication Hub have no outbound access to it and never receive the key or the raw request.

## Code Reference Map

### Planned new files

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `DecisionTool` | model | Tenant-scoped decision tool with `input_data_type_id` / `output_data_type_id` AgentDataType FKs, preset, thresholds, generated description | `backend/app/db/models/decision_tools.py` |
| `DecisionToolQuestion` | model | Ordered typed question child of a decision tool | `backend/app/db/models/decision_tools.py` |
| `SystemOneProviderConfig` | model | Provider credential config with encrypted API key | `backend/app/db/models/system_one_provider_config.py` |
| `DecisionExecutionResult` | model | Persisted decision execution with answers and gate outcome, keyed to `decision_tool_id` | `backend/app/db/models/results.py` |
| model registration | module (modified) | Registers `decision_tools` and provider config modules for Alembic/ORM; drops `decision_skills` registration | `backend/app/db/models/__init__.py` |
| decision-tools migration | migration | Creates decision tool tables with unique `(tenant_id, name)`; drops `decision_skill` tables and the `skill_type` column; re-keys results | `backend/alembic/versions/` (generated file) |
| `DecisionToolCreate` / `DecisionToolUpdate` / `DecisionToolRead` / `DecisionToolQuestionCreate` / `DecisionExecutionResultRead` | schema | Tool, question, and result DTOs with per-type validation models | `backend/app/schemas/decision_tools.py` |
| `SystemOneProviderCreate` / `SystemOneProviderUpdate` / `SystemOneProviderRead` / `SystemOneStatus` | schema | Provider config DTOs (key write-only) and configured-model status response | `backend/app/schemas/system_one.py` |
| `DecisionToolService` | service | Tool/question CRUD, per-tenant name uniqueness, per-type question and preset validation, tenant containment | `backend/app/services/system_one/decision_tool_service.py` |
| `generate_tool_description` | function | Auto-generates the stored tool description from the definition (purpose, questions, referenced data types) | `backend/app/services/system_one/decision_tool_service.py` |
| `SystemOneProviderConfigService` | service | CRUD + vault-encrypted key handling; resolves active provider | `backend/app/services/system_one/provider_config_service.py` |
| `SystemOneClient` | interface | Provider-agnostic outbound client contract | `backend/app/services/system_one/client.py` |
| `TypeSafeJevClient` | class | TypeSafe Jev implementation of the System One client | `backend/app/services/system_one/client.py` |
| `DecisionExecutionEngine` | service | State build, dispatch, response normalization, result persistence — re-keyed to tools | `backend/app/services/system_one/decision_engine.py` |
| `compute_confidence_gate` | function | Maps confidences + thresholds to act/confirm/escalate | `backend/app/services/system_one/decision_engine.py` |
| decision-tools router | router | Decision-tools CRUD + description + `POST .../generate` (AI-assisted drafting) endpoints, tenant-scoped | `backend/app/api/v1/decision_tools.py` |
| decision execution route | endpoint (new) | Decision-tool execution on the internal system-tools path (re-keyed from the decision-skill route) | `backend/app/api/v1/internal/system_tools.py` |
| MCP bridge registration | module (modified) | Registers decision tools in the MCP catalog with the canonical `decision____<name>` name, auto-generated description, and AgentDataType-derived input schema; routes `decision____` calls to CC (mirrors system-tool bridging) | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| provider config router | router | Provider CRUD + `/status` endpoints | `backend/app/api/v1/system_one.py` |
| decision results router | router | Query endpoint for persisted decision results | `backend/app/api/v1/results.py` |
| `ResourceTypeManifest` + `MODULE_GROUPS` | constant (modified) | Registers `system::system_one` resource type | `backend/app/core/resource_types.py` |
| `DecisionToolsPage` | component | Admin decision-tools page (route under the **Agent module** navigation) | `frontend/src/pages/agents/DecisionToolsPage.tsx` (moved from `frontend/src/pages/system/`) |
| `DecisionToolForm` | component | Tool authoring form: model gate, data type selectors + read-only viewers, question builder, guided state mapping (backtick auto-detect, input-type-driven property selectors), AI generation button, description preview, thresholds | `frontend/src/components/decisionTools/DecisionToolForm.tsx` |
| `DecisionToolQuestionEditor` | component | Per-question typed editing (Choice/Score/Noul) | `frontend/src/components/decisionTools/DecisionToolQuestionEditor.tsx` |
| `DecisionResultView` | component | Renders answers, probabilities, confidence, gate outcome (wired as the "Decision Results" tab of the results repository page) | `frontend/src/components/results/DecisionResultView.tsx` + `frontend/src/pages/results/ResultRepositoryPage.tsx` |
| `decisionToolsApi` | api module | Frontend REST client for decision-tools CRUD and description | `frontend/src/api/decisionToolsApi.ts` |
| `systemOneApi` | api module | Frontend REST client for provider config and status | `frontend/src/api/systemOneApi.ts` |
| `RESOURCE_TYPE_MANIFEST` + `MODULE_GROUPS` | constant (modified) | Mirrors `system::system_one` for permission UI | `frontend/src/constants/resourceTypes.ts` |
| i18n resources | resource files (modified) | All new UI strings via i18next (`systemOne`, `decisionTools`, `results.decision` namespaces) | `frontend/src/i18n/locales/en.json` (single supported locale) |
| `useDialogErrorHandler` | hook (reused) | Standard dialog error handling in new forms | `frontend/src/hooks/useDialogErrorHandler.ts` |
| decision tools backend integration tests | tests | Migration verification, encryption, validation, tenant isolation (same tool name in two tenants), execution, MCP bridge routing | `backend/tests/integration/test_system_one_decision_tools.py` |
| decision frontend tests | tests | Provider form, decision tools form, results view | `frontend/src/__tests__/` (new decision-tool specs) |
| decision e2e specs | tests | Mocked variants + real-backend variant | `e2e/tests/` (new system-one specs) |

### Round-2 modifications (existing symbols)

| Symbol | Type | Change | File |
|--------|------|--------|------|
| decision-tools migration (round 2) | migration | Adds nullable `input_data_type_id` / `output_data_type_id` FKs to `decision_tools`; drops the inline input/output JSON schema columns (applied revision `d5e6a7b8c9d0`, chained on `c3f7a1d92e40`) | `backend/alembic/versions/d5e6a7b8c9d0_round_two_decision_tool_data_types.py` |
| `DecisionToolCreate` / `DecisionToolUpdate` / `DecisionToolRead` | schema (modified) | Inline input/output schema fields replaced by `input_data_type_id` / `output_data_type_id` + embedded data type summaries in Read responses | `backend/app/schemas/decision_tools.py` |
| `DecisionToolService` | service (modified) | Data type reference validation, deletion protection checks, state-mapping validation against the chosen input data type's properties | `backend/app/services/system_one/decision_tool_service.py` |
| `generate_decision_draft` | function (new) | AI-assisted authoring: builds prompts from description + chosen data types and reuses `workflow_authoring_service.generate_workflow_text` to draft questions + state mapping | `backend/app/services/system_one/decision_authoring_service.py` |
| provider test-connection route | endpoint (new) | `POST /system-one/providers/{id}/test` — lightweight validation probe against the preset base URL with the stored key (follows the `test_connection` pattern of `system_config.py` / `mcp_hub.py` `test_mcp_session_connection`); status-only response | `backend/app/api/v1/system_one.py` |
| `SystemOneProviderUpdate` | schema (modified) | Base URL removed from editable fields (preset `https://api.typesafe.ai/v1`) | `backend/app/schemas/system_one.py` |
| `RESERVED_SERVER_NAMES` | constant (modified) | Adds `"decision"` next to `"system"` so no MCP server slug collides with the decision-tool namespace | `backend/app/services/agents/tool_naming.py` |
| reserved-slug rejection | router (modified) | 409 check extended from `slug == "system"` to also reject `slug == "decision"` | `backend/app/api/v1/mcp_hub.py` |
| AgentDataType deletion protection | service (modified) | Rejects deletion of a data type referenced by a decision tool (`input_data_type_id` / `output_data_type_id`), in addition to the existing agent-type reference rule | `backend/app/services/` data-type service + `backend/app/api/v1/data_types.py` |
| tool registry listing | router (modified) | `GET /mcp/tools` listing includes saved decision tools as `decision____<name>` alongside system tools | `backend/app/api/v1/mcp_hub.py` |
| tool-naming mirror | util (modified) | Canonicalization/reserved-name handling covers the `decision` server slug (`decision____<name>`) | `frontend/src/utils/toolNaming.ts` |
| Agent module navigation | routing (modified) | Decision Tools admin route/menu entry moved under the Agent module (from the system area) | `frontend/src/app/AppRouter.tsx` (route `/agents/decision-tools`) + `frontend/src/app/AppShell.tsx` (Agent group nav entry) |
| `DecisionToolsPage` / `DecisionToolForm` | components (modified) | Data type selectors with read-only viewers replace schema editing; guided state mapping (backtick path auto-detection, input-type-driven property selectors, state-injection instruction text); AI generation button; form field order (name, description, input/output types, questions, state mapping) | `frontend/src/pages/agents/DecisionToolsPage.tsx`, `frontend/src/components/decisionTools/DecisionToolForm.tsx` |
| `detect_state_placeholders` | util (new) | Extracts backtick-quoted state paths (e.g. `` `input.tier` ``) from question instruction text for suggested state mappings | `frontend/src/utils/decisionStatePaths.ts` |
| provider config UI | component (modified) | Read-only preset base URL + **Test connection** button with status feedback | `frontend/src/pages/system/` System One provider section |
| decision-tools API client | api module (modified) | Adds `generate` call and data-type-ref fields; system-one client adds `testConnection` | `frontend/src/api/decisionToolsApi.ts`, `frontend/src/api/systemOneApi.ts` |
| decision tool backend tests (round 2) | tests | Data type ref validation/deletion protection, test-connection endpoint, reserved-slug rejection, `decision____` naming, generate endpoint | `backend/tests/integration/test_system_one_decision_tools.py` |
| decision frontend tests (round 2) | tests | Data type selectors, guided mapping, AI generation, test-connection button, Agent-module placement, toolNaming mirror | `frontend/src/__tests__/` (decision-tool specs) |
| decision e2e specs (round 2) | tests | Variants updated for `decision____` naming and data-type-driven authoring | `e2e/tests/` (system-one specs) |

### Reverts (modified-for-revert — restore original state)

| Symbol | Type | Revert | File |
|--------|------|--------|------|
| `Skill.skill_type` | model (revert) | Removes the `tool_based` \| `decision` discriminator; restores original Skill model | `backend/app/db/models/skills.py` |
| `DecisionSkillDefinition` / `DecisionQuestion` | model (removed) | Deletes the decision-skill models file | `backend/app/db/models/decision_skills.py` |
| `SkillCreate` / `SkillUpdate` / `SkillRead` (decision fields) | schema (revert) | Removes `skill_type` and nested decision payload from skill DTOs | `backend/app/schemas/skills.py` |
| `DecisionSkillDefinitionCreate` / `DecisionQuestionCreate` | schema (removed) | Deletes the decision-skill DTO module | `backend/app/schemas/decision_skills.py` |
| skills router (decision handling) | router (revert) | Removes the decision-type gate and definition payload handling | `backend/app/api/v1/skills.py` |
| skill executor decision routing | function (revert) | Removes the `decision` skill_type delegation to the engine | `backend/app/services/skills/executor.py` |
| `DecisionSkillService` | service (removed) | Superseded by `DecisionToolService` | `backend/app/services/system_one/decision_skill_service.py` |
| skill editor decision integration | component (revert) | Removes skill-type selector and decision authoring payload; restores original editor | `frontend/src/components/agents/SkillEditor.tsx` |
| `DecisionSkillForm` | component (removed) | Superseded by `DecisionToolForm` | `frontend/src/components/skills/DecisionSkillForm.tsx` |
| decision-skill tests | tests (removed/replaced) | Decision-skill specs replaced by decision-tool specs | `backend/tests/integration/test_system_one_decision_skills.py`, `frontend/src/__tests__/DecisionSkillForm.test.tsx`, `frontend/src/__tests__/DecisionQuestionEditor.test.tsx`, `e2e/tests/system-one-decision-skills.spec.ts` |

## Implementation Notes / Deviations

- **Resource type** — no pre-existing "system tools" resource type existed, so decision tools got a dedicated `system::decision_tools` resource type registered in BOTH `backend/app/core/resource_types.py` and `frontend/src/constants/resourceTypes.ts` (actions: create/read/update/delete/manage). `system::system_one` remains for provider config.
- **MCP bridge catalog** — the bridge fetches the caller's tenant decision-tool catalog from CC via the new internal route `POST /api/v1/internal/system-tools/decision/list` and exposes each tool as `decision____<name>` (canonical `TOOL_SEPARATOR` naming, `decision` reserved server slug) with its auto-generated description and AgentDataType-derived input schema; `decision____` calls are forwarded to `POST /api/v1/internal/system-tools/decision/execute`. Both routes are in the CH allowlist in `backend/app/api/deps.py`. `build_catalog` is now async and `McpSession` carries the API key's bound `tenant_id` (session tenant binding — never client-supplied).
- **Permission gating** — decision-tool exposure and dispatch resolve within the caller's tenant (tenant containment is the permission boundary at the MCP surface). Role-skill-binding grants of individual decision tools would require a new role→tool entity and are left to the permission-model workstream; the routes themselves are JWT/service-certificate protected.
- **Naming** — stored names are plain (e.g. `tool_a`); the `decision____` prefix exists only at the MCP/tool surface. The REST API stores/exposes the plain name and an immutable name (rename creates a new tool).
- **Data type references (round 2)** — input/output schemas are never stored on the tool; they are `AgentDataType` references (nullable). The registry's globally unique name/slug identifies types; decision tools reference existing records by id and inherit their scoping. Deletion protection rejects removing a referenced type (409), mirroring the agent-type reference rule.
- **Provider preset + test connection (round 2)** — the base URL is preset to `https://api.typesafe.ai/v1` and non-editable for this release; the Test-connection endpoint performs the validation probe server-side and returns status only (never the key), following the existing `test_connection` router pattern.
- **Round-2 registry listing** — `GET /mcp/tools` and `GET /mcp/servers` expose a virtual `decision` server (id `00000000-0000-0000-0000-000000000002`) with each enabled tenant decision tool listed as `decision____<name>` (UUIDv5-derived stable tool ids), so the skill editor tool picker groups decision tools under the `decision` slug with zero extra authoring steps.
- **State placeholder helper** — backtick path extraction exists on both sides: `extract_state_placeholders` in `backend/app/services/system_one/decision_authoring_service.py` (returned by the generate endpoint as `detected_state_paths`) and `detectStatePlaceholders` in `frontend/src/utils/decisionStatePaths.ts` (drives the form's "Auto-detect placeholders" button).
