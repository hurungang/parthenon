# PRD: Production-Ready Configuration

## Epic Overview

Parthenon currently auto-initializes Keycloak realms and clients at Control Center startup — a convenience designed for development and test environments. In production, this creates a security risk and an operational impediment: the running application should not hold Keycloak admin credentials or perform identity provider bootstrapping. Additionally, the project has accumulated multiple overlapping setup scripts in `scripts/` that confuse operators and duplicate functionality. This epic separates bootstrap tooling from the runtime application, consolidates environment setup into a single clear entry point, and enables production deployments where PostgreSQL, Keycloak (or Azure EntraID), Redis, and observability infrastructure are provided externally and configured purely through environment variables — without editing YAML files or application code.

## Business Goals

- **Reduce production attack surface**: Remove identity provider admin credentials and auto-provisioning logic from running services, ensuring the Control Center does not hold or use Keycloak admin access at runtime.
- **Simplify operator experience**: Replace multiple overlapping init/check/fix scripts with one universal setup command that covers all environment bootstrapping needs in a predictable, repeatable way.
- **Enable external infrastructure adoption**: Allow production deployments to use enterprise-managed PostgreSQL, Azure EntraID (or any OIDC provider), managed Redis, and existing observability stacks, configured entirely through environment variables.
- **Zero-code-change production configuration**: Every infrastructure connection point (database, identity provider, Redis, telemetry export targets) must be configurable via environment variables without editing configuration files or rebuilding containers.
- **Preserve developer productivity**: Local development setup must remain as simple as it is today (single command to bootstrap a full dev environment) while the production path becomes cleanly separated.

## Users & Personas

| Persona | Primary Need |
|---------|--------------|
| **DevOps / SRE Engineer** | Deploy Parthenon in a production Kubernetes cluster using enterprise-managed PostgreSQL, Azure EntraID for identity, and existing Prometheus/Jaeger/Loki observability — all configured via Helm values or environment variables, with no application code changes. |
| **Platform Operator** | Initialize a new Parthenon environment (dev, staging, or self-hosted production) using a single, documented command that handles Keycloak realm/client setup, database seeding, and certificate bootstrapping in the correct order. |
| **Developer** | Spin up a local development environment with one command that provisions everything (Keycloak, DB, certs) just as quickly as before, without needing to understand production configuration concerns. |

## User Stories

1. **As a DevOps Engineer**, I want to deploy Parthenon with an external PostgreSQL database and Azure EntraID as my identity provider, so that I can use my organization's existing managed infrastructure without modifying Parthenon's source code or configuration files.

2. **As a Platform Operator**, I want to run a single `setup` command to initialize a new environment (realm, clients, roles, admin user, certificates), so that I no longer need to discover and execute the correct sequence of scripts from the `scripts/` directory.

3. **As a Developer**, I want local development setup to remain a one-command experience, so that my workflow is not slowed down by production-oriented configuration complexity.

4. **As a DevOps Engineer**, I want all infrastructure connections (PostgreSQL, Redis, OIDC provider, OTEL exporters) to be configurable via environment variables, so that I can manage configuration through my Kubernetes secrets and config maps without touching YAML files inside container images.

5. **As a Platform Operator**, I want the running Control Center to have zero knowledge of Keycloak admin credentials, so that a compromise of the application does not expose the identity provider's administrative access.

## Acceptance Criteria

### Keycloak Bootstrap Separation
- The Control Center starts and operates correctly without any Keycloak admin credentials present in its environment — Keycloak realm/client auto-provisioning does not run at startup.
- A dedicated setup tool (outside the main application containers) can initialize Keycloak realms, clients, roles, and an initial admin user when given Keycloak admin credentials.
- After setup has been run once, the Control Center can validate the expected Keycloak configuration exists and fail with a clear, actionable error message if it does not (rather than silently failing or auto-provisioning).

### Consolidated Setup
- A single entry-point setup command exists that can perform all environment initialization tasks: Keycloak realm/client setup, database readiness verification, certificate authority bootstrapping, and (in dev mode) seeding of test data.
- Running the setup command twice is idempotent — it detects existing configuration and reports what is already in place without errors.
- The setup command produces clear output showing what was created, what was skipped, and any errors encountered.
- Operators can discover the setup command and its options through built-in help (e.g., `--help` flag).

### Production-Ready Configuration
- All of the following can be configured via environment variables without editing YAML files: PostgreSQL connection (host, port, database, user, password), Redis connection (host, port, password), OIDC provider (issuer URL, client ID, client secret), and OTEL export targets (traces, metrics, logs endpoints).
- When environment variables are set for a connection, the application uses them and ignores the corresponding YAML file values.
- When environment variables are NOT set, the application falls back to YAML configuration with sensible defaults that work for local development.
- The application logs at startup which configuration source was used for each connection (env var or YAML file) to aid operators in debugging.

### No Regression in Developer Experience
- A developer can still run a single command to start all services locally with auto-provisioned Keycloak, database, and certificates.
- The consolidated setup can be called with a `--dev` flag that performs the full bootstrap just as the old `init-local-dev.py` did.

## Out of Scope

- **UI changes**: No changes to the Web UI are included in this epic.
- **Database schema changes**: No new tables, columns, or migrations are required.
- **Helm chart authoring**: While this epic enables Helm-based deployment by externalizing configuration, it does not include creating or updating Helm charts.
- **CI/CD pipeline changes**: GitHub Actions and deployment pipelines are not modified.
- **Switching from Keycloak**: This epic supports external OIDC providers (Azure EntraID), but does not remove the bundled Keycloak option for self-hosted deployments.
- **Secrets management integration**: Environment variables are the mechanism; integration with HashiCorp Vault, AWS Secrets Manager, or similar is deferred.

## Dependencies & Constraints

- **Keycloak admin API availability**: The setup tool depends on the Keycloak admin REST API being reachable during initialization. Setup must handle the case where Keycloak is not yet ready (retry with timeout).
- **Existing YAML config files**: `config/identity.yaml` and `config/telemetry.yaml` are the existing configuration files; this epic must maintain backward compatibility with them while adding environment variable overrides.
- **Configuration convention (`docs/config.yaml`)**: The project convention states "Identity provider configuration is managed via `config/identity.yaml` — written by setup wizard or CLI; operators should NOT hand-edit this file" and "Telemetry configuration is managed via `config/telemetry.yaml` and `TELEMETRY_*` environment variables." This epic extends the telemetry pattern to all infrastructure configuration.
- **Top-priority architecture rules**: The 3-service segregation (CC, AR, CH) must be maintained; only Control Center connects to the database; agents never receive sensitive data like identity tokens or database credentials.
- **Certificate-based authentication**: The inter-service mTLS certificate system (agent-instance certs, service certs via Control Center CA) must continue to function and must be bootstrapable by the setup command.
