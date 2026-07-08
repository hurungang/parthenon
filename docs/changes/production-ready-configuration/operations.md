# Operations: Production-Ready Configuration

## 1. Monitoring

This change introduces startup validation checks and configuration source logging that must be monitored to detect misconfiguration before it causes runtime failures.

### Startup Validation Health

Each service now validates its external dependencies at startup rather than provisioning them. These validations emit structured log events and health check results.

| Service | Validation | Log Event on Success | Log Event on Failure | Impact of Failure |
|---------|------------|----------------------|----------------------|-------------------|
| Control Center | PostgreSQL reachability | `startup.validation.database_ok` | `startup.validation.database_failed` | CC fails to start |
| Control Center | Keycloak realm existence | `startup.validation.keycloak_ok` | `startup.validation.keycloak_not_found` | CC fails to start; operator must run setup command or fix OIDC config |
| Control Center | Redis reachability | `startup.validation.redis_ok` | `startup.validation.redis_failed` | CC fails to start |
| Agent Runtime | Control Center reachability | `startup.validation.control_center_ok` | `startup.validation.control_center_unreachable` | AR fails to start; cannot bootstrap certificate |
| Communication Hub | Control Center reachability | `startup.validation.control_center_ok` | `startup.validation.control_center_unreachable` | CH fails to start; cannot bootstrap certificate |
| Communication Hub | Redis reachability | `startup.validation.redis_ok` | `startup.validation.redis_failed` | CH fails to start; message brokering unavailable |

**Monitoring guidance**: In production, alert if any service restarts more than twice within 5 minutes, as this may indicate an intermittent infrastructure connectivity issue rather than a configuration problem.

### Service Reachability Checks

The following endpoints must be monitored for the three-service architecture:

| Target | URL | Expected | Check Frequency |
|--------|-----|----------|----------------|
| Control Center health | `GET http://<cc-host>:8000/health` | `200 OK` | Every 30 seconds |
| Agent Runtime health | `GET http://<ar-host>:8001/health` | `200 OK` (only after CC is healthy) | Every 30 seconds |
| Communication Hub health | `GET http://<ch-host>:8002/health` | `200 OK` (only after CC and Redis are healthy) | Every 30 seconds |
| Certificate Authority | `GET http://<cc-host>:8000/api/v1/certificates/ca` | `200 OK` with `expires_at` field | Every 5 minutes |

### Configuration Source Telemetry

On every startup, services log the configuration source resolved for each infrastructure connection. These structured log lines use the pattern:

`config:<connection_type> resolved from <source>`

Where `<source>` is one of: `env var <VARIABLE_NAME>`, `YAML file <file_path>`, or `built-in default`.

**What to monitor**:
- In production, the source should consistently be `env var` for all infrastructure connections. If any connection resolves from `YAML file` or `built-in default` in a production environment, the operator has likely forgotten to set the corresponding environment variable.
- A change in the resolved source between restarts indicates a configuration drift that should be investigated.
- The source log for `database`, `redis`, and `oidc_provider` connections is the most important — missing env vars for these will cause startup failure.

### New Dashboards to Create

- **Startup Health Dashboard**: Panel showing the last startup status of each service (success or failed, with the failure reason from the startup validation log). Useful for detecting configuration regressions across rolling restarts.
- **Configuration Source Dashboard**: Panel aggregating the `config:<connection> resolved from <source>` log events across all services, colour-coded by source (env var = green, YAML = yellow, default = red). Gives operators at-a-glance visibility into which services are using which configuration model.

### New Alerts to Configure

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `StartupValidationFailed` | `startup.validation.*_failed` log event present | Critical | Page on-call; service cannot start; check the specific dependency |
| `ConfigurationFromDefault` | Any `resolved from built-in default` log event in production | Warning | Operator review: ensure all production infrastructure env vars are set |
| `KeycloakConfigNotFound` | `startup.validation.keycloak_not_found` log event present | Critical | Operator must run `setup identity` or verify OIDC environment variables |
| `KeycloakAdminCredsInRuntime` | `KEYCLOAK_ADMIN` detected in CC environment at startup | Critical | Security violation: admin credentials exposed to runtime; remove immediately |
| `ServiceRestartLoop` | Any service restarts > 3 times in 10 minutes | Critical | Page on-call; intermittent infrastructure connectivity likely |

---

## 2. Logging

### Configuration Source Logging

Every infrastructure connection is logged at startup with the resolved configuration source. These log events use the namespace `parthenon.config` and are emitted at `INFO` level.

| Log Event | Level | Key Fields | When Logged |
|-----------|-------|------------|-------------|
| `config.database.resolved` | INFO | `host`, `port`, `database`, `source`, `source_detail` | After PostgreSQL connection parameters are resolved |
| `config.redis.resolved` | INFO | `host`, `port`, `source`, `source_detail` | After Redis connection parameters are resolved |
| `config.oidc.resolved` | INFO | `issuer_url`, `client_id`, `provider_type`, `source`, `source_detail` | After OIDC configuration parameters are resolved |
| `config.telemetry.resolved` | INFO | `exporter_type`, `source`, `source_detail` | After telemetry configuration is resolved |

**`source_detail` values**:
- `env_var:POSTGRES_HOST` — resolved from a specific environment variable
- `yaml:config/telemetry.yaml` — resolved from a YAML configuration file
- `default` — using the built-in default value

### Startup Validation Logging

All startup validation checks emit structured log events under the namespace `parthenon.startup`. These are distinct from the normal runtime health check logs.

| Log Event | Level | Key Fields | When Logged |
|-----------|-------|------------|-------------|
| `startup.validation.begin` | INFO | `service_name`, `dependencies` | Startup validation phase begins; lists which dependencies will be checked |
| `startup.validation.database_ok` | INFO | `host`, `port`, `latency_ms` | PostgreSQL reachability confirmed |
| `startup.validation.database_failed` | ERROR | `host`, `port`, `error` | PostgreSQL unreachable; includes connection error detail |
| `startup.validation.keycloak_ok` | INFO | `issuer_url`, `realm_found` | Keycloak realm confirmed to exist |
| `startup.validation.keycloak_not_found` | ERROR | `issuer_url`, `expected_realm`, `error_detail` | Expected Keycloak realm does not exist or OIDC discovery endpoint unreachable |
| `startup.validation.redis_ok` | INFO | `host`, `port`, `latency_ms` | Redis PING successful |
| `startup.validation.redis_failed` | ERROR | `host`, `port`, `error` | Redis PING failed; includes connection error detail |
| `startup.validation.control_center_ok` | INFO | `url`, `latency_ms` | Control Center health check successful (logged by AR and CH) |
| `startup.validation.control_center_unreachable` | ERROR | `url`, `error`, `retries_exhausted` | Control Center health check failed after all retries |
| `startup.validation.complete` | INFO | `service_name`, `all_passed` | All validations complete; service proceeding to operational state |

### Keycloak Admin Credential Detection

If the Control Center detects `KEYCLOAK_ADMIN` in its environment at startup, it logs a prominent warning but does not use the credentials. This is a security guardrail:

| Log Event | Level | Key Fields | When Logged |
|-----------|-------|------------|-------------|
| `config.keycloak_admin_detected_in_runtime` | WARNING | `service_name` | KEYCLOAK_ADMIN or KEYCLOAK_ADMIN_PASSWORD found in CC environment; credentials are ignored by runtime |

### Setup Tool Logging

The consolidated setup command emits its own structured log events, separate from the runtime service logs. These are written to stdout when the setup tool is run.

| Log Event | Level | Key Fields | When Logged |
|-----------|-------|------------|-------------|
| `setup.identity.realm_created` | INFO | `realm_name` | New Keycloak realm provisioned |
| `setup.identity.realm_exists` | INFO | `realm_name` | Realm already exists; skipped (idempotent) |
| `setup.identity.client_created` | INFO | `client_id`, `realm` | New OIDC client registered |
| `setup.identity.client_exists` | INFO | `client_id` | Client already registered; skipped |
| `setup.identity.admin_created` | INFO | `username`, `realm` | Admin user created in Keycloak |
| `setup.identity.admin_exists` | INFO | `username` | Admin user already exists; skipped |
| `setup.database.verified` | INFO | `host`, `port`, `database` | Database schema and connectivity confirmed |
| `setup.database.seeded` | INFO | `entity_type`, `count` | Default data seeded (roles, permissions, skills, system tools) |
| `setup.certificates.ca_created` | INFO | `serial_number`, `expires_at` | New certificate authority generated |
| `setup.certificates.ca_exists` | INFO | `serial_number` | CA already exists; skipped |
| `setup.verify.all_ok` | INFO | — | All components in expected state |
| `setup.verify.issues_found` | WARNING | `issues` | One or more components need attention; lists specific issues |
| `setup.error` | ERROR | `operation`, `error` | Setup operation failed; includes full error detail |

### Log Access

| Source | Docker Compose | Kubernetes | Loki |
|--------|---------------|------------|------|
| CC startup validation | `docker compose logs control-center` | `kubectl logs <cc-pod>` | `{service_name="control-center"} \|= "startup.validation"` |
| AR startup validation | `docker compose logs agent-runtime` | `kubectl logs <ar-pod>` | `{service_name="agent-runtime"} \|= "startup.validation"` |
| CH startup validation | `docker compose logs communication-hub` | `kubectl logs <ch-pod>` | `{service_name="communication-hub"} \|= "startup.validation"` |
| Configuration source | `docker compose logs <service>` | `kubectl logs <pod>` | `{service_name=~".+"} \|= "config."` |
| Setup tool output | stdout of the setup command/job | stdout of the setup Job pod | Not shipped to Loki (setup is a one-shot operation) |

---

## 3. Common Issues

### Issue: Control Center Fails to Start — "Keycloak configuration not found"

**Symptoms**: CC startup log shows `startup.validation.keycloak_not_found` with `expected_realm=<realm>`. The service exits with a non-zero code.

**Root cause**: The expected Keycloak realm does not exist because the setup command was not run, or the OIDC environment variables are incorrect (external provider).

**Resolution for bundled Keycloak**:
1. Verify Keycloak is running and the admin API is reachable
2. Set `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` in the environment for the setup tool (NOT the CC service)
3. Run `setup identity` to provision the realm and clients
4. Run `setup verify` to confirm the realm is now reachable
5. Restart the Control Center

**Resolution for external OIDC provider**:
1. Verify `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, and `OIDC_CLIENT_SECRET` are set correctly on the CC service
2. Verify the OIDC discovery document is reachable from the CC container's network: `curl <OIDC_ISSUER_URL>/.well-known/openid-configuration`
3. Verify the registered client in the external identity provider has the correct redirect URI and grant types
4. Restart the Control Center

### Issue: Control Center Fails to Start — "PostgreSQL unreachable"

**Symptoms**: CC startup log shows `startup.validation.database_failed` with connection error details.

**Root cause**: The database connection parameters are incorrect or PostgreSQL is not reachable from the CC container's network.

**Resolution**:
1. Verify the `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` values (or `DATABASE_URL`) match the actual database deployment
2. Verify the PostgreSQL server is running and accepting connections
3. Verify network connectivity from the CC container to the PostgreSQL host: `ping <POSTGRES_HOST>` or `telnet <POSTGRES_HOST> <POSTGRES_PORT>`
4. Check the startup log for `config.database.resolved` to confirm which configuration source was used and whether it matches expectations

### Issue: Control Center Fails to Start — "Redis unreachable"

**Symptoms**: CC or CH startup log shows `startup.validation.redis_failed` with connection error details.

**Root cause**: Redis is not reachable, the password is incorrect, or the host/port configuration is wrong.

**Resolution**:
1. Verify the `REDIS_HOST`, `REDIS_PORT`, and `REDIS_PASSWORD` values (or `REDIS_URL`) match the actual Redis deployment
2. Verify the Redis server is running: `redis-cli -h <REDIS_HOST> -p <REDIS_PORT> PING`
3. Verify network connectivity from the affected service container to the Redis host
4. Check the startup log for `config.redis.resolved` to confirm which configuration source was used

### Issue: Agent Runtime or Communication Hub Fails to Start — "Control Center unreachable"

**Symptoms**: AR or CH startup log shows `startup.validation.control_center_unreachable` with `retries_exhausted`.

**Root cause**: The Control Center is not running, `CONTROL_CENTER_URL` is incorrect, or there is a network partition.

**Resolution**:
1. Verify the Control Center is healthy: `curl <CONTROL_CENTER_URL>/health`
2. Verify `CONTROL_CENTER_URL` is set correctly on the AR/CH service
3. Verify network connectivity between the AR/CH container and the Control Center
4. If the Control Center started but then failed, check CC logs for its own validation failures — the CC must be fully healthy before AR and CH can validate against it

### Issue: Keycloak Admin Credentials Detected on Runtime

**Symptoms**: CC startup log shows `config.keycloak_admin_detected_in_runtime` WARNING.

**Root cause**: `KEYCLOAK_ADMIN` or `KEYCLOAK_ADMIN_PASSWORD` environment variables are still set on the Control Center service after the migration.

**Resolution**:
1. Immediately remove `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` from the Control Center service environment
2. Restart the Control Center
3. The warning is not harmful at runtime (credentials are ignored), but represents a security risk if the CC process is compromised
4. Verify these variables are only present on the setup service/Job environment

### Issue: Configuration Resolved from YAML or Default in Production

**Symptoms**: Startup log shows `config.database.resolved` or `config.redis.resolved` or `config.oidc.resolved` with `source=default` or `source=yaml:config/identity.yaml`.

**Root cause**: The corresponding environment variables were not set for the production deployment. The service may work initially but is fragile — any environment change may alter the default behaviour.

**Resolution**:
1. For each connection showing `default` or `yaml`, set the corresponding environment variable explicitly
2. For database: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` (or `DATABASE_URL`)
3. For Redis: `REDIS_HOST`, `REDIS_PORT` (or `REDIS_URL`)
4. For OIDC: `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` (for external providers)
5. Restart the service and verify the source changes to `env var`

### Issue: Setup Command Fails — "Keycloak admin API unreachable"

**Symptoms**: Running `setup identity` fails with a connection error to the Keycloak admin API.

**Root cause**: The bundled Keycloak container is not running, is not healthy, or the `KEYCLOAK_URL` variable is incorrect.

**Resolution**:
1. Verify the Keycloak container is running and the admin console is accessible
2. Verify `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` are set for the setup command
3. Verify `KEYCLOAK_URL` points to the correct admin API base (e.g., `http://localhost:8080` for Docker Compose)
4. The setup tool includes a retry with timeout for Keycloak readiness — if Keycloak takes longer than expected to start, increase the timeout

### Issue: Operator Accidentally Runs Old Ad-Hoc Scripts

**Symptoms**: An operator discovers and runs a deprecated script from `scripts/` instead of the consolidated setup command.

**Resolution**:
1. The deprecated scripts should be updated to print a deprecation warning directing the operator to use the consolidated setup command instead
2. After confirming the new setup command works for all use cases, remove the deprecated scripts entirely
3. Document the consolidated setup command as the only supported bootstrapping method in all deployment and operations runbooks

---

## 4. Master Operations Update Instructions

After implementation, update the following files in `docs/master/operations/`:

### `docs/master/operations/README.md`

- Add a "Setup Tool" section under the existing sections documenting the consolidated setup command: how to run it, sub-commands, idempotent behaviour, and expected output.
- Add the Control Center, Agent Runtime, and Communication Hub startup validation endpoints to the Production Health Check Targets table (these are new health-check consumers, not new endpoints — the existing `/health` endpoints remain).
- In the Runbooks table, add a new row: "Setup Tool" runbook — trigger symptoms include "CC fails to start with Keycloak config not found" or "Keycloak admin credentials detected in runtime log".
- Update the Quick Reference section at the top (if one exists) to note that `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` must NOT be set on the Control Center service.

### `docs/master/operations/monitoring.md`

- Add a new "Startup Validation" section under Key Metrics by Component listing: startup validation pass/fail per dependency, configuration source resolution, and service restart loop detection.
- Add the new "Startup Health Dashboard" and "Configuration Source Dashboard" to the Dashboards to Create section.
- Add the new alerts (`StartupValidationFailed`, `ConfigurationFromDefault`, `KeycloakConfigNotFound`, `KeycloakAdminCredsInRuntime`, `ServiceRestartLoop`) to the Alerts to Configure section.

### `docs/master/operations/logging.md`

- Add a new "Startup Validation Log Events" table under Per-Component Log Events documenting the `startup.validation.*` events, their levels, key fields, and when they are logged.
- Add a new "Configuration Source Log Events" table documenting the `config.*.resolved` events.
- Add the `config.keycloak_admin_detected_in_runtime` event to a new "Security Guardrail Log Events" row.
- Add a new "Setup Tool Log Events" table documenting the `setup.*` events (separate from runtime service logs).
- Update the Log Sources table to include setup tool output access methods.

### Create: `docs/master/operations/runbooks/setup-tool.md`

- Create a new runbook for the consolidated setup command.
- Document: how to run each sub-command (`identity`, `database`, `certificates`, `dev`, `verify`), expected output for each, idempotent behaviour, failure modes, and troubleshooting steps.
- Document the distinction between setup-time credentials (`KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD`) and runtime credentials.
- Include a section on migrating from the deprecated individual scripts to the consolidated command.

### Create: `docs/master/operations/runbooks/startup-validation-failure.md`

- Create a new runbook for triaging startup validation failures.
- Document: how to identify which validation failed from the log event, resolution steps for each dependency (PostgreSQL, Keycloak, Redis, Control Center), and how to verify the fix by checking the startup log for `startup.validation.complete`.
- Include guidance on the configuration source log: how to confirm the correct environment variables are being used.

### `docs/master/operations/runbooks/oidc-token-failure.md`

- Update the root cause analysis section to include "Keycloak realm not provisioned — operator must run `setup identity`" as a possible cause, now that auto-provisioning no longer masks this issue.

### `docs/master/operations/runbooks/certificate-security.md`

- Update to reference the consolidated setup command for certificate authority bootstrapping (`setup certificates`) instead of any deprecated individual certificate issuance scripts.
