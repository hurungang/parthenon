# Model Configurations

## Overview

Model Configurations centralise all LLM provider metadata — provider type, API endpoint, encrypted credentials, and enabled model IDs — so that Agent Types can reference models by ID alone and the runtime binding layer can resolve credentials and endpoints at call time. Administrators manage configurations through the platform UI; the runtime dispatcher reads the catalogue at agent execution time.

## Supported Provider Catalogue

Parthenon supports twelve API-key-based LLM providers organised into two dispatch families:

### OpenAI-compatible (9 providers)

These providers share the same chat-completions request/response shape and can be dispatched through a single code path:

- **openai** — OpenAI (API key, GPT-4o / GPT-4.1 / O-series)
- **azure_openai** — Azure OpenAI (API key, deployment-scoped base URL)
- **litellm_proxy** — LiteLLM proxy gateway (API key, fan-out to any LLM)
- **mistral** — Mistral AI (API key, EU-hosted)
- **groq** — Groq (API key, high-throughput inference)
- **together** — Together AI (API key, open-weights hosting)
- **fireworks** — Fireworks AI (API key, open-weights hosting)
- **perplexity** — Perplexity (API key, search-augmented chat)
- **deepseek** — DeepSeek (API key, open-weights hosting)

### Native-API (3 providers)

These providers use vendor-native request/response shapes and have their own dispatch branches:

- **anthropic** — Anthropic (API key, Claude, Messages API)
- **gemini** — Google Gemini (API key, generateContent API)
- **cohere** — Cohere (API key, /chat API)

Adding a new API-key-based provider is an engineering-led release activity. The catalogue grows through a single coordinated release that registers the provider in the platform's provider registry, model lister, and admin UI — no dynamic registration at runtime.

## CRUD Lifecycle

Administrators can create, read, update, and delete Model Configurations through the Agents → Model Configurations page.

| Action | Description |
|---|---|
| **Create** | Select a provider type, give a display name, optionally set a base URL, enter an API key, and (optionally) fetch and enable specific models. The API key is encrypted before storage and never returned in read responses. |
| **Read** | The list page shows every configuration, with a distinct colour-coded provider chip, a credentials-set indicator, and the enabled-model count. |
| **Update** | All fields can be edited. Changing the `provider_type` from one vendor to another is allowed and persists. Leaving the API-key field at the placeholder does not overwrite the existing credential; providing a new value replaces it; clearing the field explicitly clears the credential. |
| **Delete** | A configuration can be deleted only if no Agent Type currently references one of its enabled models. If any Agent Type still uses a model from the configuration, deletion is blocked with a clear error. After deletion, a configuration with the same display name and provider can be re-created. |
| **Disable (vendor-level)** | The vendor-level `is_disabled` toggle cascades to every model under that vendor, blocking agent execution across all referencing agent types. |

## Credential Security

- API keys are encrypted at rest with AES-256-GCM via the platform's credential vault. The raw key is never persisted in plain text.
- Credential-derived fields in API responses are limited to a single `has_credentials: true/false` flag. The encrypted blob is never returned.
- The Agent Runtime receives a decrypted key at call time through the Control Center data-client. The runtime never holds raw API keys at rest, consistent with the top-priority architecture rule that agents cannot hold sensitive credentials.

## Fetch Models

Each provider configuration has a "Fetch Models" capability that returns the available model identifiers for that vendor:

- **Live listing** (OpenAI-compatible family): the endpoint queries the vendor's `/models` API and returns the current model catalogue.
- **Curated static list** (Gemini, Cohere): the endpoint returns a curated list of well-known flagship models maintained alongside the dispatcher code. The list is reviewed at release time.
- **Failure degradation**: if the vendor's listing endpoint is unreachable or the API key is invalid, the endpoint returns an empty list and logs the error. The administrator is never blocked from saving the configuration because the model list is unavailable.

## Runtime Resolution

1. An Agent Type carries a `model_id` string (e.g. `"gemini-2.5-pro"`).
2. The Model Binding Layer scans all `ModelConfig` records to find the one whose `enabled_models` list contains that `model_id`.
3. The matched configuration's endpoint and decrypted credential are returned to the Agent Runtime.
4. The runtime dispatches the call to the correct vendor through the provider-registry facade, which routes by dispatch family (OpenAI-compatible or native-API).

This late-binding architecture means swapping a provider or rotating a credential requires updating only the `ModelConfig` record — no agent type changes are needed.
