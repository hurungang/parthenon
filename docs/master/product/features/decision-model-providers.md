# Decision Model Providers

## Overview
Decision Model Providers is the central catalogue for decision-skill vendors and their models. Previously, a deployment could configure exactly one decision-skill provider (under "System One Providers" terminology) and every decision tool silently used it. Decision Model Providers replaces this with a multi-vendor catalogue: administrators register any number of decision vendors, manage their credentials securely, enable or disable individual models, and each decision tool explicitly selects which enabled model it evaluates against. All guardrail and budget/spend controls that govern regular agent model usage also apply to decision model usage, so enterprise governance stays airtight. The catalogue mirrors the same management experience as [Model Configurations](model-configurations.md).

## Who Uses It
- Platform Administrators: register decision vendors, manage credentials, enable/disable models, test connections
- Agent/SOP Authors: select which enabled decision model a decision tool uses when authoring or configuring it
- Compliance / Finance Owners: rely on guardrails and budget/spend limits applying equally to decision model usage
- Operations / Support: see which provider and model were used for a decision evaluation and check connection health

## What It Does
- Provides a multi-vendor catalogue of Decision Model Providers, each with a display name, endpoint configuration (where applicable), and securely stored credentials
- Supports the full provider lifecycle: create, edit, delete, and connection testing (before saving and at any time afterwards)
- Credentials are stored securely, never displayed back after entry, and can be replaced or explicitly cleared on edit
- Each provider exposes a model catalogue; administrators individually enable or disable models, and a vendor-level enable/disable cascades to all its models
- Decision tools explicitly select an enabled decision model at authoring/configuration time; the selection is visible on the tool's detail and list views
- Changing a tool's selected model takes effect on its next evaluation, with no restart or re-deploy
- Decision model evaluations pass through the same guardrail checks as regular agent model usage; guardrails for decision models are managed in this module, reusing the platform guardrail system
- Decision model usage is metered against the same budget/spend limits as regular agent model usage; breaches and budget exhaustion block evaluations with the same observable outcomes and audit trail
- Execution and audit records identify the provider and model used for each decision evaluation

## Key Concepts
- **Decision Model Provider**: A registered decision-skill vendor with its own configuration and credentials
- **Model Enablement**: Per-model on/off control within a provider; only enabled models are selectable when authoring decision tools
- **Per-Tool Model Selection**: Each decision tool resolves the explicitly selected enabled model — there is no implicit fallback to a single configured provider
- **Connection Testing**: A health check administrators can run before saving a provider and at any time afterwards
- **Referential Integrity**: A provider still referenced by decision tools cannot be deleted; deletion is blocked with a clear error naming the blocking references

## Acceptance Criteria

### Provider Management
- Administrators can create, edit, and delete Decision Model Providers, with required-field validation and clear, visible errors for duplicates or API/permission failures (no silent failures)
- Created or edited providers appear in the providers table immediately, without a manual page reload
- Leaving the credential field at its placeholder on edit does not overwrite the stored credential; entering a new value replaces it; explicitly clearing removes it
- Deleting a provider requires confirmation; the provider is removed from the table immediately, and a new provider can be created with the same name afterwards (proving true deletion)
- A provider still referenced by decision tools cannot be deleted — a clear error names the blocking references
- Duplicate provider names (per vendor) are rejected with a clear, user-friendly message
- Connection tests can be run before saving and at any time afterwards, with results shown to the administrator

### Model Enablement
- Administrators can view a provider's model catalogue and toggle individual models on or off; changes take effect immediately for decision tool authoring
- A vendor-level enable/disable cascades to all models under that vendor
- Disabled models do not appear as selectable options when authoring or re-configuring decision tools
- Decision tools referencing a model that later becomes disabled are prevented from evaluating with it and surface a clear, actionable error

### Per-Tool Model Selection
- When authoring or configuring a decision tool, the selector lists only enabled decision models across all providers
- The selected model is displayed on the decision tool's detail and list views
- Execution records identify the provider and model used for each evaluation

### Guardrails & Budget
- Every decision model evaluation passes through the same guardrail checks as regular agent model usage; guardrails for decision models are managed in the Decision Model Providers module, reusing the platform guardrail system
- Decision model usage is metered against the same budget/spend limits as regular agent model usage
- Guardrail breaches and budget exhaustion block decision evaluations with the same user-visible outcomes and audit trail as regular model usage

### Migration & Terminology
- The capability is named "Decision Model Providers" everywhere user-facing; "System One Providers" terminology is retired
- Existing single-provider configuration is preserved and appears after upgrade as a fully editable Decision Model Provider — no data loss, no re-entry of credentials
- Existing decision tools continue to work after upgrade, resolving to the migrated provider/model

## Known Limitations
- Decision usage is metered on execution results, but is not yet rolled into Model Usage Posture spend reporting. Decision model evaluations are governed by guardrails and budgets at execution time; integrated spend reporting coverage is planned for a future change.

## Out of Scope
- Adding new decision vendor integrations (new vendors remain an engineering-led release activity)
- Automatic model recommendation, routing, or fail-over between decision providers based on cost/quality
- Changes to the regular LLM [Model Configurations](model-configurations.md) feature itself
- Per-tenant custom vendor registration or runtime/plugin-based vendor onboarding
- Restructuring guardrail or budget configuration — only extending their coverage to decision models
- Bulk import/export of provider configurations

## Dependencies & Constraints
- Mirrors the Model Configurations management pattern (encrypted credentials, enabled-model lists) as its UX and governance baseline
- Relies on the shared platform guardrail and budget/spend enforcement pipeline
- Credentials are encrypted at rest and never returned in read responses, consistent with platform-wide credential handling
- Only administrators with the appropriate permissions can manage providers
