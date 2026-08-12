# Tech Spec: expand-model-config-providers

## Technical Overview

This change extends Parthenon's Model Configuration Service to recognise twelve LLM provider keys (the four incumbent `openai` / `anthropic` / `litellm_proxy` / `azure_openai` plus eight new `gemini` / `mistral` / `cohere` / `groq` / `together` / `fireworks` / `perplexity` / `deepseek`). The provider-type allowlist is widened at three layers: the Python `ModelProvider` enum and the Postgres `model_provider_enum` (via an additive Alembic migration), the dispatch surface in `backend/app/services/agents/model_binding.py` (refactored into a `PROVIDER_REGISTRY` facade that routes the six OpenAI-compatible providers through a single shared call path and gives the two native-API providers their own per-vendor branches), and the model-lister in `backend/app/services/agents/model_config_service.py` (a shared `_list_openai_compat_models` helper for the six OpenAI-compatible providers plus curated static lists for Gemini and Cohere). The frontend `ModelProviderType` union, the `PROVIDERS` dropdown array, the `providerColor` chip-colour map, and the i18n catalogue are extended in lockstep. The Agent Runtime boundary is unchanged: the runtime still receives a decrypted `model_config_dict` from `ControlCenterDataClient.get_model_config` and never holds raw API keys at rest. No new top-priority architecture rule from `docs/config.yaml` is violated.

## Component Breakdown

### `ModelProvider` enum (modified)

- **Responsibility:** canonical allowlist of LLM provider keys, used by the SQLAlchemy `model_configs.provider_type` column, the runtime dispatcher, the model-lister, and the Pydantic `ModelConfigCreate` / `ModelConfigUpdate` / `ModelConfigRead` schemas.
- **File:** `backend/app/db/models/agents.py`
- **Public symbols touched:** `ModelProvider` (enum), its 4 incumbent members (`openai`, `anthropic`, `litellm_proxy`, `azure_openai`), and 8 new members (`gemini`, `mistral`, `cohere`, `groq`, `together`, `fireworks`, `perplexity`, `deepseek`).

### `ModelConfig` ORM (unchanged in shape, indirectly updated)

- **Responsibility:** persistence of one LLM provider configuration per row, including the encrypted API-key blob and the enabled-models allowlist.
- **File:** `backend/app/db/models/agents.py`
- **Public symbols touched:** `ModelConfig` (ORM class) — no attribute is renamed, added, or removed; the `provider_type` column is unchanged in shape.

### `ModelBindingLayer` and the new `PROVIDER_REGISTRY` (modified and new)

- **Responsibility:** resolve a `model_id` to a `ModelConfig`, dispatch the chat-completion call to the right vendor endpoint, and normalise the response into Parthenon's internal completion envelope (text, tool calls, usage). The new `PROVIDER_REGISTRY` is a thin in-process map that lets the dispatcher route by family without a four-branch `if/elif` ladder.
- **File:** `backend/app/services/agents/model_binding.py`
- **Public symbols touched:**
  - `ModelBindingError` (exception, unchanged)
  - `ModelBindingLayer` (class, unchanged)
  - `ModelBindingLayer.resolve_model_config` (method, unchanged)
  - `ModelBindingLayer.fetch_model_config_via_client` (method, unchanged)
  - `ModelBindingLayer.complete_from_context` (method, refactored to dispatch by registry)
  - `ModelBindingLayer.complete` (method, refactored to dispatch by registry)
  - `ModelBindingLayer._resolve_api_key` (private method, unchanged)
  - `ModelBindingLayer._call_openai_compat` (private method, unchanged; reused by the 6 new OpenAI-compatible providers)
  - `ModelBindingLayer._call_anthropic` (private method, unchanged)
  - `ModelBindingLayer._call_gemini` (private method, new)
  - `ModelBindingLayer._call_cohere` (private method, new)
  - `ModelBindingLayer.extract_text` (static method, widened to cover the new providers)
  - `ModelBindingLayer.extract_tool_calls` (static method, widened to cover the new providers)
  - `ModelBindingLayer.extract_usage` (static method, widened to cover the new providers)
  - `OPENAI_DEFAULT_ENDPOINT` (module-level constant, unchanged)
  - `ANTHROPIC_DEFAULT_ENDPOINT` (module-level constant, unchanged)
  - `PROVIDER_REGISTRY` (module-level constant, new)

### `ModelConfigService` and the new lister helpers (modified and new)

- **Responsibility:** CRUD for `ModelConfig` rows with AES-256 credential encryption, plus the "Fetch Models" capability that returns the available model identifiers for a given provider.
- **File:** `backend/app/services/agents/model_config_service.py`
- **Public symbols touched:**
  - `ModelConfigNotFoundError` (exception, unchanged)
  - `ModelConfigConflictError` (exception, unchanged)
  - `ModelConfigService` (class, unchanged)
  - `ModelConfigService.create_model_config` (method, unchanged)
  - `ModelConfigService.list_model_configs` (method, unchanged)
  - `ModelConfigService.get_model_config` (method, unchanged)
  - `ModelConfigService.update_model_config` (method, unchanged)
  - `ModelConfigService.delete_model_config` (method, unchanged)
  - `ModelConfigService.fetch_available_models` (method, unchanged)
  - `ModelConfigService.list_models_for_config` (method, refactored to route the 12 providers)
  - `ModelConfigService._list_openai_models` (private method, may delegate to the new shared helper)
  - `ModelConfigService._list_azure_models` (private method, unchanged)
  - `ModelConfigService._list_litellm_models` (private method, may delegate to the new shared helper)
  - `ModelConfigService._list_openai_compat_models` (private method, new — shared by Mistral, Groq, Together, Fireworks, Perplexity, DeepSeek, OpenAI, LiteLLM, Azure OpenAI)
  - `ModelConfigService._list_gemini_models` (private method, new — curated static list)
  - `ModelConfigService._list_cohere_models` (private method, new — curated static list)

### Pydantic schemas for `ModelConfig` (unchanged in shape, indirectly updated)

- **Responsibility:** define the request and response shapes for the `ModelConfig` REST API.
- **File:** `backend/app/schemas/agents.py`
- **Public symbols touched:** `ModelConfigCreate`, `ModelConfigUpdate`, `ModelConfigRead` (Pydantic classes, unchanged in shape; `provider_type` field automatically accepts the 8 new enum members).

### REST API endpoints for `ModelConfig` (unchanged in shape, indirectly updated)

- **Responsibility:** expose the CRUD lifecycle and the "Fetch Models" capability over HTTP.
- **File:** `backend/app/api/v1/agents.py`
- **Public symbols touched:**
  - `ModelConfigRouter` (APIRouter instance, unchanged)
  - `_model_config_service` (module-level singleton, unchanged)
  - `list_model_configs` (endpoint, unchanged — response includes the 12 provider types)
  - `create_model_config` (endpoint, unchanged — accepts the 12 provider types)
  - `get_model_config` (endpoint, unchanged)
  - `update_model_config` (endpoint, unchanged — accepts provider-type changes across the 12 keys)
  - `delete_model_config` (endpoint, unchanged — same 409 safety guard)
  - `list_models_for_config` (endpoint, unchanged — returns a non-empty list for each of the 12 providers)
  - `get_workflow_generation_model` (endpoint, unchanged — `options` list automatically includes models from the 8 new providers)
  - `set_workflow_generation_model` (endpoint, unchanged — same 422 guard for non-enabled models)

### Internal data-client endpoint for `ModelConfig` (unchanged, indirectly updated)

- **Responsibility:** return the `ModelConfig` row with decrypted credentials to the Agent Runtime over the internal mTLS channel.
- **File:** `backend/app/api/v1/internal/agent_data.py`
- **Public symbols touched:** `get_model_config` (internal endpoint, unchanged — `provider_type` field is forwarded as the string-literal value).

### `ControlCenterDataClient` (unchanged, indirectly updated)

- **Responsibility:** Agent Runtime data client that fetches the `ModelConfig` dict over the internal channel.
- **File:** `backend/agent_runtime/data_client.py`
- **Public symbols touched:**
  - `ControlCenterDataClient` (class, unchanged)
  - `ControlCenterDataClient.get_model_config` (method, unchanged — returns a dict whose `provider_type` is one of the 12 string literals)

### Agent Runtime call sites (unchanged, indirectly updated)

- **Responsibility:** orchestrate the LLM call inside the agent loop.
- **File:** `backend/app/services/agents/runtime_executor.py`
- **Public symbols touched:** the call sites that invoke `ModelBindingLayer.complete`, `ModelBindingLayer.complete_from_context`, `ModelBindingLayer.extract_text`, `ModelBindingLayer.extract_tool_calls`, and `ModelBindingLayer.extract_usage` continue to work without modification because the public surface of `ModelBindingLayer` is widened, not narrowed.

### Credential vault (unchanged, used unchanged)

- **Responsibility:** AES-256-GCM encryption and decryption of API keys at rest.
- **File:** `backend/app/core/credential_vault.py`
- **Public symbols touched:**
  - `CredentialVault` (class, unchanged)
  - `CredentialVault.encrypt` (method, unchanged)
  - `CredentialVault.decrypt` (method, unchanged)
  - `get_vault` (function, unchanged)

### Alembic migration (new)

- **Responsibility:** additively extend the Postgres `model_provider_enum` with the 8 new values.
- **File:** new file under `backend/alembic/versions/`, chaining from the most recent revision `f4a5b6c7d8e9`. Uses `postgresql.ENUM(..., create_type=False)` and a non-parameterised `ALTER TYPE` statement (no `.bindparams()`).
- **Public symbols touched:** none — the migration is a one-shot DDL artifact.

### Frontend type union (modified)

- **Responsibility:** compile-time guardrail for the LLM provider key on the wire.
- **File:** `frontend/src/types/index.ts`
- **Public symbols touched:** `ModelProviderType` (TypeScript union — extended with 8 new string-literal members; existing 4 preserved in order).

### Frontend data shapes (unchanged, indirectly updated)

- **Responsibility:** describe the `ModelConfig` and `WorkflowGenerationModelOption` shapes used by the UI.
- **File:** `frontend/src/types/index.ts`
- **Public symbols touched:** `ModelConfig` (TypeScript interface, unchanged in shape) and `WorkflowGenerationModelOption` (TypeScript interface, unchanged in shape — `provider_type` is typed by the widened `ModelProviderType`).

### `ModelConfigDialog` component (modified)

- **Responsibility:** create / edit a `ModelConfig` row, including provider-type selection, API-key entry, and the "Fetch Models" picker.
- **File:** `frontend/src/pages/agents/ModelConfigDialog.tsx`
- **Public symbols touched:**
  - `ModelConfigDialog` (component, modified — the dropdown renders all 12 providers; the existing standard dialog error pattern is preserved)
  - `ModelConfigDialogProps` (TypeScript interface, unchanged)
  - `PROVIDERS` (module-level constant — extended to 12 entries)
  - `API_KEY_PLACEHOLDER` (module-level constant, unchanged)

### `ModelConfigListPage` component (modified)

- **Responsibility:** render the table of `ModelConfig` rows with the provider chip, credentials indicator, and Edit / Delete actions.
- **File:** `frontend/src/pages/agents/ModelConfigListPage.tsx`
- **Public symbols touched:**
  - `ModelConfigListPage` (component, modified — the chip-colour map is widened)
  - `providerColor` (function defined inside the component, extended to 12 entries with no duplicate colours)

### `useAvailableModels` hook (unchanged, indirectly updated)

- **Responsibility:** return the flat union of `enabled_models` across all configured `ModelConfig` rows, for use by guardrail and workflow-generation dialogs.
- **File:** `frontend/src/hooks/useAvailableModels.ts`
- **Public symbols touched:** `useAvailableModels` (hook, unchanged — the returned `AvailableModel[]` automatically includes models from the 8 new providers).

### `AvailableModel` type (unchanged, indirectly updated)

- **Responsibility:** describe one available model for use in guardrail and workflow-generation dialogs.
- **File:** `frontend/src/components/agents/AvailableModel.ts`
- **Public symbols touched:** `AvailableModel` (TypeScript interface, unchanged in shape; `provider_type` field is typed by the widened `ModelProviderType`).

### i18n catalogue (modified)

- **Responsibility:** hold the human-readable English display labels for every provider key.
- **File:** `frontend/src/i18n/locales/en.json`
- **Public symbols touched:** the `agents.modelConfigs.providerLabels` map (or equivalent nested key) gains 8 new entries. The existing `agents.modelConfigs.*` keys (title, subtitle, create, edit, delete, etc.) are preserved.

### Test files (extended)

- **Responsibility:** cover the new behaviour at every layer of the test pyramid.
- **Files (all extended, none replaced):**
  - `backend/tests/unit/test_model_binding.py` — adds resolve + dispatch + 4xx log tests for each of the 8 new providers.
  - `backend/tests/unit/test_model_config_service.py` — adds CRUD lifecycle tests and list-models tests for the 8 new providers.
  - `backend/tests/api/test_model_configs_api.py` — adds round-trip tests for the full 12-provider catalogue.
  - `frontend/src/__tests__/ModelConfigDialog.test.tsx` — adds dropdown, create-flow, edit-flow, delete-flow, and chip-colour tests for the 12 providers.
  - `frontend/src/__tests__/ModelConfigListPage.test.tsx` — adds chip-rendering, delete-confirmation, and table-refresh tests for the 12 providers.
  - `e2e/tests/agent-runtime.spec.ts` — adds the `model-configurations` block with at least one real-backend variant.

## API Changes

This change does not add, remove, or rename any HTTP endpoint. It widens the request and response shapes accepted and returned by the existing `ModelConfig` endpoints so that the 8 new `provider_type` string literals round-trip cleanly. Specifically:

- The `provider_type` field on `ModelConfigCreate`, `ModelConfigUpdate`, and `ModelConfigRead` (defined in `backend/app/schemas/agents.py` as the `ModelProvider` enum) accepts and returns the 8 new values. The wire shape (`provider_type: "gemini" | "mistral" | ...`) is unchanged; only the enum members are extended.
- `GET /api/v1/agents/model-configs` returns a list whose `provider_type` field may now be any of the 12 values; the list page renders all 12 as distinct chips.
- `POST /api/v1/agents/model-configs` accepts the 12 values; the request body shape is otherwise unchanged.
- `PUT /api/v1/agents/model-configs/{config_id}` accepts a `provider_type` change across the 12 values (e.g. from `gemini` to `mistral`); the request body shape is otherwise unchanged.
- `DELETE /api/v1/agents/model-configs/{config_id}` continues to return 409 if an `AgentType` references a model in the config's `enabled_models`; the safety guard is unchanged.
- `GET /api/v1/agents/model-configs/{config_id}/models` returns a non-empty list of model identifiers for any of the 12 providers; the response shape (`list[str]`) is unchanged. Network or credential failures degrade to `[]` with a logged error; the response is still 200.
- `GET /api/v1/agents/model-configs/workflow-generation` and `PUT /api/v1/agents/model-configs/workflow-generation` automatically include models from the 8 new providers in their `options` list, because the options list is derived from the same `ModelConfig.enabled_models` field; the request and response shapes are otherwise unchanged.
- The internal endpoint `GET /api/v1/internal/data/model-configs/{model_config_id}` (in `backend/app/api/v1/internal/agent_data.py`) returns the `provider_type` as a string-literal value; the response shape is unchanged.
- All endpoints continue to require the existing JWT authentication and `agent:<action>` permission; no new permission is introduced.
- All endpoints continue to emit OpenTelemetry traces and structured logs through the existing pipeline; the new providers are tagged with the same `provider` attribute as the incumbent ones.

## State Management

This change does not introduce a new Zustand store, React Query key, or persistent client-side state. The existing React Query cache key `['agents', 'model-configs']` (used by `useQuery` in `ModelConfigListPage` and invalidated by `queryClient.invalidateQueries` in the create / edit / delete handlers) is unchanged. The `useAvailableModels` hook continues to use the same query key `['agents', 'model-configs', 'available-models']` and is unaffected. The `ModelConfigDialog` component continues to use local `useState` for the form fields; no field is added, removed, or moved. The dropdown is purely a presentational extension of the existing `PROVIDERS` array.

## Data Access Patterns

- **Server-side, control center (DB owner).** CRUD for `ModelConfig` rows and the "Fetch Models" listing run in the Control Center (port 8000), which owns the Postgres connection per the top-priority architecture rules. `ModelConfigService` uses the async `AsyncSession` and the AES-256 vault via `get_vault()`.
- **Server-side, agent runtime (data-client).** The Agent Runtime does not connect to the database. It receives a decrypted `model_config_dict` over the internal mTLS channel via `ControlCenterDataClient.get_model_config`, and forwards it to `ModelBindingLayer.complete_from_context` and the extractors. The change preserves this boundary.
- **Client-side, frontend (REST).** The frontend continues to call the public REST API through `apiClient`; no direct database access. The `useQuery` cache key pattern is preserved.
- **Async patterns.** All I/O continues to be `async` / `await` with the existing `httpx.AsyncClient` for vendor calls, the existing `AsyncSession` for DB calls, and the existing `vault.encrypt` / `vault.decrypt` for credential handling. No new concurrency primitive is introduced.
- **Provider call timeout.** The existing 120-second timeout in `_call_openai_compat` and `_call_anthropic` is reused; the new `_call_gemini` and `_call_cohere` use the same timeout for consistency.
- **Model listing timeout.** The existing 10-second timeout in `_list_openai_models` and `_list_litellm_models` is reused; the new `_list_openai_compat_models` uses the same timeout.
- **Failure degradation.** The model-lister already returns `[]` and logs an error on network failure; the new helpers honour the same contract. The dispatcher already raises `ModelBindingError` on 4xx / 5xx; the new helpers honour the same contract.

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ModelProvider` | enum | Canonical allowlist of LLM provider keys; 4 incumbent + 8 new | `backend/app/db/models/agents.py` |
| `ModelProvider.openai` | enum member | Incumbent provider key | `backend/app/db/models/agents.py` |
| `ModelProvider.anthropic` | enum member | Incumbent provider key | `backend/app/db/models/agents.py` |
| `ModelProvider.litellm_proxy` | enum member | Incumbent provider key | `backend/app/db/models/agents.py` |
| `ModelProvider.azure_openai` | enum member | Incumbent provider key | `backend/app/db/models/agents.py` |
| `ModelProvider.gemini` | enum member | New provider key (this change) | `backend/app/db/models/agents.py` |
| `ModelProvider.mistral` | enum member | New provider key (this change) | `backend/app/db/models/agents.py` |
| `ModelProvider.cohere` | enum member | New provider key (this change) | `backend/app/db/models/agents.py` |
| `ModelProvider.groq` | enum member | New provider key (this change) | `backend/app/db/models/agents.py` |
| `ModelProvider.together` | enum member | New provider key (this change) | `backend/app/db/models/agents.py` |
| `ModelProvider.fireworks` | enum member | New provider key (this change) | `backend/app/db/models/agents.py` |
| `ModelProvider.perplexity` | enum member | New provider key (this change) | `backend/app/db/models/agents.py` |
| `ModelProvider.deepseek` | enum member | New provider key (this change) | `backend/app/db/models/agents.py` |
| `ModelConfig` | ORM class | Persistence for one LLM provider configuration | `backend/app/db/models/agents.py` |
| `AgentType` | ORM class | Defines one agent's model binding (unchanged; the public surface continues to hold `model_id` as a string) | `backend/app/db/models/agents.py` |
| `ModelBindingError` | exception | Raised by `ModelBindingLayer` on resolve or dispatch failure | `backend/app/services/agents/model_binding.py` |
| `ModelBindingLayer` | class | Resolves a `model_id` to a `ModelConfig` and dispatches the chat-completion call | `backend/app/services/agents/model_binding.py` |
| `ModelBindingLayer.resolve_model_config` | method | DB-backed resolver (Control Center side) | `backend/app/services/agents/model_binding.py` |
| `ModelBindingLayer.fetch_model_config_via_client` | method | Data-client-backed fetcher (Agent Runtime side) | `backend/app/services/agents/model_binding.py` |
| `ModelBindingLayer.complete_from_context` | method | Dispatcher entry point for the data-client call path | `backend/app/services/agents/model_binding.py` |
| `ModelBindingLayer.complete` | method | Dispatcher entry point for the ORM call path | `backend/app/services/agents/model_binding.py` |
| `ModelBindingLayer._resolve_api_key` | private method | Decrypts the API key from the stored blob | `backend/app/services/agents/model_binding.py` |
| `ModelBindingLayer._call_openai_compat` | private method | POSTs to an OpenAI-compatible `/chat/completions` endpoint; reused by the 6 new OpenAI-compatible providers | `backend/app/services/agents/model_binding.py` |
| `ModelBindingLayer._call_anthropic` | private method | POSTs to the Anthropic Messages API | `backend/app/services/agents/model_binding.py` |
| `ModelBindingLayer._call_gemini` | private method | New — POSTs to the Google Gemini native API | `backend/app/services/agents/model_binding.py` |
| `ModelBindingLayer._call_cohere` | private method | New — POSTs to the Cohere native API | `backend/app/services/agents/model_binding.py` |
| `ModelBindingLayer.extract_text` | static method | Extracts the assistant's text from a vendor response | `backend/app/services/agents/model_binding.py` |
| `ModelBindingLayer.extract_tool_calls` | static method | Extracts the tool-call list from a vendor response | `backend/app/services/agents/model_binding.py` |
| `ModelBindingLayer.extract_usage` | static method | Extracts the normalised usage dict from a vendor response | `backend/app/services/agents/model_binding.py` |
| `OPENAI_DEFAULT_ENDPOINT` | constant | Default OpenAI chat-completions URL | `backend/app/services/agents/model_binding.py` |
| `ANTHROPIC_DEFAULT_ENDPOINT` | constant | Default Anthropic Messages URL | `backend/app/services/agents/model_binding.py` |
| `PROVIDER_REGISTRY` | constant | New — maps each of the 12 provider keys to a dispatch-family tag and default base URL | `backend/app/services/agents/model_binding.py` |
| `ModelConfigNotFoundError` | exception | Raised by `ModelConfigService` when a config is not found | `backend/app/services/agents/model_config_service.py` |
| `ModelConfigConflictError` | exception | Raised by `ModelConfigService` when deletion is blocked by a referencing `AgentType` | `backend/app/services/agents/model_config_service.py` |
| `ModelConfigService` | class | CRUD for `ModelConfig` with AES-256 encryption | `backend/app/services/agents/model_config_service.py` |
| `ModelConfigService.create_model_config` | method | Creates a new `ModelConfig` row | `backend/app/services/agents/model_config_service.py` |
| `ModelConfigService.list_model_configs` | method | Lists all `ModelConfig` rows | `backend/app/services/agents/model_config_service.py` |
| `ModelConfigService.get_model_config` | method | Fetches one `ModelConfig` row by id | `backend/app/services/agents/model_config_service.py` |
| `ModelConfigService.update_model_config` | method | Updates one `ModelConfig` row | `backend/app/services/agents/model_config_service.py` |
| `ModelConfigService.delete_model_config` | method | Deletes one `ModelConfig` row (with the 409 safety guard) | `backend/app/services/agents/model_config_service.py` |
| `ModelConfigService.fetch_available_models` | method | Returns the `enabled_models` list, falling back to the lister | `backend/app/services/agents/model_config_service.py` |
| `ModelConfigService.list_models_for_config` | method | Returns the available model identifiers for a given provider | `backend/app/services/agents/model_config_service.py` |
| `ModelConfigService._list_openai_models` | private method | Lists models from the OpenAI `/models` endpoint | `backend/app/services/agents/model_config_service.py` |
| `ModelConfigService._list_azure_models` | private method | Returns a static list of common Azure OpenAI deployment names | `backend/app/services/agents/model_config_service.py` |
| `ModelConfigService._list_litellm_models` | private method | Lists models from a LiteLLM proxy `/models` endpoint | `backend/app/services/agents/model_config_service.py` |
| `ModelConfigService._list_openai_compat_models` | private method | New — shared OpenAI-compatible lister used by the 6 new OpenAI-compatible providers | `backend/app/services/agents/model_config_service.py` |
| `ModelConfigService._list_gemini_models` | private method | New — curated static list of Gemini models | `backend/app/services/agents/model_config_service.py` |
| `ModelConfigService._list_cohere_models` | private method | New — curated static list of Cohere models | `backend/app/services/agents/model_config_service.py` |
| `ModelConfigCreate` | Pydantic class | Request shape for `POST /agents/model-configs` | `backend/app/schemas/agents.py` |
| `ModelConfigUpdate` | Pydantic class | Request shape for `PUT /agents/model-configs/{id}` | `backend/app/schemas/agents.py` |
| `ModelConfigRead` | Pydantic class | Response shape for the `ModelConfig` endpoints | `backend/app/schemas/agents.py` |
| `ModelConfigRouter` | APIRouter | FastAPI router grouping the `ModelConfig` endpoints | `backend/app/api/v1/agents.py` |
| `_model_config_service` | singleton | Module-level `ModelConfigService` instance used by the router | `backend/app/api/v1/agents.py` |
| `list_model_configs` | endpoint | `GET /api/v1/agents/model-configs` | `backend/app/api/v1/agents.py` |
| `create_model_config` | endpoint | `POST /api/v1/agents/model-configs` | `backend/app/api/v1/agents.py` |
| `get_model_config` | endpoint (public) | `GET /api/v1/agents/model-configs/{config_id}` | `backend/app/api/v1/agents.py` |
| `update_model_config` | endpoint | `PUT /api/v1/agents/model-configs/{config_id}` | `backend/app/api/v1/agents.py` |
| `delete_model_config` | endpoint | `DELETE /api/v1/agents/model-configs/{config_id}` | `backend/app/api/v1/agents.py` |
| `list_models_for_config` | endpoint | `GET /api/v1/agents/model-configs/{config_id}/models` | `backend/app/api/v1/agents.py` |
| `get_workflow_generation_model` | endpoint | `GET /api/v1/agents/model-configs/workflow-generation` | `backend/app/api/v1/agents.py` |
| `set_workflow_generation_model` | endpoint | `PUT /api/v1/agents/model-configs/workflow-generation` | `backend/app/api/v1/agents.py` |
| `get_model_config` | endpoint (internal) | `GET /api/v1/internal/data/model-configs/{model_config_id}` — used by Agent Runtime | `backend/app/api/v1/internal/agent_data.py` |
| `ControlCenterDataClient` | class | Agent Runtime data client | `backend/app/agent_runtime/data_client.py` |
| `ControlCenterDataClient.get_model_config` | method | Fetches the decrypted `ModelConfig` dict over the internal channel | `backend/app/agent_runtime/data_client.py` |
| `CredentialVault` | class | AES-256-GCM encryption and decryption of credentials at rest | `backend/app/core/credential_vault.py` |
| `CredentialVault.encrypt` | method | Encrypts a plaintext string | `backend/app/core/credential_vault.py` |
| `CredentialVault.decrypt` | method | Decrypts a base64 ciphertext | `backend/app/core/credential_vault.py` |
| `get_vault` | function | Returns the singleton `CredentialVault` instance | `backend/app/core/credential_vault.py` |
| Alembic migration (new revision) | migration | New file under `backend/alembic/versions/` — additively extends the Postgres `model_provider_enum`; chains from `f4a5b6c7d8e9` | `backend/alembic/versions/<new_revision>.py` |
| `ModelProviderType` | type | TypeScript union of LLM provider keys; 4 incumbent + 8 new | `frontend/src/types/index.ts` |
| `ModelConfig` | interface | TypeScript shape of a `ModelConfig` row | `frontend/src/types/index.ts` |
| `WorkflowGenerationModelOption` | interface | TypeScript shape of one option in the workflow-generation picker | `frontend/src/types/index.ts` |
| `ModelConfigDialog` | component | Create / edit dialog for a `ModelConfig` | `frontend/src/pages/agents/ModelConfigDialog.tsx` |
| `ModelConfigDialogProps` | interface | Props for the dialog component | `frontend/src/pages/agents/ModelConfigDialog.tsx` |
| `PROVIDERS` | constant | Dropdown options for the provider-type picker; extended to 12 entries | `frontend/src/pages/agents/ModelConfigDialog.tsx` |
| `API_KEY_PLACEHOLDER` | constant | Placeholder used to indicate "API key already set" in the dialog | `frontend/src/pages/agents/ModelConfigDialog.tsx` |
| `ModelConfigListPage` | component | List page for `ModelConfig` rows | `frontend/src/pages/agents/ModelConfigListPage.tsx` |
| `providerColor` | function | Maps a provider key to an MUI 7 chip colour; extended to 12 entries with no duplicates | `frontend/src/pages/agents/ModelConfigListPage.tsx` |
| `useAvailableModels` | hook | Returns the flat union of `enabled_models` across all `ModelConfig` rows | `frontend/src/hooks/useAvailableModels.ts` |
| `AvailableModel` | interface | One available model entry in the guardrail / workflow-generation picker | `frontend/src/components/agents/AvailableModel.ts` |
| `agents.modelConfigs.*` | i18n namespace | English display labels and helper text for the Model Configurations feature | `frontend/src/i18n/locales/en.json` |
| `agents.modelConfigs.providerLabels` | i18n map | Human-readable English display label for each of the 12 provider keys | `frontend/src/i18n/locales/en.json` |
| Runtime call sites for `ModelBindingLayer` | call sites | The six call sites in the agent loop that invoke the dispatcher; unchanged in shape | `backend/app/services/agents/runtime_executor.py` |
| Backend unit tests — binding | test file | Resolve + dispatch + 4xx log tests for the 12 providers | `backend/tests/unit/test_model_binding.py` |
| Backend unit tests — service | test file | CRUD lifecycle and list-models tests for the 12 providers | `backend/tests/unit/test_model_config_service.py` |
| Backend API tests | test file | Round-trip tests for the full 12-provider catalogue | `backend/tests/api/test_model_configs_api.py` |
| Frontend unit tests — dialog | test file | Dropdown, create, edit, and delete tests for the 12 providers | `frontend/src/__tests__/ModelConfigDialog.test.tsx` |
| Frontend unit tests — list page | test file | Chip-rendering, delete-confirmation, and table-refresh tests | `frontend/src/__tests__/ModelConfigListPage.test.tsx` |
| E2E tests — agent runtime | test file | Model Configurations block with at least one real-backend variant | `e2e/tests/agent-runtime.spec.ts` |
