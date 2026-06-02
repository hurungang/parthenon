# Spec Change: Expand Model Config Providers

## Affected Spec Areas

This change modifies the product, architecture, data-model, and technology master spec areas for the Model Configurations feature and the agent runtime. The user-facing capability is "extend the LLM provider catalogue", and it cascades through every layer that currently knows about the four-provider set.

| Master Spec Area | File(s) Touched |
|---|---|
| Product — Agent Management feature | `docs/master/product/features/agent-management.md` |
| Product — Agent Runtime Gateway feature | `docs/master/product/features/agent-runtime-gateway.md` |
| Product — Agent Types feature | `docs/master/product/features/agent-types.md` |
| Product — new dedicated Model Configurations feature spec | `docs/master/product/features/model-configurations.md` (new) |
| Architecture — Model Configuration Service module | `docs/master/architecture/modules/model-config.md` |
| Architecture — Agent Runtime / System overview | `docs/master/architecture/system-overview.md` (Mermaid `flowchart` updated if needed) |
| Data Model — Agent Management module entities | `docs/master/data-model/modules/agents/entities.md` |
| Data Model — Overview entity-relationship diagram | `docs/master/data-model/overview.md` |
| Technology — Agent Management module tech spec (Code Reference Map) | `docs/master/technology/modules/agents/tech-spec.md` |
| QA — Agent runtime / engine test plans | `docs/master/qa/test-plans/agent-runtime-test-plan.md`, `docs/master/qa/test-plans/agent-engine-test-plan.md` |
| QA — Frontend / agents UI test plan | `docs/master/qa/test-plans/agents-ui-test-plan.md` |

> The `openspec/specs/` directory referenced in the change-lifecycle skill format does not exist in this workspace; the affected "spec areas" above are the live master spec files in `docs/master/`.

## New Capabilities

### NC-1. Extended LLM provider catalogue (8 new providers)

Parthenon's Model Configurations feature recognises and supports the following additional API-key-based LLM providers, each with the same admin workflow and security guarantees as the existing four (`openai`, `anthropic`, `litellm_proxy`, `azure_openai`):

- **Google Gemini** — Google's flagship chat-completions family via Google's `generateContent` API; uses a native (non-OpenAI-compatible) request shape.
- **Mistral AI** — European cloud, OpenAI-compatible chat-completions endpoint.
- **Cohere** — Enterprise chat, native Cohere `/chat` request shape.
- **Groq** — High-throughput inference, OpenAI-compatible chat-completions endpoint.
- **Together AI** — Open-weights model hosting, OpenAI-compatible chat-completions endpoint.
- **Fireworks AI** — Open-weights model hosting, OpenAI-compatible chat-completions endpoint.
- **Perplexity** — Search-augmented chat, OpenAI-compatible chat-completions endpoint.
- **DeepSeek** — Open-weights model hosting, OpenAI-compatible chat-completions endpoint.

The total supported catalogue for this change is twelve providers (4 existing + 8 new). Each new provider is selectable from the Model Configuration create / edit dialog, storable as a `ModelConfig` row, listable via the "Fetch Models" button, and dispatchable by the agent runtime.

**Rationale for the selected set:** the eight new providers collectively cover all four of LangChain's major provider categories in its API-key tier — (a) hyperscaler cloud (Gemini), (b) regional / European cloud (Mistral), (c) enterprise chat (Cohere), and (d) specialty and open-weights hosting (Groq for fast inference; Together and Fireworks for open-weights; Perplexity for search-augmented; DeepSeek for Chinese open-weights). The selection deliberately excludes pure aggregator gateways (such as OpenRouter), because the existing `litellm_proxy` provider already fills that role and a second aggregator would be redundant. Newer entrants (such as xAI / Grok) are deferred to a follow-on wave.

### NC-2. Per-provider model listing support

For each of the eight new providers, the existing "Fetch Models" capability on the model configuration edit screen returns a list of well-known model identifiers. The list is sourced from a live vendor listing endpoint (where the vendor exposes one) or, where the vendor does not expose a public model-listing endpoint, from a curated static list maintained alongside the dispatcher code. The UI surfaces the list in the existing "Fetch Models" picker unchanged.

### NC-3. Per-provider runtime dispatch path

For each of the eight new providers, the runtime model-binding layer routes the inference call to the correct vendor endpoint using the correct request shape and credential header:

- **OpenAI-compatible providers** (Mistral, Groq, Together, Fireworks, Perplexity, DeepSeek) reuse the existing OpenAI-style chat-completions dispatch with a per-provider `api_base_url` and the standard credential attached per the provider's convention.
- **Native-API providers** (Gemini, Cohere) use a vendor-specific request shape — the dispatcher translates Parthenon's internal message format into the vendor's expected payload and parses the vendor's response back into Parthenon's internal completion envelope.
- The response-extraction helpers (text content, tool calls, token usage) cover the new providers with the same `null`-on-unavailable semantics already used for the incumbent providers.

### NC-4. New dedicated Model Configurations feature spec

A new top-level product spec file `docs/master/product/features/model-configurations.md` is introduced (or, if the team prefers to keep the feature embedded in `agent-management.md`, the existing feature spec is updated in place to a comparable level of detail). The new spec describes the full Model Configurations capability — provider catalogue, CRUD lifecycle, credential security model, "Fetch Models" behaviour, and runtime resolution — so that operators have a single, current, business-language reference.

## Modified Capabilities

### MC-1. Supported provider catalogue in agent-management spec

**Before.** `docs/master/product/features/agent-management.md` references model provider configuration in passing but does not enumerate the supported provider catalogue. The architecture module spec `docs/master/architecture/modules/model-config.md` lists only "OpenAI, Anthropic, or similar provider APIs" and the "LiteLLM proxy" backend. The technology spec `docs/master/technology/modules/agents/tech-spec.md` enumerates the four provider keys as a hard-coded tuple.

**After.** All three specs enumerate the full twelve-provider catalogue and call out the per-provider dispatch family (OpenAI-compatible vs. native). The product spec confirms that new providers are added by release rather than by dynamic registration, and that adding a new provider remains an engineering-led activity.

### MC-2. ModelConfig entity `provider_type` enumeration

**Before.** `docs/master/data-model/modules/agents/entities.md` and `docs/master/data-model/overview.md` document the `ModelConfig.provider_type` field as a generic `enum provider_type` with no enumerated values. The data model therefore leaves the supported set implicit and reader-dependent.

**After.** Both data-model files enumerate the supported provider keys as a labelled set of twelve values, marking the eight new keys as added by this change. The data-model files remain schema-free (no SQL, no ORM, no column types) — only the value list changes.

### MC-3. Frontend ModelProviderType union

**Before.** The TypeScript `ModelProviderType` union in `frontend/src/types/index.ts` lists exactly the four incumbent provider keys as string literals. The provider dropdown array in `frontend/src/pages/agents/ModelConfigDialog.tsx` and the chip-colour map in `frontend/src/pages/agents/ModelConfigListPage.tsx` mirror that list.

**After.** All three places are extended in lockstep to the twelve-provider catalogue, with each new provider having a unique chip colour. Provider keys remain string literals in TypeScript so that the type acts as a compile-time guardrail against typos.

### MC-4. i18n strings

**Before.** The i18n catalogue under `frontend/src/i18n/locales/en.json`'s `agents.modelConfigs` namespace contains labels and helper text keyed off the existing four providers; there are no provider-specific keys.

**After.** The same namespace is extended with a `providerLabels` map that holds the human-readable English display name for each of the twelve providers. The dropdown and the list chip both read from this map, so adding a new locale requires only a single translation entry per provider.

### MC-5. Runtime model binding dispatch surface

**Before.** The dispatcher in `backend/app/services/agents/model_binding.py` recognises only the four incumbent providers. Each provider has a hard-coded branch in `complete_from_context`, `complete`, `extract_text`, `extract_tool_calls`, and `extract_usage`. The `_list_*` helpers in `backend/app/services/agents/model_config_service.py` cover the same four.

**After.** The dispatcher recognises the eight new providers, with branches grouped by dispatch family (OpenAI-compatible vs. native) so that the OpenAI-compatible providers share a single dispatch path. The list-models path returns a curated list per new provider.

### MC-6. Test plans

**Before.** Test plans in `docs/master/qa/test-plans/agent-runtime-test-plan.md`, `docs/master/qa/test-plans/agent-engine-test-plan.md`, and `docs/master/qa/test-plans/agents-ui-test-plan.md` reference "model configuration" but do not enumerate per-provider scenarios.

**After.** Each relevant test plan is updated to call out the per-provider scenarios added by this change, with pointers to the specific test files in `backend/tests/`, `frontend/src/__tests__/`, and `e2e/tests/`.

## Removed Capabilities

None. This change is purely additive. The four incumbent providers continue to work as before, and no existing capability is deprecated, hidden, or removed.

## Spec Update Instructions

The following bullets describe what to change in the master spec files. They are ordered so that downstream agents can apply them in sequence.

1. **Create or expand `docs/master/product/features/model-configurations.md`.**
   - Prefer a new dedicated feature spec over inlining everything into `agent-management.md`.
   - Document the twelve-provider catalogue as a single business-language list, with a one-line note per provider describing the dispatch family.
   - Document the full CRUD lifecycle (create, read, update, delete, disable / enable), the credential-encryption model, the "Fetch Models" behaviour, and the runtime resolution contract.

2. **Update `docs/master/product/features/agent-management.md`.**
   - In the "What It Does" and "Key Concepts" sections, replace any reference to a fixed "OpenAI, Anthropic, LiteLLM, Azure" provider set with a reference to the central Model Configurations feature spec.
   - Update "Acceptance Criteria" so that the model-selection criterion names "Model Configurations" as the source of truth rather than enumerating providers inline.

3. **Update `docs/master/product/features/agent-types.md` and `docs/master/product/features/agent-runtime-gateway.md`.**
   - Replace any hard-coded provider list with a reference to the Model Configurations feature spec.
   - Add a one-line statement that the model picker in the Agent Type form is sourced from the centrally managed catalogue and grows as new providers are configured.

4. **Update `docs/master/architecture/modules/model-config.md`.**
   - In the "Supported Backend Types" table, add a row per new provider family (OpenAI-compatible and native) and call out which vendors fall into each family.
   - In the `ModelConfig` entity table, note that `provider_type` is an open enum with twelve recognised values and a documented extension path.
   - In the Mermaid `flowchart`, do not change the diagram (the new providers do not change the runtime resolution flow); add a note below the diagram that lists the supported providers by dispatch family.

5. **Update `docs/master/architecture/system-overview.md` only if the diagram is provider-specific.**
   - Most of the system-overview diagrams are provider-agnostic and require no change.
   - If any diagram explicitly names the four providers, replace those names with a generic "LLM provider (catalog)" label and link to the Model Configurations feature spec.

6. **Update `docs/master/data-model/modules/agents/entities.md`.**
   - In the Mermaid `erDiagram` `ModelConfig` block, keep the `enum provider_type` attribute type but add a comment in the entity table describing the twelve supported values.
   - Add a one-paragraph note that the enum is extended through Alembic migrations and that adding a new value is a release-led activity.

7. **Update `docs/master/data-model/overview.md`.**
   - In the Mermaid `erDiagram` `ModelConfig` block, mirror the entity-module change above.
   - If the overview text names the four providers, replace the names with a generic reference.

8. **Update `docs/master/technology/modules/agents/tech-spec.md`.**
   - In the Code Reference Map, update any row that names the four providers to reflect the twelve-provider catalogue.
   - Update the `ModelConfig` model description and the `ModelConfigRead` / `ModelConfigCreate` / `ModelConfigUpdate` schema descriptions to note that the provider-type field accepts the twelve keys.
   - Update the `ModelProviderType` frontend type description to list the twelve keys.
   - In any "How to add a new provider" or "Configuration catalogue" narrative, add a brief paragraph that describes the two dispatch families (OpenAI-compatible and native) and where in the codebase a new provider would be registered.

9. **Update `docs/master/qa/test-plans/agent-runtime-test-plan.md` and `docs/master/qa/test-plans/agent-engine-test-plan.md`.**
   - In the "Coverage Areas" and "Critical Scenarios" sections, add a per-provider scenario block that points to the unit tests in `backend/tests/unit/test_model_config_service.py` and `backend/tests/unit/test_model_binding.py`, and to the API tests in `backend/tests/api/test_model_configs_api.py`.
   - Add a new "WHEN/THEN" scenario for each of the eight new providers asserting that a model id bound to a config of that provider is dispatched to the correct vendor endpoint, with a clear provider-key error on failure.

10. **Update `docs/master/qa/test-plans/agents-ui-test-plan.md`.**
    - In the "Coverage Areas" section, add a per-provider scenario block that points to the frontend tests in `frontend/src/__tests__/ModelConfigDialog.test.tsx` and `frontend/src/__tests__/ModelConfigListPage.test.tsx`, and to the model-configuration block of `e2e/tests/agent-runtime.spec.ts`.
    - Add a "WHEN/THEN" scenario asserting that the dropdown lists all twelve providers, that the create flow inserts a row without manual reload, and that the chip colour is unique per provider.

11. **Do not create or update** `docs/master/deployment/`, `docs/master/operations/`, or `docs/changes/expand-model-config-providers/deployment.md` / `operations.md`.
    - This change has `has_deployment_changes: false` and `has_operations_changes: false` per the change metadata.
    - No new environment variables, no new infrastructure, no new runbook — the change reuses the existing credential vault, OpenTelemetry pipeline, and Alembic migration mechanism.
