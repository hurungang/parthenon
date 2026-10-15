# Deployment Notes: strict-tenant-isolation

## Environment Variables

None. All enforcement is server-side (signed internal headers already exist; tenant resolution is database/config-driven). No new `TELEMETRY_*`, connection, or feature-flag variables are introduced.

## Infrastructure Changes

None expected. No new services, ports, containers, reverse-proxy rules, or certificate changes. The only external dependency is PostgreSQL 16, already provisioned.

## Migration Steps (Ordered)

1. **Backup.** Take a full PostgreSQL backup immediately before starting; rollback relies on downgrade plus this backup for non-migration issues.
2. **Pre-flight checks.** For every affected data-plane table (data types, skills/SOPs/bindings, agent roles/identities/types and join tables, agent data, agent outputs, recipient groups, notification channels, mappings and logs, scheduled jobs/executions, policy statements/resources, tag definitions, model configs), record the count of NULL-tenant rows. These counts become the rollback baseline and the post-migration verification target.
3. **Apply migrations.** Run `alembic upgrade head` from `backend/`. This chains the idempotent NULL→root adoption data migration (down-revision `a7b9c1d3e5f7`) followed by the constraint swaps: `tenant_id` becomes NOT NULL and NULL-variant partial unique indexes are dropped; per-tenant uniqueness from `a7b9c1d3e5f7` is preserved. The adoption step resolves the root tenant at runtime, guards on `tenant_id IS NULL`, and no-ops if the root tenant does not exist yet — safe to re-run.
4. **Verify pre-restart.** Confirm `alembic current` is at head and zero NULL-tenant rows remain (queries below).

## Deploy Order: CC → AR → CH

1. **Control Center first.** CC owns the database (the only service with DB access), the migration tooling, tenant resolution, and the CA. The new code expects the tightened schema and mandatory tenant bindings; with migrations applied it can serve both adopted (root-owned) data and fail-closed internal requests.
2. **Agent Runtime next.** AR rejects or root-binds execution requests per the tenant switch and forwards signed tenant headers on every internal call. It depends on CC being live for certificate bootstrap and tenant-context verification, so it must never start before CC.
3. **Communication Hub last.** CH re-verifies and forwards tenant headers on execute/A2A hops and serves per-tenant MCP protocol endpoints; it needs both CC (permission resolution, certs) and the new AR header-forwarding behavior to be in place.

Restart via `parthenon.ps1 restart -Services backend -Force` (or per-service restarts in the order above) so certificates bootstrap with CC up.

## Post-Migration Verification

- `alembic current` reports head (the revision after `a7b9c1d3e5f7`).
- Re-run the NULL-tenant count queries: every affected table must report zero.
- Spot-check that previously NULL-tenant rows now carry the root tenant id.
- Exercise a two-tenant (or simulated cross-tenant) flow: query_result name collision, save_data/get_data invisibility, A2A delegation, MCP tools/list per tenant.
- Watch `backend/logs/control-center.log`, `agent-runtime.log`, and `communication-hub.log` for tenant-scope rejections, 401s on internal data-plane routes, and cert bootstrap errors.

## Rollback Procedure

1. **Order: CH → AR → CC** (reverse of deploy) — stop forwarding traffic on the newest behaviors first.
2. **Code rollback** per service to the previous build.
3. **Downgrade migration:** run `alembic downgrade` back through the constraint swaps and the adoption revision. The downgrade restores NULLs on previously adopted rows (the migration records which rows it adopted or restores from the pre-flight baseline), making the upgrade replayable. Verify with the NULL-count queries that counts match the pre-flight baseline.
4. **Caveat — adopted rows cannot safely return to NULL once strict matching is live.** After any code that performs strict `(tenant_id = own)` matching has served traffic, downgrading the data back to NULL means those rows become invisible to the strict predicates (the NULL-shared slot is retired). Only roll the data migration back if you are also rolling back the application code to a build that still understands the NULL-shared slot; otherwise leave the rows adopted (root-owned) and roll back code only.
5. If only code rollback is needed (schema kept), no `alembic downgrade` is required — the pre-change code tolerates NOT NULL tenant columns but treats all rows as root-owned, which matches the adopted state.

## docs/master/deployment/ Updates

- `database-migrations.md` — add the adoption + constraint-swap revisions, their order, idempotency behavior, and the pre-flight NULL-count / post-migration zero-check procedure.
- `rollback.md` — add the strict-matching caveat (adopted rows must not be re-NULLed once strict matching is live) and the CH → AR → CC rollback ordering.
- `environment-variables.md` — no changes (confirm and note none required).
- `operational-runbooks.md` — add troubleshooting entries: 401s on `/api/v1/internal/*` (missing/invalid signed tenant headers), scope-miss audit events, and post-migration NULL-tenant verification queries.
- `first-time-deployment.md` / `README.md` — only if the standard runbook references migration heads; update the head revision reference.
