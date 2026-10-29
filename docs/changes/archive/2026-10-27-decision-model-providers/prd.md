# PRD: Decision Model Providers

## Epic Overview

Parthenon currently limits administrators to a single configured decision-skill provider ("System One Provider"), which every decision tool must use. This creates vendor lock-in, prevents cost/quality comparison across decision vendors, and forces a one-size-fits-all choice. This epic rebrands and generalises the capability into **Decision Model Providers**: administrators can register multiple decision-skill vendors, each with multiple individually enable/disable-able models (mirroring the existing Model Configurations experience for LLMs). When authoring or configuring a decision tool, users select which enabled decision model that tool should use. Critically, all existing guardrail and budget/spend controls that govern regular agent model usage must also apply to decision model usage, so enterprise governance stays airtight.

## Business Goals

- Eliminate single-vendor lock-in for decision-skill evaluations by supporting multiple vendors per deployment.
- Give administrators the same management experience (encrypted credentials, per-model enablement) for decision providers as they already have for LLM providers.
- Allow per-decision-tool model selection so teams can match vendors/models to specific use cases (accuracy, latency, cost).
- Extend existing guardrail and budget/spend enforcement to 100% of decision model calls — no ungoverned spend.
- Provide consistent, unambiguous terminology ("Decision Model Providers") across the UI, docs, and settings pages.

## Users & Personas

- **Platform Administrator** — configures decision vendors, credentials, and which models are enabled; needs encrypted credential storage and a familiar CRUD experience.
- **Agent/SOP Author** — creates and configures decision tools; needs to pick the right enabled decision model per tool without needing to manage credentials.
- **Compliance / Finance Owner** — needs assurance that guardrails and budget/spend limits apply equally to decision model usage as to regular agent usage.
- **Operations / Support** — needs to diagnose which provider/model a decision tool used and see connection health.

## User Stories

- As a platform administrator, I want to register multiple Decision Model Providers (vendors) with their credentials, so that my organisation is not tied to a single decision vendor.
- As a platform administrator, I want each vendor to offer a list of models that I can individually enable or disable, so that I control exactly which models are usable in my deployment.
- As a platform administrator, I want to test a provider connection before saving and at any time afterwards, so that misconfigurations are caught early.
- As a platform administrator, I want decision provider credentials stored securely and never displayed back to me, so that secrets are not exposed.
- As an agent/SOP author, I want to choose which enabled decision model a decision tool uses, so that each tool gets the vendor/model best suited to it.
- As a compliance/finance owner, I want guardrails and budget/spend limits applied to every decision model call, so that decision evaluations cannot bypass cost controls or safety rules.
- As an operations user, I want to see which decision model was used for a given decision evaluation, so that I can troubleshoot and audit outcomes.

## Acceptance Criteria

### Provider Management (CRUD Lifecycle)

- ✅ Administrator can create a new Decision Model Provider by selecting a vendor type, providing a display name, endpoint (where applicable), and credentials (API key / secret) in a create dialog.
- ✅ Created provider immediately appears in the providers table with all fields (vendor chip, credentials-set indicator) correctly displayed, without a page reload.
- ✅ Administrator can edit an existing provider; the edit dialog is pre-populated with current values, and after saving the parent table refreshes automatically to show updated data.
- ✅ Leaving the credential field at its placeholder on edit does not overwrite the stored credential; entering a new value replaces it; explicitly clearing removes it.
- ✅ Administrator can delete a provider with a confirmation dialog; after deletion the provider is removed from the table immediately.
- ✅ A provider still referenced by decision tools cannot be deleted — deletion is blocked with a clear error naming the blocking references.
- ✅ After deletion, the administrator can create a new provider with the same display name and vendor (proves true deletion).
- ✅ Duplicate display names (per vendor) or duplicate vendor registrations where uniqueness is required are rejected with a clear, user-friendly error message.
- ✅ Required fields are enforced with visible validation; API/permission failures inside create/edit/delete dialogs are surfaced as visible errors in the dialog (no silent failures).

### Model Management

- ✅ Administrator can view the model catalogue for a vendor and enable/disable individual models via a toggle; changes take effect immediately for decision tool authoring.
- ✅ A vendor-level enable/disable control cascades to all models under that vendor.
- ✅ Disabled models do not appear as selectable options when authoring or re-configuring decision tools.
- ✅ Existing decision tools that reference a model that later becomes disabled are prevented from evaluating with it and surface a clear, actionable error.

### Per-Decision-Tool Model Selection

- ✅ When authoring or configuring a decision tool, the user sees a selector listing only enabled decision models (across all providers).
- ✅ The selected model is displayed on the decision tool's detail/list view.
- ✅ A decision tool evaluates against its selected model; execution records/logs identify the provider and model used.
- ✅ Changing a tool's selected model takes effect on its next evaluation without any restart or re-deploy.

### Guardrails & Budget

- ✅ Every decision model evaluation passes through the same guardrail checks applied to regular agent model usage (content/safety guardrails as configured).
- ✅ Decision model usage is metered and counted against the same budget/spend limits as regular agent model usage.
- ✅ When a guardrail is triggered or a budget is exhausted, the decision evaluation is blocked with the same user-visible outcomes and audit trail as regular model usage.
- ✅ Decision model usage appears in the same usage/spend reporting views as regular agent model usage.

### Migration & Terminology

- ✅ The existing "System One Providers" settings page is renamed to "Decision Model Providers" everywhere it appears (navigation, page titles, dialogs, help text, notifications).
- ✅ Existing single-provider configuration is preserved and appears after upgrade as a fully editable Decision Model Provider — no data loss, no re-entry of credentials.
- ✅ Existing decision tools continue to work after upgrade, resolving to the migrated provider/model.

## Out of Scope

- Adding new decision vendor integrations beyond what is already supported (new vendors remain an engineering-led release activity).
- Automatic model recommendation, routing, or fail-over between decision providers based on cost/quality.
- Changes to the regular LLM Model Configurations feature itself.
- Per-tenant custom vendor registration or runtime/plugin-based vendor onboarding.
- Restructuring guardrail or budget configuration itself — only extending their coverage to decision models.
- Bulk import/export of provider configurations.

## Dependencies & Constraints

- Depends on the existing Model Configurations management pattern (encrypted credentials, enabled-model lists) as the UX and governance baseline to mirror.
- Depends on the existing guardrail and budget/spend enforcement pipeline being reusable for decision evaluations.
- Requires a data migration from the current single System One provider configuration to the new multi-provider model, which must be backward compatible and idempotent.
- Credentials must remain encrypted at rest and never returned in read responses, consistent with platform-wide credential handling.
- Terminology rename must be propagated consistently to UI text (i18n resources), documentation, and exported reports; internal identifiers may remain unchanged to limit migration risk.
- Permission model for the settings page must carry over (only administrators with the appropriate permissions can manage providers).
