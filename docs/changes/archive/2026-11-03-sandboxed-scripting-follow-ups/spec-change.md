# Spec Delta: Sandboxed Scripting Follow-ups

**Baseline:** [archived sandboxed-scripting spec](../archive/2026-10-25-sandboxed-scripting-and-llm-mocking/tech-spec.md)

## CHANGED

| Area | What changes |
|---|---|
| **Sandbox baseline** | Globals are no longer built construct-by-construct with incremental guard hooks. The baseline is RestrictedPython's `safe_globals`/`safe_builtins` seeded wholesale; only documented, tested custom guards (MCP-only `tools` facade, `context` binding, resource caps) are layered on top. Guarantees unchanged: no I/O, no network, no imports, fail-closed escapes. |
| **Execution outcome semantics** | A script execution whose tool call fails semantically (error payload inside a successful envelope, upstream error report) no longer records `outcome=success`. A `partial_failure` outcome is recorded so fallback, repair, and re-optimization react. Transport-level tool failures (tool not found, HTTP errors) already raise typed errors — unchanged. |
| **needs_feedback visibility** | `generate_optimized_plan` failures must persist the reason in the plan's `error` field. The authoring prompt mandates this; the Optimized Plan tab renders the stored reason (previously often empty). |
| **Retire UX** | Retire already refreshes launch-dialog state (kept). NEW: when no active plan exists, retire shows an explicit "nothing to retire" state instead of a silent no-op. |
| **Self-reflection** | The optimization mission elevates reading `get_scripts` / `get_execution_log` / `get_optimized_implementation_plan` from a suggestion to a MANDATORY pre-authoring step, with explicit skip-when-healthy-and-unchanged behaviour. |

## NEW

| Area | What is added |
|---|---|
| **MCP session `requires_reauth` state** | McpSession gains `requires_reauth` (boolean) and `last_refresh_error` (text). Unrecoverable refresh failures (e.g. `404 No such refresh token found`) set the flag; a user-facing notification names the affected session and offers re-auth; completing the existing in-place re-auth clears the flag and error. Transient refresh failures do not set the flag. |
| **Master UX prototype** | `docs/master/ux/prototype/` — a prototype derived from the shipped Optimized Plan / Scripts UI (deferred from the master update). |
| **Test health remediation** | Fix or explicitly quarantine: AppShell tenantAdmin vitest flake; ~9 tenant-isolation sweep `KeyError: _OWN_KWARGS` failures for script models; `test_full_execution_flow` middleware failures. Quarantines require a documented reason. |

## UNCHANGED

Everything else from the predecessor change, including: script registry lifecycle (draft → verified → compiled → retired); two-layer plan model and Script-First Dispatcher preference/fallback policy; LLM mocking framework (scripted/record/replay); sandbox resource caps and their env configuration; tool-name validation at authoring and runtime; token-savings accounting; retire marking rows `retired` (kept for reference); the invocation contract (`script____<name>`, `server____tool`); CC-only database ownership and AR-only sandbox execution; OptimizedImplementationPlan schema (the `error` column already exists — only its population becomes mandatory on failure).
