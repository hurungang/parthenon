## Deployment Notes: namespace-resource-types

## Environment Variables

No new or changed environment variables required. This change does not introduce new service configurations or modify existing ones.

## Infrastructure Changes

No infrastructure changes. Existing database, services, and Docker Compose / Kubernetes configuration remain unchanged. No new containers, ports, volumes, or networks are introduced.

## Migration Steps

This is a **data-only migration** (no schema changes). The Alembic migration transforms legacy flat resource type values in `policy_statements.module` and `policy_resources.resource_type` to the new `module::submodule` format. After migration, the backend validates all resource types against the new namespaced manifest and rejects flat values.

The migration must complete **before the updated backend starts serving traffic** to avoid inconsistent permission evaluation.

### Step 1 — Stop Control Center

Stop the Control Center container (or scale the Deployment to zero replicas in Kubernetes). Only Control Center connects to the database, so stopping it prevents concurrent writes against a partially migrated dataset.

Leave PostgreSQL, Redis, Agent Runtime, Communication Hub, and all other services running.

### Step 2 — Run the Alembic Migration

Execute the data migration against the running PostgreSQL instance from the `backend/` directory:

```
python -m alembic upgrade head
```

The migration:
- Transforms 7 direct 1:1 legacy renames (e.g., `agent` → `agent::management`, `role` → `agent::roles`)
- Consolidates 2 many:1 groups (`conversation` + `result` → `agent::trails`; `permissions` + `group` + `user` + `tag` + `access_request` → `system::permissions`)
- Transforms legacy `*` wildcard to `*::*`
- Is idempotent — skips rows already containing `::`

Verify the migration completed:

```
python -m alembic current
```

Confirm the output shows the latest revision. Query `policy_statements` and `policy_resources` to verify no legacy flat values remain.

### Step 3 — Deploy Updated Backend Code

Deploy the updated Control Center image containing the new `resource_types.py` manifest, updated `PermissionEngine`, and router-level constant changes. The updated backend validates all resource types against the 17 namespaced identifiers and rejects flat values at policy CRUD time.

If using Docker Compose, update the `control-center` image tag. If using Kubernetes, update the Deployment with the new image and trigger a rolling restart.

### Step 4 — Restart All Backend Services

Start services in the standard dependency order:

1. **Control Center** — Confirm the `/health` endpoint responds. Verify the Permission Engine startup log shows no errors related to the manifest.
2. **Agent Runtime** — Confirm the `/health` endpoint responds. Certificate bootstrap completes as normal (no changes).
3. **Communication Hub** — Confirm the `/health` endpoint responds. Certificate bootstrap completes as normal (no changes).

Wait for each service to reach a healthy state before starting the next. Service order enforces the certificate bootstrap dependency: Control Center must be healthy before AR and CH can obtain certificates.

### Step 5 — Deploy Updated Frontend

Deploy the updated Web UI containing the grouped resource type dropdown (`AddStatementDialog`) and updated `resourceTypes.ts` manifest.

Verify:
- The frontend application loads in a browser and resolves the Platform API
- The OIDC login flow completes successfully

### Step 6 — Verify

1. Log in as `system_admin` and confirm all `/permissions` sub-pages load without 403 errors.
2. Navigate to a role's policy statements and verify existing policies display namespaced resource types (e.g., `agent::management`, `integration::mcp_hub`).
3. Create a new policy statement via the `AddStatementDialog` — confirm the resource type dropdown shows all 17 options grouped under **Agents**, **Integrations**, and **System**.
4. Select `agent::management` with action `read` and create the statement — verify it persists and displays correctly.
5. Edit the statement to change the resource type to `integration::mcp_hub` — confirm the edit saves.
6. Delete the statement — confirm removal.
7. Run the standard smoke test from `docs/master/deployment/first-time-deployment.md` Step 11 to confirm end-to-end agent interaction works.
8. Verify the `system_admin` role retains its `*::*` wildcard policy (checked during bootstrap on Control Center startup).

## Rollback Procedure

Use this procedure if the deployment fails and the platform must be restored to its pre-migration state.

### Trigger Conditions

Initiate rollback if any of the following occur:

- Permission Engine returns 403 for legitimate requests that previously succeeded
- Wildcard policy evaluation (`*::*`, `module::*`) fails to match expected modules
- Policy CRUD endpoints reject valid namespaced resource types with validation errors
- Legacy flat values appear unmigrated in `policy_statements` or `policy_resources` after the upgrade ran

### Step R1 — Stop Control Center

Stop the Control Center container or scale its Deployment to zero replicas. Leave all other services running.

### Step R2 — Roll Back the Database Migration

Run the Alembic downgrade to revert the data migration:

```
python -m alembic downgrade -1
```

> **Downgrade behaviour**: The `downgrade()` function reverses all 1:1 renames and transforms `*::*` back to `*`. For consolidation reversals, `agent::trails` maps back to `conversation` (not `result`) and `system::permissions` maps back to `permissions` (not the other four consolidated types). Any policy statements or resources created after the migration using the new namespaced format will be left unchanged — these were not present before the upgrade and the downgrade is a best-effort reversal, not a magical undo.

Verify the downgrade:

```
python -m alembic current
```

Confirm the output shows the previous revision (the pre-upgrade head).

### Step R3 — Deploy Previous Backend and Frontend Images

Redeploy the previous Control Center, Agent Runtime, Communication Hub, and Web UI images (the versions in use before this change was deployed).

For Docker Compose: update image tags to the previous versions and bring services up.
For Kubernetes: run `helm rollback` or re-apply with the previous image tags.

### Step R4 — Restart Services

Start services in standard order: Control Center → Agent Runtime → Communication Hub → Web UI. Wait for each health check to pass before starting the next.

### Step R5 — Verify Legacy Compatibility

1. Log in as `system_admin` and confirm all `/permissions` pages load without 403 errors.
2. Navigate to role policy statements — confirm flat resource types display correctly (e.g., `agent`, `mcp_server`, `role`).
3. Create a policy statement using a legacy flat type — confirm it persists and the legacy validation logic accepts it.
4. Run the standard smoke test to confirm end-to-end platform functionality.

## Master Deployment Update Instructions

Update the following master deployment documents after this change is merged:

### `docs/master/deployment/database-migrations.md`

Add a new row to the Migration History table:

- **Revision**: The generated Alembic revision ID
- **File**: The migration filename (e.g., `{revision}_namespace_resource_types.py`)
- **Description**: "Namespaced Resource Types — data-only migration transforming legacy flat resource type identifiers in `policy_statements.module` and `policy_resources.resource_type` to `module::submodule` format. 7 direct renames, 2 many:1 consolidations, and `*` → `*::*` wildcard transformation. No schema changes."
- **Tables Added / Modified**: `policy_statements.module` (value format), `policy_resources.resource_type` (value format)
- **Production Date**: Record when deployed to production

Add a note to the Notes section documenting:
- This is a **data-only migration** — no schema changes (no new tables, columns, or constraints)
- The migration is **idempotent** — rows already containing `::` are skipped
- Downgrade provides **best-effort reversal** — any policy statements or resources created after the migration with new namespaced values will be left unchanged
- After migration, the backend rejects flat resource type values. The migration must complete before the updated backend starts serving traffic.
- Only Control Center connects to the database; Agent Runtime and Communication Hub consume permission data via the Control Center API and are unaffected by the data migration.

### `docs/master/deployment/rollback.md`

Add a new "Change-Specific Rollback: Namespaced Resource Types" section documenting the rollback procedure above (Steps R1–R5). Include:
- Trigger conditions
- The downgrade behaviour note about consolidation best-effort reversal
- Verification that legacy flat types work after rollback

### No updates needed for

- `environment-variables.md` — No new or changed variables
- `services.md` — No service inventory changes
- `first-time-deployment.md` — No changes to the fresh-install sequence (migrations are applied as part of Step 3 regardless)
- `configuration-files.md` — No new config files
- `operational-runbooks.md` — No new operational procedures
