# Spec Delta: Decision Model Providers

## Affected Spec Areas

Master product specs (see `docs/master/product/features/`):

- `docs/master/product/features/skill-management.md` — decision skills / decision tools reference the provider model; naming and selection semantics change.
- `docs/master/product/features/model-configurations.md` — the governance pattern (encrypted credentials, enabled-model lists) this epic mirrors; guardrail/budget coverage scope widens.
- `docs/master/product/features/agent-execution.md` — decision evaluations now consume the same guardrail and budget/spend enforcement as regular agent model usage.
- `docs/master/product/features/dashboard-metrics.md` — usage/spend reporting must include decision model usage.

> Note: the current "System One Providers" capability has no dedicated master feature spec; this change introduces `decision-model-providers` as its successor specification.

## New Capabilities

1. **Multi-vendor Decision Model Providers catalogue**
   - Administrators register any number of decision-skill vendors, each with its own display name, endpoint configuration, and encrypted credentials.
   - Full CRUD lifecycle with vendor-level and per-model enable/disable, connection testing, and referential-integrity protection on delete (providers in use by decision tools cannot be deleted).
   - The catalogue follows the same management experience as LLM Model Configurations.

2. **Per-vendor model enablement**
   - Each provider exposes a list of models; administrators individually enable or disable each model.
   - A vendor-level disable cascades to all its models.
   - Only enabled models are selectable when authoring decision tools.

3. **Per-decision-tool model selection**
   - When authoring or configuring a decision tool, the user selects which enabled decision model the tool evaluates against.
   - Selection is visible on the decision tool's detail/list views; changes take effect on the next evaluation.
   - Execution/audit records identify the provider and model used for each decision evaluation.

4. **Guardrail & budget coverage for decision models**
   - Decision model evaluations pass through the same guardrail checks as regular agent model usage.
   - Decision model usage is metered against the same budget/spend limits and appears in the same usage/spend reporting.
   - Guardrail breaches and budget exhaustion block decision evaluations with the same observable outcomes and audit trail as regular model usage.

## Modified Capabilities

### System One Providers → Decision Model Providers

**Before:**
- A "System One Providers" settings page allows exactly one decision-skill provider (e.g., TypeSafe Jev) per deployment.
- All decision tools implicitly evaluate against that single configured provider/model; no per-tool choice exists.
- Naming throughout the UI, docs, and settings uses "System One" terminology.

**After:**
- The capability is named **Decision Model Providers** everywhere user-facing (navigation, page titles, dialogs, help text, notifications); internal identifiers may remain for compatibility.
- Multiple vendors can be registered; each carries multiple models that can be individually enabled/disabled.
- Each decision tool explicitly selects an enabled decision model at authoring/configuration time.
- Guardrails and budget/spend controls, previously scoped to regular agent model usage, now apply to decision model usage as well.
- Existing single-provider configuration is migrated forward as an editable Decision Model Provider with credentials preserved; existing decision tools continue to work unchanged.

## Removed Capabilities

- **Single-provider-only restriction**: the constraint that a deployment can have exactly one decision-skill provider is removed (replaced by the multi-provider catalogue).
- **"System One Providers" terminology**: user-facing naming is retired in favour of "Decision Model Providers".
- **Implicit provider binding for decision tools**: decision tools no longer silently fall back to the single configured provider; they resolve the explicitly selected model.

## Spec Update Instructions

- Create `docs/master/product/features/decision-model-providers.md` as the successor feature spec: multi-vendor catalogue, encrypted credential handling, per-model enablement, CRUD lifecycle (including delete-blocking when referenced and duplicate-name rejection), and connection testing.
- Update `docs/master/product/features/skill-management.md`: replace all "System One" terminology with "Decision Model Providers"; document per-decision-tool model selection (enabled models only) and the disabled-model error behaviour.
- Update `docs/master/product/features/model-configurations.md`: cross-reference Decision Model Providers as the sibling catalogue for decision vendors; note the shared management/governance pattern.
- Update `docs/master/product/features/agent-execution.md`: state that guardrail and budget/spend enforcement covers both regular agent model usage and decision model evaluations, including audit/observability of provider and model per evaluation.
- Update `docs/master/product/features/dashboard-metrics.md`: include decision model usage in usage/spend reporting and guardrail breach metrics.
- Update `docs/master/product/README.md` (feature index) to list the new feature spec and remove/redirect any System One references.
- Update `docs/master/data-model/` overview: reflect the transition from a single provider configuration to a provider catalogue with per-provider models and per-decision-tool model references.
- Sweep `docs/master/` (product, operations, reference, glossary) for "System One" terminology and replace with "Decision Model Providers"; retain internal identifier mentions only where technically required.
