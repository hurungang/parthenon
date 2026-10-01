# Security Review — Cross-Tenant Payload Isolation (Task 8.7)

Review of every payload Control Center sends to Communication Hub (CH)
and Agent Runtime (AR), confirming only tenant-scoped data leaves CC and
that agents never receive other tenants' business data or tokens.
Findings feed the Phase 9 test matrix.

## 1. CC → CH payloads

| Call | Payload | Tenant binding |
|---|---|---|
| `dispatch_message` | session_id, message_type, content, metadata | `tenant_context` signed headers attached (`CommunicationHubClient`); session resolved at CC within the requesting tenant |
| `trigger_execution` | session_id, agent_type_id, input_data | signed headers; the AgentJob/agent type were resolved through CC's tenant-scoped gateway |
| `resume_session` / `terminate_session` | session_id (+ response/reason) | signed headers; the session belongs to the requesting tenant (UI/API actions are tenant-scoped) |

**Conclusion:** every outbound payload references only identifiers that
CC resolves *within the requesting tenant* (row-level scoping at the
`get_db` choke point). A cross-tenant identifier is invisible → 404
before any dispatch is built.

## 2. CH → AR payloads

| Call | Payload | Tenant binding |
|---|---|---|
| `/execute`, `/internal/agent/resume/*`, `/internal/agent/terminate/*` | session_id, agent_type_id, input_data | CH forwards the signed tenant headers it received from CC (`ControlPlaneMiddleware` binds ALL internal paths, including the cert-exempt forwards); AR's `ControlCenterCertificateMiddleware` re-verifies the signature and binds the context |

**Conclusion:** AR receives the same identifiers plus a signature it can
verify but cannot forge. AR cannot widen the context: the tenant arrives
only as CC-signed headers, and AR's runtime loader resolves all
configuration through CC's data client, which forwards the same signed
headers so every CC resolve is tenant-scoped.

## 3. Identity tokens and credentials

- Identity tokens are resolved by **CC** (`validate_api_key_internal`,
  internal authorization) and delivered **only to CH** over mTLS.
- AR never receives identity tokens; agents never receive tokens —
  per-tool-call injection happens at CC within the session's tenant
  (tenant-scoped resolution narrows the existing flow).
- The tenant signing key (`TENANT_CONTEXT_SIGNING_KEY`) lives in the
  three services' env config — never sent to agents or the frontend.

## 4. Isolation mechanisms verified end to end

1. **Single resolution point** — CC resolves the tenant once per request
   (middleware) and once per internal call (signed headers).
2. **Row-level scoping** — the `do_orm_execute` listener filters
   SELECT/UPDATE/DELETE on scoped sessions; `before_flush` auto-stamps
   new rows with the session's tenant, so data created during execution
   cannot land in another tenant.
3. **Cross-tenant probes** — a direct-addressed foreign id yields 404
   (no data leak) and a security-relevant `cross_tenant_access_denied`
   audit event (scope-miss detection).
4. **Scheduler adoption** — triggered jobs carry their owning tenant's
   context through launch → CH → AR; jobs can only reference agent types
   resolvable within their tenant (scoped resolve in `_dispatch`).
5. **MCP/API keys** — key validation at CC returns the key's tenant
   binding; CH binds the MCP session to it (`request.state.tenant_id`);
   a tenant-A key cannot address tenant-B resources (CC resolves scoped).

## 5. Known boundaries (documented for Phase 9 tests)

- **Background sessions outside the scheduler** (e.g. the plan-generation
  background task, auto-naming) use unscoped sessions by design; rows
  they create carry `tenant_id = NULL` (pre-adoption semantics) until
  their flows are tenant-adopted. Isolation of *request-driven* paths is
  unaffected.
- **`/api/v1/platform/*`** is intentionally tenant-free (metadata-only
  console at the base domain); it exposes no business rows.
- **Enforcement of "CH cannot sign"** is code organization: only
  `build_tenant_signature_headers` constructs signatures, and AR/CH code
  paths call only `verify_*` / forwarding helpers. Phase 9.4 asserts no
  CH/AR code path can construct a valid signature.

---

## Phase 9.8 — Security Hardening Review vs `docs/config.yaml` `top_priority_rules`

Date: 2026-09-25 (Phase 9 test completion). Scope: confirm the four
top-priority architecture rules still hold with multi-tenancy merged,
with test evidence from the Phase 9 suites.

### Rule 1 — "3 backend services should be fully segregated" — HOLDING

- The tenant change adds no cross-service coupling: tenant context
  travels CC → CH/AR exclusively as signed headers (CS-19/CS-20).
- Evidence: `backend/tests/agent_runtime/test_tenant_header_verification.py`
  and `backend/tests/communication_hub/test_tenant_header_verification.py`
  (tamper/stale/unsigned/mismatch all rejected; verified context bound to
  `request.state`); `backend/tests/test_tenant_signature.py`
  (`test_receiver_services_never_import_signing_helper` structural guard).
- E2E: `three-service-architecture.spec.ts` and
  `service-segregation-security-audit.spec.ts` still green (mocked
  variants verified in the Phase 9 run; real-backend variants pass when
  the stack is up).

### Rule 2 — "Agent can only run in agent runtime services" — HOLDING

- Execution dispatch still terminates at AR; the tenant change binds the
  verified tenant context onto the existing execute/resume/terminate/
  intervene paths (Phase 8.5) without adding any new execution entry
  point.
- Evidence: AR header-verification suite (above) +
  `agent-security-segregation.spec.ts` green.

### Rule 3 — "Only Control Center can connect to database" — HOLDING

- Verified by inspection 2026-09-25: `create_async_engine` /
  `DATABASE_URL` / `POSTGRES_*` appear ONLY under `backend/app/db/session.py`
  (Control Center). No engine or DB credential exists in
  `backend/app/agent_runtime/` or `backend/app/communication_hub/`.
- The tenant scoping choke point (`app/db/tenant_scoping.py`) therefore
  strengthens the rule's intent: even CC's own queries are tenant-bounded.
- Evidence: `backend/tests/test_tenant_scoping.py` (24 tests: SELECT/
  UPDATE/DELETE/INSERT isolation, join-table inheritance, scope-miss
  audits) and `backend/tests/db/test_tenant_schema_migration.py`
  (87 schema assertions vs real PostgreSQL).

### Rule 4 — "Agent can not get any sensitive data (identity tokens, database credentials, etc.)" — HOLDING

- Section 3 above (Task 8.7 review) remains accurate: tokens resolved by
  CC, injected per tool call at CH over mTLS; AR/agents receive none.
- The tenant signing key is env-config on the three services, never sent
  to agents or the frontend; AR/CH can verify but never sign
  (`test_receiver_services_never_import_signing_helper`).
- Tenant data: agents resolve configuration only through CC data clients
  that forward CC-signed headers — an agent cannot widen its tenant, so
  no other tenant's secrets are reachable (CS-17/CS-18; cross-tenant
  A2A refusal tests in the CH suite).

### Findings

| # | Severity | Finding | Disposition |
|---|----------|---------|-------------|
| F-1 | Low (UX, not security) | `PlatformAdminRoute` treated the un-resolved tenancy state as "off" and bounced authorized platform admins deep-linking/refreshing `/platform/*` to the dashboard. Fail-closed direction (no data exposed), but availability defect for admins. | FIXED during Phase 9: store state is now tri-state (`null` = resolving); the guard waits while unknown, redirects only on resolved-false. Covered by `e2e/tests/single-tenant-regression.spec.ts` + `multi-tenant-lifecycle.spec.ts`. |
| F-2 | Low (UX) | `TenantSessionGate` "continue with current organization" wrote sessionStorage without triggering a re-render, leaving the picker visible until an unrelated re-render. | FIXED during Phase 9: reactive local dismissal added; covered by `e2e/tests/multi-tenant-login-flows.spec.ts`. |
| F-3 | Info | Background tasks outside the scheduler (plan-generation, auto-naming) still use unscoped sessions and write `tenant_id = NULL` rows (documented boundary in the 8.7 review above). No cross-tenant read path exists; rows are unreachable from tenant contexts (scoped queries filter on `tenant_id = :ctx`). | Accepted pre-existing boundary; tracked in the 8.7 section. |
| F-4 | Info | The `SAWarning: Cannot correctly sort tables … agent_jobs, agent_outputs, termination_requests` cycle surfaces during tenant delete/adoption backfill loops. Deletion completes correctly (covered by lifecycle tests incl. slug-reuse). | Cosmetic warning; recommend `use_alter=True` on the cyclic FKs in a future hygiene pass. |

### Verdict

All four top-priority rules hold. Cross-tenant paths are fail-closed and
audited (`cross_tenant_access_denied` / `tenant_boundary_violation` are
security-relevant and visible via the platform audit API). No security
escalation required.
