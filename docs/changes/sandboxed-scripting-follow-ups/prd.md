# PRD: Sandboxed Scripting Follow-ups (Hardening & Defect Closure)

**Builds on:** [sandboxed-scripting-and-llm-mocking](../archive/2026-10-25-sandboxed-scripting-and-llm-mocking/prd.md) (archived)

## Epic Overview

The sandboxed scripting epic shipped, but live debugging surfaced eight deferred defects and gaps. Every one of them breaks a promise the original PRD made: scripts fail on valid Python constructs because the sandbox globals were built incrementally instead of from a vetted baseline; semantic tool failures are masked as successes so fallback and re-optimization never react; OAuth refresh failures strand agents silently; optimization failures are invisible to users; self-reflection is not enforced; retire is a silent no-op in one state; the master documentation lacks a UX prototype; and known broken tests erode trust in CI. This change closes all eight in one hardening pass.

## Business Goals

- Eliminate a class of script-authoring failures: valid business logic must not fail on language constructs (`_unpack_sequence_`, `_inplacevar_`), raising first-run script success rate.
- Make failure honest: semantic tool errors and optimization failures must be visible so fallback, repair, and re-optimization can react — reducing silent wrong results.
- Reduce operator toil: unrecoverable OAuth refresh failures must surface a clear re-auth path instead of silent agent breakage.
- Restore CI trust: all known broken/flaky tests fixed or explicitly quarantined with documented reasons.

## Users & Personas

- **Agent Operator** — needs true execution outcomes (partial failure reflected), visible optimization failure reasons, and clear re-auth prompts when MCP credentials expire.
- **Platform Administrator** — needs a single auditable sandbox baseline (with documented custom guards) and trustworthy CI.
- **Enterprise Consumer** — benefits silently: fewer spurious failures, faster recovery after credential expiry.

## User Stories

- As a platform administrator, I want the sandbox globals seeded from RestrictedPython's own audited safe baseline (with any custom guards documented and tested) so that valid scripts stop failing on standard language constructs.
- As an agent operator, I want a script run whose tool call fails semantically to be recorded as a partial failure so that fallback and re-optimization can react.
- As an agent operator, I want an unrecoverable MCP token-refresh failure to mark the session as needing re-auth and prompt me, so that I can restore the agent without diagnosing logs.
- As an agent operator, I want the failure reason of a `needs_feedback` optimization shown in the Optimized Plan tab so that I know what to fix or how to steer feedback.
- As an agent operator, I want the optimization run to always read its current scripts, execution logs, and prior optimized plan before authoring (and skip when healthy and unchanged) so that optimization never redoes good work or works from stale state.
- As an agent operator, I want a clear "nothing to retire" indication when no active optimized plan exists so that retire is never a silent no-op.
- As a platform administrator, I want a master UX prototype derived from the shipped Optimized Plan / Scripts UI so that documentation reflects reality.
- As a developer, I want the known broken and flaky tests fixed or explicitly quarantined with reasons so that CI signal is trustworthy.

## Acceptance Criteria

### Sandbox Baseline Rework

- Sandbox globals are seeded wholesale from RestrictedPython's `safe_globals`/`safe_builtins` baseline; scripts using tuple unpacking and augmented assignment (`_unpack_sequence_`, `_inplacevar_`) execute without errors.
- Any guard layered on top of the baseline is documented in the capability contract and covered by a test.
- Existing sandbox security invariants still hold: escapes fail closed; resource caps enforced (regression-covered).

### Real Tool-Error Propagation

- When a script's tool call returns a semantic error (e.g. an upstream error report in a successful envelope), the execution record reflects partial failure — not `outcome=success`.
- Fallback/repair/re-optimization flows react to the partial-failure outcome (regression tests demonstrate each reaction path).

### Unrecoverable OAuth Refresh Handling

- When an MCP token refresh fails unrecoverably (e.g. "No such refresh token found"), the MCP session is marked `requires_reauth` with the failure reason stored.
- A user-facing notification/prompt identifies the affected session and offers the re-auth path; completing re-auth updates the same session in place and clears the flag.
- Other sessions and servers are unaffected; ordinary transient refresh failures do NOT set the flag.

### Optimization Failure Visibility

- When optimize-and-verify ends in `needs_feedback`, the failure reason is persisted on the plan's `error` field and rendered in the Optimized Plan tab.
- The authoring prompt mandates the agent populate `error` when calling `generate_optimized_plan` for a failed outcome; the UI shows the reason with i18n-wrapped text.

### Self-Reflection Completeness

- The optimization mission requires reading `get_scripts`, `get_execution_log`, and `get_optimized_implementation_plan` before authoring any script.
- When scripts and logs are healthy and the agent is unchanged, the run skips re-authoring and states so.

### Retire UX

- Retire refreshes the launch-dialog state (already shipped — regression-covered).
- When no active plan exists, retire shows a clear "nothing to retire" state instead of a silent no-op.

### Master UX Prototype

- `docs/master/ux/prototype/` contains a prototype derived from the shipped Optimized Plan / Scripts UI.

### Pre-existing Test Health

- The AppShell tenantAdmin vitest flake, the ~9 tenant-isolation sweep `KeyError: _OWN_KWARGS` failures for script models, and the `test_full_execution_flow` middleware failures are each fixed, or quarantined with a documented reason and tracking note.

## Out of Scope

- New sandbox features or capability changes beyond the baseline rework.
- Changes to the script lifecycle, dispatch preference logic, or fallback policy (only outcome semantics change).
- OAuth re-auth flows for non-MCP credentials (agent identity tokens unchanged).
- Redesign of the Optimized Plan UI beyond error rendering and retire states.
- Any new feature work — this change is defect closure only.

## Dependencies & Constraints

- Depends on the archived sandboxed-scripting change being fully shipped (it is).
- Complies with `docs/config.yaml` top-priority rules: services segregated; sandbox runs only in Agent Runtime; only Control Center touches the database; scripts never see credentials.
- The in-place re-auth fix already exists — this change adds only detection and UX around it.
- `generate_optimized_plan` already accepts `error` — only agent-prompt usage and UI rendering remain.
