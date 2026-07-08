# Spec Change: Production-Ready Configuration

## Affected Spec Areas

| Area | Impact |
|------|--------|
| `docs/master/deployment/` — Master deployment instructions | High — new environment variable model for all infrastructure |
| `docs/master/operations/` — Master operations runbooks | High — new setup command, changed bootstrap procedure |
| `docs/master/architecture/` — System architecture | Medium — component diagram changes (bootstrap tooling separated from runtime) |
| `docs/master/product/` — Feature specs (identity provider config) | Medium — external provider configuration capability |
| `docs/master/reference/` — Configuration reference | High — new environment variable catalog needed |

## New Capabilities

### NC1: Consolidated Environment Setup Command
A single, universal command replaces the collection of ad-hoc scripts currently in `scripts/`. This command handles all environment initialization: Keycloak realm/client provisioning, database readiness checks, certificate authority bootstrapping, and optional dev-mode data seeding. It is idempotent (safe to run multiple times) and self-documenting (built-in help).

### NC2: Environment-Variable-Driven Infrastructure Configuration
Operators can configure all external infrastructure connections through environment variables without editing YAML files or rebuilding container images. Covered connections: PostgreSQL, Redis, OIDC provider (issuer, client ID, client secret), and OpenTelemetry export targets (traces, metrics, logs). When environment variables are set, they take precedence over YAML file values; when absent, YAML defaults apply.

### NC3: External OIDC Provider Support Without Code Changes
Production deployments using Azure EntraID (or any OIDC-compliant provider) can be configured purely through environment variables. The application validates the provider configuration at startup and reports whether it is using the bundled Keycloak or an external provider. No recompilation, rebuilding, or YAML editing is required.

### NC4: Startup Configuration Diagnostics
On startup, each service logs which configuration source was resolved for every infrastructure connection (environment variable, YAML file, or built-in default). This gives operators immediate visibility into what configuration is active, reducing debugging time for misconfigured deployments.

## Modified Capabilities

### MC1: Keycloak Bootstrap — Extracted from Runtime to Setup Phase

| | Before | After |
|---|---|---|
| **When it runs** | At Control Center startup (every restart) | Only when operator explicitly runs the setup command |
| **Where it lives** | Built into the Control Center's application startup sequence | In a dedicated setup tool, separate from application containers |
| **Credentials** | Control Center holds Keycloak admin credentials at runtime | Only the setup tool (run by operator) uses admin credentials; Control Center has none |
| **Failure mode** | Silent auto-provisioning; may mask configuration errors | Clear error on startup if Keycloak config is missing or wrong; operator must explicitly fix |

### MC2: Setup Script Consolidation

| Before | After |
|---|---|
| Multiple scripts: `init-local-dev.py`, `fix-agent-client.py`, `fix-admin-permissions.py`, `check-admin-permissions.py`, `check-duplicate-admins.py`, `provision-test-user.py`, `issue-service-cert.py` | One setup command with sub-commands or flags for each operation |
| Operator must know which scripts exist and their correct execution order | Built-in help and ordered execution; command handles dependencies |
| No idempotency guarantees across scripts | All operations detect existing state and safely skip already-completed steps |

### MC3: Configuration Resolution Priority

| Before | After |
|---|---|
| YAML files (`config/identity.yaml`, `config/telemetry.yaml`) are the primary configuration source; some telemetry env vars supported | Environment variables are the primary source for production; YAML files serve as defaults and dev-mode convenience |
| Operator must edit YAML files inside the deployed container or bind-mount them | Operator provides environment variables through Kubernetes secrets/config maps or Docker Compose environment; no file editing required |

## Removed Capabilities

### RC1: Auto-Keycloak-Provisioning at Control Center Startup
The Control Center will no longer automatically create or modify Keycloak realms, clients, or roles at startup. If the expected identity provider configuration is not found, the service logs a clear error and fails to start — it does not silently attempt to fix the configuration. This capability is replaced by the consolidated setup command (NC1) which is run deliberately by an operator.

### RC2: Individual Ad-Hoc Setup Scripts
The collection of overlapping scripts in `scripts/` (`init-local-dev.py`, `fix-agent-client.py`, `fix-admin-permissions.py`, `check-admin-permissions.py`, `check-duplicate-admins.py`, `provision-test-user.py`, `issue-service-cert.py`) is replaced by the consolidated setup command. Individual scripts may be removed or redirected to the unified command.

## Spec Update Instructions

After implementation, the following master spec files must be updated:

### `docs/master/deployment/`
- Add new section documenting all environment variables for infrastructure configuration (PostgreSQL, Redis, OIDC, OTEL) with their expected format, defaults, and whether they are required for production.
- Update deployment instructions to describe the two deployment modes: bundled (Keycloak included) vs. external (Keycloak/Azure EntraID provided externally).
- Remove any references to Keycloak auto-provisioning at startup.

### `docs/master/operations/`
- Add runbook section for the consolidated setup command: how to run it, what flags are available, expected output, and troubleshooting.
- Document the idempotent behavior and how to verify each step completed successfully.
- Update the Keycloak administration section to describe that realm/client management is now a setup-time operation, not a runtime operation.

### `docs/master/architecture/`
- Update system component diagram: show the setup tool as a separate, operator-invoked component (not part of the running system).
- Remove Keycloak bootstrap from the Control Center's responsibilities in the component description.
- Show the configuration resolution flow: environment variables → YAML files → built-in defaults.

### `docs/master/product/`
- Update the identity provider configuration feature spec to include external OIDC provider support (Azure EntraID) as a first-class configuration option alongside bundled Keycloak.
- Add the consolidated setup command as a documented product capability.

### `docs/master/reference/`
- Create a new environment variable configuration reference catalog listing all supported variables, their YAML equivalents, and usage examples.
