# PRD: Expand Model Config Providers

## Epic Overview

Parthenon's Model Configurations module currently ships with a fixed set of four LLM provider types — `openai`, `anthropic`, `litellm_proxy`, and `azure_openai` — and of those only `openai` has been validated end-to-end. The underlying LangChain deep-agent runtime, however, exposes first-class chat-model integrations with many more major, API-key-based providers, and operators are routinely asked to bring their own accounts with whichever vendor their organization has standardised on. This change extends the Model Configurations registry so platform administrators can configure, persist credentials for, enable models from, and route agent inferences to a curated set of additional API-key-based LLM providers through the existing model configuration UI and APIs, with no change to the agent authoring or execution flows. OAuth, federated, or service-account auth flows are explicitly out of scope for this change — all new providers authenticate with a single API key.

## Business Goals

- **G1 — Provider coverage parity with LangChain's API-key tier.** Ship first-class configuration and runtime support for a curated set of major API-key-based LLM providers in this change, with a documented path for adding more in future waves, so Parthenon can serve organisations that have standardised on vendors other than OpenAI or Anthropic.
- **G2 — Zero-friction enablement for new providers.** Operators can register a new LLM vendor — display name, provider type, base URL, API key, and enabled models — entirely through the existing Model Configurations UI, with the new provider appearing in the dropdown on the same release that the backend recognises it.
- **G3 — Reuse existing security and operational guarantees.** All new providers store credentials in the existing AES-256 credential vault, surface only credential-presence flags in the UI, respect the existing `is_disabled` cascade, and emit the same observability signals as the four incumbent providers — no new secret-handling code path is introduced.
- **G4 — Predictable runtime behaviour for agents.** Agent Types continue to reference a provider-scoped `model_id` string; the runtime binding layer resolves the correct provider configuration from the extended registry, so authoring an Agent Type against a new vendor follows the exact same workflow as authoring one against OpenAI.
- **G5 — Operator confidence in vendor choice.** Each new provider ships with a curated list of well-known model identifiers surfaced in the "Fetch Models" experience (live listing where the vendor supports it, static curated list otherwise), so operators can enable models without consulting external documentation.

## Users & Personas

- **Platform Administrator (primary user).** Owns the Model Configurations page. Wants to add a new LLM vendor, paste an API key, and enable the specific models the organisation has licences for — without involving engineering. Needs confidence that the credential is stored securely, that the agent runtime will dispatch to the right vendor, and that they can roll back by deleting the configuration.
- **Agent Author / Business User (downstream beneficiary).** Configures Agent Types and selects a `model_id` from the centrally managed catalogue. Wants the list of available models to expand as soon as a new provider is configured, so they can pick the best model for the agent's purpose (reasoning, speed, cost, sovereignty) without leaving the agent authoring screen.
- **Compliance / Security Reviewer (indirect stakeholder).** Audits which LLM vendors the platform can talk to and confirms that API keys for new vendors follow the same encryption-at-rest, never-returned-to-client, and audit-logged-access patterns as the four incumbent providers.
- **Agent Runtime Operator (operational stakeholder).** Monitors agent executions. Wants clear provider attribution in logs and errors so that when a 4xx/5xx comes back from a vendor, the operator can immediately tell which provider the failing agent was talking to.

## User Stories

- **US-1.** As a Platform Administrator, I want to select additional LLM providers (such as Google Gemini, Mistral AI, Cohere, Groq, Together AI, Fireworks AI, Perplexity, and DeepSeek) from the Model Configuration create/edit dialog, so that I can register non-OpenAI/Anthropic vendors in Parthenon without code changes.
- **US-2.** As a Platform Administrator, I want to paste an API key for any supported provider, save the configuration, and have the credential encrypted and never displayed back to me, so that I can onboard a new vendor with the same security guarantees as the existing four providers.
- **US-3.** As a Platform Administrator, I want the "Fetch Models" button on a new provider's edit dialog to return a curated list of well-known model identifiers (or a live list where the vendor exposes one), so that I can enable specific models without consulting the vendor's external documentation.
- **US-4.** As a Platform Administrator, I want the existing Model Configurations list page to show a distinct, recognisable provider chip for each new provider, so that I can visually distinguish configurations across many vendors at a glance.
- **US-5.** As an Agent Author, I want the model picker in the Agent Type form to expose models from any newly configured provider, so that I can build agents that use, for example, Gemini or Mistral without leaving the authoring workflow.
- **US-6.** As an Agent Runtime Operator, I want the agent execution logs and error messages to clearly identify which LLM provider a failing call was made against, so that I can diagnose vendor-specific issues quickly.
- **US-7.** As a Compliance / Security Reviewer, I want every new provider to follow the same credential-storage and credential-rotation patterns as the existing four providers, so that audit findings remain consistent as the vendor catalogue grows.
- **US-8.** As a Platform Administrator, I want to delete or disable a Model Configuration that uses a new provider, with the same safety checks (e.g. blocking deletion if an Agent Type still references one of its enabled models), so that lifecycle management is consistent regardless of vendor.

## Acceptance Criteria

The change is complete when all of the following are observably true. The criteria are grouped so that the test plan can map one-for-one to them. References to test files are paths declared in `docs/config.yaml` `source.tests`; references to source files are paths from the workspace root.

### A. Provider Catalogue (Registry)

- **AC-1.** The provider registry recognises the following eight new provider keys, in addition to the existing four: `gemini`, `mistral`, `cohere`, `groq`, `together`, `fireworks`, `perplexity`, `deepseek`. The full set of twelve keys is documented as the supported provider catalogue.
- **AC-2.** Each of the eight new providers can be stored in a `ModelConfig` row, returned by the existing list / get / create / update / delete endpoints, and selected from the provider-type dropdown in the Model Configurations create and edit dialogs.
- **AC-3.** The provider-type dropdown in the frontend lists all twelve providers with a human-readable label, and the existing list page renders a distinct chip colour for each (mapping defined in the implementation, no two providers share a colour).
- **AC-4.** Existing `ModelConfig` records with provider type in `{openai, anthropic, litellm_proxy, azure_openai}` continue to be returned and editable without any data migration; their `provider_type` value is preserved exactly.

### B. CRUD Lifecycle for the Extended Catalogue

Following the standard CRUD acceptance pattern for the provider configuration dialog and list page:

- **AC-5.** **Create.** An admin can create a Model Config for any of the eight new providers, supplying display name, optional `api_base_url`, API key, and an `enabled_models` list. After save, the new row appears in the Model Configurations table without a manual page reload, and the dialog closes.
- **AC-6.** **Create — validation.** The dialog rejects submission when the display name is empty, and shows a clear validation message in the dialog. Permission-denied (HTTP 403) and other API failures appear inline in the dialog using the standard dialog error pattern, not as silent failures.
- **AC-7.** **Read.** The list endpoint returns all Model Config records the caller is authorised to see, with `provider_type` correctly populated for the new providers. Each row shows the display name, the provider chip, a credentials-set / not-set indicator, the enabled-model count, and the existing Edit / Delete actions.
- **AC-8.** **Update — edit dialog pre-population.** Opening the edit dialog for a config with one of the new providers pre-populates the display name, the correct provider in the dropdown, the `api_base_url`, the `enabled_models` chips, and the API-key placeholder (never the raw value).
- **AC-9.** **Update — parent table refresh.** After saving edits, the parent Model Configurations table refreshes automatically to reflect the new values, with no manual page reload.
- **AC-10.** **Update — provider type change.** Editing a config and changing its `provider_type` from one new provider to another (for example, from `gemini` to `mistral`) is allowed and persists, with the chip colour and label in the list page updating accordingly.
- **AC-11.** **Delete — confirmation.** Deleting a config triggers the existing delete-confirmation dialog (already localised) and, on confirmation, removes the row from the table immediately.
- **AC-12.** **Delete — safety guard.** Deletion is blocked (with a clear error) if any Agent Type still references one of the config's enabled models, mirroring the behaviour of the existing four providers.
- **AC-13.** **Delete — recreate.** After a config is deleted, an admin can create a new config with the same display name, the same provider, and a fresh API key, confirming true deletion rather than soft-delete.
- **AC-14.** **Disable / enable toggle.** The existing vendor-level `is_disabled` toggle works for the new providers with the same cascade semantics as for the incumbent providers.
- **AC-15.** **Refresh after dialog close.** After closing any create / edit / delete dialog for a new provider's configuration, the parent Model Configurations table refreshes automatically, mirroring the requirement for the existing providers.

### C. Runtime Dispatch

- **AC-16.** When an agent invokes a model whose ID is bound to a new provider's configuration, the call reaches the correct vendor using that vendor's credential, and the response is delivered back to the agent.
- **AC-17.** Agent invocations against the new providers produce text and tool-call outcomes consistent with what the vendor documents for its flagship models.
- **AC-18.** Usage information is captured for every invocation of a new provider; if a vendor does not report usage, the call still completes successfully and usage is recorded as unavailable.
- **AC-19.** When a vendor call returns a 4xx / 5xx error, the error log clearly identifies the provider key (for example, `gemini`, `mistral`) and the underlying error message from the vendor, so operators can diagnose the failure.

### D. Model Listing ("Fetch Models") Per Provider

- **AC-20.** For each of the eight new providers, the existing "Fetch Models" capability on the model configuration edit screen returns a non-empty list of well-known model identifiers, sourced either from a live vendor listing endpoint (where the vendor exposes one) or from a curated static list maintained alongside the code.
- **AC-21.** The curated list for each new provider is documented in the implementation and is up to date with the vendor's generally available flagship model families at the time of release. Operators can extend the list for their own organisation by manually editing `enabled_models` after fetching.
- **AC-22.** Failures while listing models (network error, invalid key, vendor outage) degrade gracefully: the endpoint returns an empty list, the UI shows the existing "no models returned" state, and the admin is never blocked from saving the configuration.

### E. Security, Encryption, and Audit

- **AC-23.** API keys for the new providers are encrypted with the existing platform vault before storage; the encrypted blob is never returned to the frontend (the `has_credentials` flag is the only credential-derived field in `ModelConfigRead`).
- **AC-24.** Editing a config and leaving the API-key field at the placeholder does not overwrite the existing stored credential; providing a new value replaces it; clearing the field explicitly clears the stored credential.
- **AC-25.** Audit and observability signals (OpenTelemetry traces, structured logs) emitted for inference calls to the new providers include the provider key, the model id, the config display name, and standard latency / status attributes, consistent with the existing four providers.

### F. Internationalisation

- **AC-26.** Each of the eight new providers has an English display label in the i18n catalogue (`frontend/src/i18n/locales/en.json` under the existing `agents.modelConfigs` namespace). Provider keys are stable identifiers; labels are translatable strings and may differ across locales.

### G. Test Coverage

- **AC-27.** Backend unit tests in `backend/tests/unit/test_model_config_service.py` and `backend/tests/unit/test_model_binding.py` cover the CRUD lifecycle (create, read, update, delete, conflict) and the runtime dispatch path (resolve, call, error) for each of the eight new providers, with provider-specific behaviour exercised by at least one dedicated test case per provider.
- **AC-28.** Backend API tests in `backend/tests/api/test_model_configs_api.py` cover list, create, update, and delete over the full twelve-provider catalogue, asserting that the response payload round-trips the provider key correctly.
- **AC-29.** Frontend unit tests in `frontend/src/__tests__/ModelConfigDialog.test.tsx` and `frontend/src/__tests__/ModelConfigListPage.test.tsx` cover: all twelve providers appear in the dropdown; the create flow produces a row in the list without a manual reload; the edit flow pre-populates correctly; the delete flow removes the row; and the table refreshes after each dialog closes.
- **AC-30.** E2E tests in `e2e/tests/agent-runtime.spec.ts` (in the model configurations block) cover the same flows against a running backend: list page renders all providers as chips; create dialog accepts a new provider and the row appears; edit dialog saves changes; delete dialog removes the row; the page is responsive and reload-free.

## Out of Scope

The following are explicitly **not** part of this change:

- **OAuth, federated, or service-account authentication flows.** All eight new providers authenticate with a single API key. Vertex AI (Google service-account JSON), Azure AD-issued Azure OpenAI keys, AWS Bedrock, and similar auth flows are deferred to a future change.
- **Model Context Protocol (MCP) / tool-calling standardisation across providers.** Each provider's tool-calling surface is supported through LangChain's existing adapter; Parthenon does not introduce a new tool-call translation layer.
- **Image, audio, embedding, or fine-tuning endpoints.** Only chat-completions (and the closest vendor equivalent) are in scope. Embedding and image endpoints are out of scope.
- **Streaming responses in the agent runtime.** The dispatcher returns a single completion response, as it does today. Token-by-token streaming from vendor to UI is a future enhancement.
- **A provider marketplace or self-service signup.** Adding a new provider remains an engineering / release activity; this change does not introduce dynamic provider registration at runtime.
- **Provider-specific model capability flags** (context-window overrides, function-calling toggles, JSON-mode toggles). The change exposes the existing `enabled_models` allowlist and leaves advanced per-model parameters to a future change.
- **Migration of existing `litellm_proxy` customers** to a specific new vendor. Operators can keep using the LiteLLM proxy as a single configuration that fans out to any vendor.
- **UI redesign of the Model Configurations page.** The list, dialog, and chip styling are extended, not redesigned.
- **Per-model cost / usage attribution by vendor.** Cost rollups already supported by the guardrail subsystem remain provider-agnostic; per-vendor cost breakdowns are a future change.

## Dependencies & Constraints

- **D-1 — Provider runtime availability.** Each of the eight new providers must be reachable from the agent runtime using the existing model binding path. The runtime call site for each provider must be configured and exercised end-to-end before the change ships. The technical implementation (vendor SDK vs. raw HTTP) is decided in `tech-spec.md`.
- **D-2 — Provider registry persistence.** The platform's persistent registry of supported provider types must be extended to accept the eight new keys, in addition to the four existing keys. The extension must be safe to apply on a running database and must not require any change to existing `ModelConfig` rows. The technical mechanism is defined in `data-model.md` and `tech-spec.md`.
- **D-3 — Encryption parity.** All API keys for new providers are encrypted with the existing AES-256 platform vault (`app/core/credential_vault.py`). The change does not introduce a new encryption mechanism.
- **D-4 — Service segregation.** Per the top-priority architecture rules in `docs/config.yaml`, agent runtime services cannot hold raw API keys. The control center remains the sole resolver of `ModelConfig` credentials; agent runtime requests model configs through the existing data-client path, and the dispatch path for new providers follows the same boundary.
- **D-5 — i18n policy.** All user-facing labels for the new providers live in `frontend/src/i18n/locales/en.json` and pass through the i18next `t()` function. No hard-coded provider labels in components.
- **D-6 — Backward compatibility.** All existing `ModelConfig` rows with provider type in `{openai, anthropic, litellm_proxy, azure_openai}` must continue to function without change. Existing API consumers, frontend callers, and the agent runtime must not require a redeploy to keep working.
- **D-7 — Test framework coverage.** The change is accepted only when the three test layers (backend pytest, frontend Vitest, E2E Playwright) all pass for the new behaviour, with at least one new test case per provider in the relevant layers, mirroring the existing coverage of the four incumbent providers.
- **D-8 — Observability.** The change does not introduce new telemetry exporters; it reuses the existing OpenTelemetry pipeline and structured logging configured via `config/telemetry.yaml`.
- **D-9 — Documentation update.** The corresponding master product spec, master architecture diagram, master data model, and master technology reference map entries are updated as part of this change, so that operator-facing documentation does not drift from the supported provider catalogue.
