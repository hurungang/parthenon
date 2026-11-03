# Test Plan: Sandboxed Scripting Follow-ups

**Related:** [prd.md](prd.md) · [implementation-plan.md](implementation-plan.md)

## Test Strategy

Three layers per project standard: backend pytest (unit + integration), frontend Vitest (component UX), E2E Playwright (user flows). The sandbox changes run only in Agent Runtime — segregation is asserted by existing structural tests, which must stay green. OAuth re-auth is tested with a simulated unrecoverable provider failure; no live identity-provider calls. The LLM mock layer exercises optimization flows deterministically.

## Coverage Areas

1. **Sandbox baseline** — baseline seeding covers previously failing constructs; layered guards documented and tested; security invariants regress-green.
2. **Outcome semantics** — semantic tool errors produce partial failure; transport errors unchanged; reaction paths (fallback/repair/re-optimization) each demonstrated.
3. **OAuth re-auth** — flag set/clear lifecycle, same-session update, transient-failure immunity, user notification, UI state.
4. **Optimization visibility** — `error` persisted on `needs_feedback`; rendered in tab; self-reflection ordering and skip-when-healthy.
5. **Retire UX** — cache-refresh regression; "nothing to retire" empty state.
6. **Test health** — AppShell flake, tenant-isolation `_OWN_KWARGS` sweep, `test_full_execution_flow` middleware failures fixed or documented quarantines.

## Critical Scenarios (WHEN/THEN)

- **WHEN** a script uses tuple unpacking or augmented assignment, **THEN** it executes successfully under the baseline-seeded globals.
- **WHEN** a script attempts a disallowed import or attribute escape, **THEN** it fails closed with a typed recorded error (unchanged behaviour).
- **WHEN** a script's tool call returns an upstream error report inside a successful envelope, **THEN** the execution record shows partial failure, not `outcome=success`.
- **WHEN** a partial failure is recorded, **THEN** the fallback path runs (or re-optimization is eligible) as configured.
- **WHEN** an MCP token refresh fails with an unrecoverable provider error, **THEN** the session is flagged `requires_reauth` with the stored reason and the user is notified.
- **WHEN** the user completes re-auth, **THEN** the SAME session is updated in place, the flag and error are cleared, and tool calls resume.
- **WHEN** a refresh fails transiently, **THEN** the flag is NOT set and normal retry occurs.
- **WHEN** optimize-and-verify ends in `needs_feedback`, **THEN** the failure reason is persisted and visible in the Optimized Plan tab.
- **WHEN** the optimization run starts with healthy unchanged scripts, **THEN** it reads scripts/logs/prior plan first and skips re-authoring, stating so.
- **WHEN** retire is invoked with no active plan, **THEN** a clear "nothing to retire" state is shown (no silent no-op).
- **WHEN** retire succeeds, **THEN** the launch dialog immediately re-evaluates (regression for the shipped cache-refresh fix).

## Edge Cases

- Tool result is an error-shaped payload but the script handles it deliberately — outcome rules must distinguish handled vs unhandled semantic errors (define and test the boundary).
- Multiple MCP sessions on one server: only the affected session is flagged; others keep working.
- Re-auth on a session whose server was deleted mid-flow → graceful error, no crash.
- `error` field with very long/empty/unicode failure text renders safely.
- Concurrent retire and launch → launch dialog state remains consistent.
- Baseline seeding must not accidentally widen access vs. the previous incremental guards (allowlist-diff test).
- Quarantined tests: each carries a documented reason; CI counts them explicitly.

## Acceptance Criteria Checklist

- [ ] `_unpack_sequence_` / `_inplacevar_` scripts pass; all sandbox security-invariant tests green
- [ ] Every custom guard layered on the baseline has documentation + a test
- [ ] Semantic tool failure → partial-failure outcome recorded; success no longer claimed
- [ ] Fallback/repair/re-optimization react to partial failure (tested per path)
- [ ] Unrecoverable refresh → `requires_reauth` + `last_refresh_error` set; user notified; re-auth clears both on the same session; transient failures don't flag
- [ ] `needs_feedback` failure reason persisted and rendered in the Optimized Plan tab
- [ ] Self-reflection order (scripts → logs → prior plan) enforced; skip-when-healthy works
- [ ] Retire empty state shown when no active plan; retire cache-refresh regression test present
- [ ] `docs/master/ux/prototype/` exists and is referenced from master docs
- [ ] AppShell flake, `_OWN_KWARGS` sweep failures, and `test_full_execution_flow` middleware failures fixed or quarantined with reasons
- [ ] All three test layers pass: backend pytest, frontend Vitest, E2E Playwright

## Test File References

| Layer | File | Covers |
|---|---|---|
| Backend | `backend/tests/test_sandbox_engine.py` | Baseline seeding, construct regressions, invariants, guards |
| Backend | `backend/tests/test_sandbox_unpack.py` | `_unpack_sequence_` / `_inplacevar_` construct execution |
| Backend | `backend/tests/test_script_runner.py`, `test_script_first_dispatcher.py` | Semantic-error detection, partial-failure outcome, reactions |
| Backend | `backend/tests/services/test_oauth_refresh_classification.py` | Refresh classification (unrecoverable/transient/success flag lifecycle) |
| Backend | `backend/tests/services/test_mcp_oauth_reauth_tenant.py` | Same-session re-auth, flag clearing |
| Backend | `backend/tests/test_optimized_plan.py` | `error` persistence on `needs_feedback`, self-reflection ordering, retire endpoint |
| Backend | `backend/tests/test_tenant_isolation_sweep.py` | `_OWN_KWARGS` sweep fix (script models), registry completeness |
| Backend | `backend/tests/unit/test_control_plane_middleware.py` | CH control-plane cert enforcement (execute path) |
| Backend | `backend/tests/integration/test_full_execution_flow.py` | Full CC→CH→AR flow middleware invariants |
| Frontend | `frontend/src/__tests__/AgentOptimizedPlanTab.test.tsx` | Error rendering, retire empty state, retire refresh regression |
| Frontend | `frontend/src/__tests__/AppShell.tenantAdmin.test.tsx` | Sidebar tenant-admin gating (flake fixed) |
| Frontend | `frontend/src/__tests__/McpSessionManager.test.tsx` | Re-auth UX states (requires_reauth token status) |
| E2E | `e2e/tests/mcp-hub.spec.ts` ("MCP Session re-auth state") | `requires_reauth` token status + re-auth prompt flow |
