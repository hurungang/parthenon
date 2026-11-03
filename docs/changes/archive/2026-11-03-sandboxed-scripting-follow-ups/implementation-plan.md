# Implementation Plan: Sandboxed Scripting Follow-ups

## Overview

Hardening change closing eight deferred defects from the sandboxed-scripting epic: sandbox baseline rework, honest tool-error outcome semantics, unrecoverable OAuth refresh detection + UX, optimization failure visibility, enforced self-reflection, retire empty-state UX, master UX prototype, and pre-existing test health. No new features; six phases, each independently verifiable.

## Task Checklist

### Phase 1 — Sandbox Baseline Rework

- [x] phase.1 Seed sandbox globals wholesale from RestrictedPython `safe_globals`/`safe_builtins` in `backend/app/agent_runtime/scripts/sandbox.py`
- [x] phase.1 Remove construct-by-construct globals patching; keep only documented custom guards (tools facade, context binding, caps)
- [x] phase.1 Document every layered guard in the capability contract
- [x] phase.1 Regression tests: tuple unpacking + augmented assignment scripts pass; all existing security-invariant tests stay green

**Done when:** `_unpack_sequence_` / `_inplacevar_` scripts execute; sandbox invariant suite passes unchanged.

### Phase 2 — Tool-Error Propagation + Outcome Semantics

- [ ] phase.2 Detect semantic tool errors (error report inside a successful envelope) in the sandbox/runner tool path — **DEFERRED** (product decision): no platform-level heuristic. Scripts already handle unexpected data shapes defensively (e.g. a non-array where a list is expected); that is the accepted resolution.
- [x] phase.2 Record a partial-failure outcome on the execution record (extend outcome enumeration if needed) — `partial_failure` added to `ScriptExecutionOutcome` enum + migration `e4f66f7c7f1c` (unused placeholder pending a future detection contract)
- [ ] phase.2 Wire fallback/repair/re-optimization reactions to the new outcome — **DEFERRED** with detection
- [ ] phase.2 Tests: semantic error → not `success`; each reaction path demonstrated — **DEFERRED** with detection

**Done when:** ~~a script whose tool call returns an upstream error report no longer records `outcome=success`.~~ Deferred — script-level defensive handling of unexpected tool-result shapes is the accepted mitigation.

### Phase 3 — OAuth requires_reauth + UX

- [x] phase.3 Add `requires_reauth` + `last_refresh_error` to McpSession (model + Alembic migration) in `backend/app/db/models/mcp_hub.py`
- [x] phase.3 Classify refresh failures in `backend/app/services/mcp/oauth_refresh.py` / `backend/app/services/mcp_oauth_service.py`: unrecoverable sets flag; transient does not
- [x] phase.3 Surface user-facing notification/prompt naming the session with a re-auth path; in-place re-auth clears flag + error on the SAME session
- [x] phase.3 i18n strings for all new UI text

**Done when:** a simulated "no such refresh token" failure flags the session, notifies the user, and completing re-auth restores the same session.

### Phase 4 — Optimization Failure Visibility + Retire UX

- [x] phase.4 Mandate `error` population in the `generate_optimized_plan` mission/prompt (`backend/app/services/agents/command_prompts.py`, `optimized_plan_service.py`)
- [x] phase.4 Render the persisted `error` in `frontend/src/components/agents/AgentOptimizedPlanTab.tsx` (via `t()`)
- [x] phase.4 Enforce mandatory self-reflection ordering (get_scripts → get_execution_log → get_optimized_implementation_plan before authoring) in the mission, with skip-when-healthy
- [x] phase.4 Add "nothing to retire" empty state for retire when no active plan exists

**Done when:** a `needs_feedback` plan shows its failure reason in the tab; retire without an active plan shows a clear message.

### Phase 5 — Master UX Prototype

- [x] phase.5 Create `docs/master/ux/prototype/` derived from the shipped Optimized Plan / Scripts UI
- [x] phase.5 Reference the prototype from master documentation

**Done when:** prototype exists and is linked from master docs.

### Phase 6 — Pre-existing Test Health

- [x] phase.6 Fix or quarantine AppShell tenantAdmin vitest flake (reason documented if quarantined)
- [x] phase.6 Fix ~9 tenant-isolation sweep `KeyError: _OWN_KWARGS` failures for script models
- [x] phase.6 Fix `test_full_execution_flow` middleware failures
- [x] phase.6 Full backend + frontend suites green (quarantines documented)

**Done when:** CI is green with no unexplained skips.

## Completion Checklist

- [ ] All acceptance criteria in prd.md verified
- [ ] All three test layers pass (backend pytest, frontend Vitest, E2E Playwright)
- [x] Alembic migration applied (`alembic upgrade head`) before testing
- [x] `docs/master/` updated per architecture.md §5
- [ ] `.change.yaml` updated; docs reviewed by es-Document Reviewer
