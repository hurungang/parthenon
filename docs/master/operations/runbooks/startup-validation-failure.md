# Runbook: Startup Validation Failure

Triaging service startup failures caused by dependency validation checks. When any service fails to start, it emits a `startup.validation.*_failed` log event identifying which dependency is unreachable or misconfigured.

---

## Quick Diagnosis

Every service validates its external dependencies at startup. The failing dependency is identified by the log event name:

| Log Event | Dependency | Affected Service |
|-----------|-----------|-----------------|
| `startup.validation.database_failed` | PostgreSQL | Control Center |
| `startup.validation.keycloak_not_found` | Keycloak realm | Control Center |
| `startup.validation.redis_failed` | Redis | Control Center, Communication Hub |
| `startup.validation.control_center_unreachable` | Control Center | Agent Runtime, Communication Hub |

The service exits with a non-zero code and will not proceed to operational state until the validation passes.

---

## Resolution Steps by Dependency

### 1. PostgreSQL Unreachable (`startup.validation.database_failed`)

**Affected service**: Control Center

**Resolution**:
1. Verify the `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` values (or `DATABASE_URL`) match the actual database deployment
2. Verify PostgreSQL is running and accepting connections
3. Verify network connectivity from the CC container to the PostgreSQL host:
   ```bash
   ping <POSTGRES_HOST>
   telnet <POSTGRES_HOST> <POSTGRES_PORT>
   ```
4. Check the startup log for `config.database.resolved` to confirm which configuration source was used and whether it matches expectations
5. After fixing, restart the Control Center — the startup log should show `startup.validation.database_ok`

### 2. Keycloak Realm Not Found (`startup.validation.keycloak_not_found`)

**Affected service**: Control Center

**Resolution for bundled Keycloak**:
1. Verify Keycloak is running and the admin API is reachable
2. Set `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` in the environment for the setup tool (**not** the CC service)
3. Run `setup identity` to provision the realm and clients
4. Run `setup verify` to confirm the realm is now reachable
5. Restart the Control Center — the startup log should show `startup.validation.keycloak_ok`

**Resolution for external OIDC provider**:
1. Verify `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, and `OIDC_CLIENT_SECRET` are set correctly on the CC service
2. Verify the OIDC discovery document is reachable from the CC container's network:
   ```bash
   curl <OIDC_ISSUER_URL>/.well-known/openid-configuration
   ```
3. Verify the registered client in the external identity provider has the correct redirect URI and grant types
4. Restart the Control Center

### 3. Redis Unreachable (`startup.validation.redis_failed`)

**Affected services**: Control Center, Communication Hub

**Resolution**:
1. Verify the `REDIS_HOST`, `REDIS_PORT`, and `REDIS_PASSWORD` values (or `REDIS_URL`) match the actual Redis deployment
2. Verify Redis is running:
   ```bash
   redis-cli -h <REDIS_HOST> -p <REDIS_PORT> PING
   ```
3. Verify network connectivity from the affected service container to the Redis host
4. Check the startup log for `config.redis.resolved` to confirm which configuration source was used
5. After fixing, restart the affected service — the startup log should show `startup.validation.redis_ok`

### 4. Control Center Unreachable (`startup.validation.control_center_unreachable`)

**Affected services**: Agent Runtime, Communication Hub

**Resolution**:
1. Verify the Control Center is healthy:
   ```bash
   curl <CONTROL_CENTER_URL>/health
   ```
2. Verify `CONTROL_CENTER_URL` is set correctly on the AR/CH service
3. Verify network connectivity between the AR/CH container and the Control Center
4. If the Control Center started but then failed, check CC logs for its own validation failures — the CC must be fully healthy before AR and CH can validate against it
5. After fixing the CC issue and confirming its health, restart AR/CH — the startup log should show `startup.validation.control_center_ok`

---

## Verifying the Fix

After resolving the dependency issue:

1. Restart the affected service
2. Check the startup log for `startup.validation.complete` with `all_passed=true`
3. The service should now proceed to its operational state

If the validation fails again, the root cause was not fully resolved — review the specific `_failed` event for the exact error detail and re-triage.

---

## Configuration Source Diagnosis

If a service fails validation despite apparently correct configuration, the service may be using the wrong configuration source. Check the startup log for `config.*.resolved` events:

- **`source=env var`**: The service resolved configuration from environment variables — the correct production behaviour.
- **`source=yaml:config/...`**: The service is using a YAML file, which may be stale or incorrect. Override with environment variables.
- **`source=default`**: The service is using built-in defaults, meaning the corresponding environment variable is not set. Set it explicitly.

In production, all infrastructure connections should resolve from `env var`. Any `yaml` or `default` source indicates a missing environment variable.

---

## Restart Loop Detection

If a service restarts more than 3 times in 10 minutes, this may indicate an intermittent infrastructure connectivity issue rather than a configuration problem:

1. Check the service's startup validation logs across restart cycles — look for `_failed` events that appear intermittently
2. Investigate the infrastructure component for transient issues (network flaps, resource pressure, load spikes)
3. The `ServiceRestartLoop` alert fires when this threshold is exceeded
