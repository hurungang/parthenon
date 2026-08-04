# Runbook: Setup Tool

Using and troubleshooting the consolidated `setup` command for infrastructure bootstrap. The setup tool provisions all infrastructure dependencies (identity provider, database, certificates) before any service is started.

---

## Overview

The consolidated `setup` command replaces the deprecated individual scripts previously located in `scripts/`. All sub-commands are idempotent — safe to run repeatedly on an already-provisioned environment.

### Setup-Time vs. Runtime Credentials

- **Setup-time credentials**: `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` are required for the setup tool to provision Keycloak realms, clients, and admin users. These must be set in the setup tool's environment only.
- **Runtime credentials**: The Control Center, Agent Runtime, and Communication Hub services must **never** have `KEYCLOAK_ADMIN` or `KEYCLOAK_ADMIN_PASSWORD` in their environment. If detected, the CC logs a `config.keycloak_admin_detected_in_runtime` WARNING and ignores the credentials entirely.

---

## Sub-Commands

### `setup identity`

Provisions the identity provider for bundled Keycloak deployments.

```bash
KEYCLOAK_ADMIN=admin KEYCLOAK_ADMIN_PASSWORD=secret setup identity
```

**What it does**:
1. Verifies Keycloak is reachable at `KEYCLOAK_URL`
2. Creates the Parthenon realm if it does not exist (logs `setup.identity.realm_created` or `setup.identity.realm_exists`)
3. Registers OIDC clients for the API UI and agent runtime (logs `setup.identity.client_created` or `setup.identity.client_exists`)
4. Creates an admin user in the realm (logs `setup.identity.admin_created` or `setup.identity.admin_exists`)

**Expected output on first run**:
```
setup.identity.realm_created     realm_name=parthenon
setup.identity.client_created    client_id=parthenon-api-ui  realm=parthenon
setup.identity.client_created    client_id=parthenon-agent-runtime  realm=parthenon
setup.identity.admin_created     username=admin  realm=parthenon
```

**Idempotent behaviour**: Running `setup identity` a second time on the same environment logs `realm_exists`, `client_exists`, and `admin_exists` for each respective resource.

**Failure modes**:
- `setup.error` with `operation=identity` and error detail — Keycloak admin API unreachable. See [issue below](#issue-setup-command-fails--keycloak-admin-api-unreachable).

### `setup database`

Verifies database connectivity and seeds default data.

```bash
setup database
```

**What it does**:
1. Confirms PostgreSQL schema and connectivity (logs `setup.database.verified`)
2. Seeds default roles, permissions, skills, and system tools (logs `setup.database.seeded` with `entity_type` and `count`)

**Failure modes**:
- `setup.error` with `operation=database` — PostgreSQL unreachable or migration not applied. Verify database connection parameters and run `alembic upgrade head`.

### `setup certificates`

Bootstraps the Certificate Authority for service-to-service mTLS.

```bash
setup certificates
```

**What it does**:
1. Generates a new CA certificate and key if none exists (logs `setup.certificates.ca_created` with `serial_number` and `expires_at`)
2. Skips if the CA already exists (logs `setup.certificates.ca_exists`)

**Note**: For full certificate lifecycle management (issuing, renewing, revoking), use the Control Center API endpoints. This sub-command only bootstraps the CA.

### `setup dev`

Convenience command for development environments — runs `identity`, `database`, and `certificates` in sequence.

```bash
setup dev
```

### `setup verify`

Validates that all infrastructure components are in their expected state.

```bash
setup verify
```

**Expected output on success**:
```
setup.verify.all_ok
```

**Expected output on partial failure**:
```
setup.verify.issues_found    issues=["Keycloak realm not found", "Database not seeded"]
```

---

## Common Issues

### Issue: Setup Command Fails — "Keycloak admin API unreachable"

**Symptoms**: Running `setup identity` fails with `setup.error` and a connection error to the Keycloak admin API.

**Root cause**: The bundled Keycloak container is not running, is not healthy, or `KEYCLOAK_URL` is incorrect.

**Resolution**:
1. Verify the Keycloak container is running and the admin console is accessible
2. Verify `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` are set for the setup command
3. Verify `KEYCLOAK_URL` points to the correct admin API base (e.g., `http://localhost:8080` for Docker Compose)
4. The setup tool includes a retry with timeout for Keycloak readiness — if Keycloak takes longer than expected to start, increase the timeout

### Issue: Setup Database Fails — "PostgreSQL unreachable"

**Symptoms**: `setup database` fails with a connection error.

**Resolution**:
1. Verify `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` (or `DATABASE_URL`) match the actual database deployment
2. Verify PostgreSQL is running and accepting connections
3. Run `alembic upgrade head` to ensure migrations are applied

---

## Migrating from Deprecated Scripts

The individual ad-hoc scripts previously located under `scripts/` are deprecated. If you discover and attempt to run one of these scripts, you will see a deprecation warning directing you to use the consolidated `setup` command instead.

All bootstrap operations that were previously handled by separate scripts are now available through:

| Old Approach | New Approach |
|-------------|-------------|
| Individual Keycloak provisioning scripts | `setup identity` |
| Database initialization scripts | `setup database` |
| Certificate issuance scripts | `setup certificates` (CA bootstrap only) |

After confirming the consolidated setup command works for all use cases, the deprecated scripts should be removed. The consolidated `setup` command is the only supported bootstrapping method.
