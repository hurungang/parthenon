# Tech Spec: Sandboxed Scripting Follow-ups

**Related:** [prd.md](prd.md) · [spec-change.md](spec-change.md) · [architecture.md](architecture.md) · [data-model.md](data-model.md) · [implementation-plan.md](implementation-plan.md)
**Builds on:** [archived sandboxed-scripting tech spec](../archive/2026-10-25-sandboxed-scripting-and-llm-mocking/tech-spec.md) — no code snippets here; see predecessor for detail.

## Component Breakdown

| Component | Location | Change |
|---|---|---|
| **Sandbox Engine** | `backend/app/agent_runtime/scripts/sandbox.py` | Rework globals construction: seed from RestrictedPython `safe_globals`/`safe_builtins` wholesale; layered guards (MCP-only tools facade, context binding, resource caps) kept, documented in the capability contract, and tested |
| **Script Runner / Dispatcher** | `backend/app/agent_runtime/scripts/runner.py`, `dispatch.py`, `fallback.py` | Detect semantic tool errors inside successful envelopes; record partial-failure outcome; classify it for fallback/repair/re-optimization reactions |
| **OAuth Refresh** | `backend/app/services/mcp/oauth_refresh.py`, `backend/app/services/mcp_oauth_service.py` | Failure classification: unrecoverable (provider says refresh token gone) → set `requires_reauth` + `last_refresh_error`; transient → retry as today. On successful re-auth, clear both fields on the SAME session (in-place fix already exists) |
| **McpSession model** | `backend/app/db/models/mcp_hub.py` | Add `requires_reauth` (bool) + `last_refresh_error` (text); Alembic migration |
| **Optimized Plan Service** | `backend/app/services/agents/optimized_plan_service.py` | Ensure `needs_feedback` failures persist the reason into the plan's existing `error` column; enforce self-reflection ordering in the mission (`command_prompts.py`) |
| **Optimization System Tools** | `backend/app/api/v1/internal/optimization_tools.py` | `generate_optimized_plan` already accepts `error` — verify the agent-facing contract encourages it on failure; no signature change expected |
| **Optimized Plan Tab** | `frontend/src/components/agents/AgentOptimizedPlanTab.tsx` | Render persisted `error` on `needs_feedback`; "nothing to retire" empty state; retire cache-refresh regression coverage; all strings via `t()` |
| **MCP session UX** | MCP Hub frontend surfaces (session management UI + notifications) | User-facing `requires_reauth` state, re-auth prompt, post-re-auth in-place refresh |
| **Master UX prototype** | `docs/master/ux/prototype/` | NEW — derived from shipped Optimized Plan / Scripts UI |
| **Test health** | `frontend/src/__tests__/AppShell*`, `backend/tests/` (tenant-isolation sweep, `test_full_execution_flow`) | Fix or quarantine with documented reasons |

## API Changes

| API | Change |
|---|---|
| MCP session REST reads | Expose `requires_reauth` and `last_refresh_error`; re-auth completion endpoint unchanged (operates on the same session in place) |
| Optimized plan REST (`GET .../optimized-plan`) | No contract change — `error` field already served; consumers (tab) must render it |
| Retire endpoint | Unchanged; the "nothing to retire" case is frontend UX (empty/retired state) |
| Execution/audit reads | Outcome values gain partial-failure semantics (extend outcome enum if the wire schema enumerates values) |
| Internal tool endpoints | No protocol change |

## Data Access Patterns

- **Ownership invariant unchanged:** only Control Center accesses PostgreSQL. AR consumes scripts and reports execution outcomes via mTLS CC REST with signed internal headers (`internal_httpx_client`).
- **McpSession:** two new columns; written by CC refresh classification; read by session management UI; no new query patterns (existing per-server session lists suffice).
- **OptimizedImplementationPlan:** `error` becomes reliably populated on `needs_feedback`; no new indexes or tables.
- **Execution records:** partial-failure outcome appended as today (records are append-only).
- **Alembic:** one migration (McpSession columns); reversible; `postgresql.ENUM(create_type=False)` conventions if an outcome enum is extended.

## Code Reference Map

| Area | File | Change type | Notes |
|---|---|---|---|
| AR sandbox | `backend/app/agent_runtime/scripts/sandbox.py` | MODIFY | Baseline seeding + documented guards; `_unpack_sequence_` → `guarded_unpack_sequence`, `_inplacevar_` → operator map |
| AR runner/dispatch/fallback | `backend/app/agent_runtime/scripts/runner.py`, `dispatch.py`, `fallback.py` | MODIFY | Semantic-error detection, partial-failure outcome, reactions (enum added; detection/wiring deferred) |
| AR tests | `backend/tests/test_sandbox_engine.py`, `test_script_runner.py`, `test_script_first_dispatcher.py` | MODIFY | Baseline regressions (`_unpack_sequence_`, `_inplacevar_`), outcome semantics |
| OAuth refresh | `backend/app/services/mcp/oauth_refresh.py` | MODIFY | Failure classification: unrecoverable → `requires_reauth`/`last_refresh_error`; success clears flags |
| OAuth service | `backend/app/services/mcp_oauth_service.py` | MODIFY | Flag set/clear wiring, re-auth same-session update |
| DB model | `backend/app/db/models/mcp_hub.py` | MODIFY | `McpSession.requires_reauth`, `.last_refresh_error` |
| DB model | `backend/app/db/models/script_execution.py` | MODIFY | `ScriptExecutionOutcome.partial_failure` added |
| Migration | `backend/alembic/versions/903e79b3fac9_add_requires_reauth_to_mcp_sessions.py` | NEW | Two columns, reversible |
| Migration | `backend/alembic/versions/e4f66f7c7f1c_add_partial_failure_to_script_execution_.py` | NEW | `partial_failure` enum value |
| MCP session schema | `backend/app/schemas/mcp_hub.py` | MODIFY | Expose `requires_reauth` + `last_refresh_error` in `McpSessionRead` |
| CH middleware | `backend/app/communication_hub/middleware/control_plane.py` | MODIFY | Removed cert-exempt bypass for `/internal/agent/execute|terminate|resume`; enforce `service:control-center` |
| Optimize service | `backend/app/services/agents/optimized_plan_service.py` | MODIFY | Persist failure reason on `needs_feedback` |
| Command prompts | `backend/app/services/agents/command_prompts.py` | MODIFY | Mandatory self-reflection order; mandate `error` on failed `generate_optimized_plan` |
| Optimization tools | `backend/app/api/v1/internal/optimization_tools.py` | VERIFY | `error` parameter honored and persisted |
| Frontend tab | `frontend/src/components/agents/AgentOptimizedPlanTab.tsx` | MODIFY | Error rendering, retire empty state |
| Frontend MCP UX | `frontend/src/pages/mcp/McpSessionManager.tsx` | MODIFY | `requires_reauth` token status + re-auth button; `needsReauth` i18n |
| Frontend types | `frontend/src/types/index.ts` | MODIFY | `McpSession.requires_reauth` / `last_refresh_error` |
| Frontend tests | `frontend/src/__tests__/AgentOptimizedPlanTab.test.tsx`, `AppShell.tenantAdmin.test.tsx` | MODIFY | New UX coverage; flake fix |
| Tenant-isolation sweep | `backend/tests/test_tenant_isolation_sweep.py` | MODIFY | `_OWN_KWARGS`/`_parent_fks` for script models; `command_prompts` registry entry |
| CH middleware test | `backend/tests/unit/test_control_plane_middleware.py` | MODIFY | Execute path now requires `service:control-center` |
| OAuth classification test | `backend/tests/services/test_oauth_refresh_classification.py` | NEW | Unrecoverable/transient/success flag lifecycle |
| E2E | `backend/tests/integration/test_full_execution_flow.py` | MODIFY | Fix middleware failures |
| Master UX | `docs/master/ux/prototype/` | NEW | Prototype from shipped UI |
| Master docs | `docs/master/` per architecture.md §5 | MODIFY | Post-implementation update |

## Compliance Note

Complies with `docs/config.yaml` top-priority rules: no boundary changes — sandbox stays AR-only, CC remains the sole database gateway, scripts/agents never receive credentials (re-auth is user-performed; only refresh results flow through CC with encrypted credential storage).
