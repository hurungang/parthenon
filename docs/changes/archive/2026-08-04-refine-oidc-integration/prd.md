# PRD: Refine OIDC Integration

## Epic Overview

The Parthenon platform currently ties its identity layer to Keycloak-specific OIDC assumptions and couples user authentication with agent identity in a single provider configuration stored in a static YAML file. This creates vendor lock-in, prevents separation of user and agent identity domains, and lacks a production-ready configuration experience. This epic industrializes the OIDC integration to support any OIDC-compliant provider, decouples user identity from agent identity so each can point to an independent provider, introduces a built-in super admin for production bootstrap, and moves all OIDC configuration from a static YAML file into the database-backed system config module with a web UI.

## Business Goals

- Support any OIDC-compliant identity provider (not only Keycloak and Azure EntraID), eliminating vendor lock-in
- Decouple user identity from agent identity, enabling enterprises to source each from separate, independent identity providers
- Reduce production deployment risk by providing a built-in super admin that works before OIDC is configured or when OIDC is unavailable
- Eliminate the need for operators to hand-edit configuration files by moving all OIDC settings to the database-backed system config UI
- Preserve the existing dev/demo setup wizard for low-friction development and evaluation environments

## Users & Personas

- **Platform Operator** — Deploys Parthenon in production; needs to configure user and agent identity providers through a secure UI without editing YAML files; needs a fallback super admin in case of OIDC misconfiguration
- **Dev/Demo User** — Evaluates Parthenon locally; needs a quick, guided setup wizard with a bundled Keycloak to get started in minutes
- **Security Administrator** — Manages enterprise identity boundaries; needs the ability to source user and agent identities from separate providers to maintain segregation of duties
- **End User (Human)** — Logs in via the configured user identity provider; expects seamless SSO
- **Agent Operator** — Manages agent identities; expects agent identity provider to function independently from user identity

## User Stories

- As a **platform operator**, I want to configure user and agent identity providers independently through a web UI, so that I can source human and agent identities from separate identity domains without editing config files.
- As a **platform operator**, I want a built-in super admin account that works regardless of OIDC status, so that I can always access the system to fix a misconfigured identity provider.
- As a **platform operator**, I want to test an OIDC configuration and attempt a login before committing it, so that I can validate connectivity and claims mapping without disrupting existing users.
- As a **platform operator**, I want to disable the super admin once OIDC authentication is confirmed working, so that all authentication flows through the identity provider in production.
- As a **dev/demo user**, I want to continue using the existing setup wizard with bundled Keycloak, so that I can evaluate Parthenon locally in minutes without any manual configuration.
- As a **security administrator**, I want to point user identity to our enterprise SSO (e.g., Azure EntraID) and agent identity to a separate provider, so that human access and machine identity remain governed independently.

## Acceptance Criteria

### Super Admin Bootstrap
- On first launch before OIDC is configured, a built-in super admin account is available for login with credentials configurable via the existing config system (overridable by env vars)
- Super admin can access the full platform UI (not limited to setup screens)
- Super admin credentials are never hardcoded — always sourced from config/env

### OIDC Provider Configuration in UI
- Super admin can navigate to the system config module and configure OIDC providers via a web form
- User identity provider and agent identity provider are configured as separate, independent entries
- Required fields follow standard OIDC discovery: issuer URL, client ID, client secret, and optional scopes/claims mapping
- OIDC configuration is persisted to the database (not a YAML file)
- The database-stored configuration is the source of truth for the Control Center's OIDC authentication

### Independent Identity Providers
- A single deployment can use one provider for both user and agent identity, or two different providers
- Changing the user identity provider does not affect agent identity authentication and vice versa
- Agent identity tokens continue to be managed centrally by Control Center and never exposed to agent runtimes

### OIDC Test & Login
- An operator can trigger a test OIDC connection from the UI to validate provider reachability and client credentials
- An operator can attempt a test login through the configured provider from the UI to verify the full authentication flow and claims response

### Super Admin Disablement
- An operator can disable the super admin account via a config setting or environment variable
- When super admin is disabled, the super admin login is refused even with correct credentials
- When super admin is disabled, only OIDC-authenticated users can access the platform

### Dev/Demo Setup Wizard (Preserved)
- On first launch with no OIDC configured and no super admin enabled, the existing setup wizard still appears
- Wizard continues to support bundled Keycloak or external OIDC (existing Keycloak/Azure EntraID flows)
- Wizard output is now saved to the database system config instead of `config/identity.yaml`

### Backward Compatibility
- Existing `config/identity.yaml` values are migrated to the database on upgrade (one-time migration)
- After migration, the database configuration takes precedence; the YAML file is no longer read

### Error Handling
- If a configured OIDC provider is unreachable, the platform shows a clear error on the login page (not a generic 500)
- If OIDC is configured but the super admin is disabled and OIDC is broken, platform provides clear guidance in logs and on the login page about how to re-enable the super admin

## Out of Scope

- Building an identity provider — Parthenon consumes existing OIDC providers, it does not become one
- Managing users, groups, or credentials inside the identity provider itself (those remain managed in the provider's own admin console)
- Multi-tenancy where different tenants use different identity providers simultaneously
- Just-in-time (JIT) user provisioning from OIDC claims (users must be pre-created or mapped via existing group claim mechanisms)
- OIDC provider health monitoring or alerting dashboards
- SAML or non-OIDC authentication protocols

## Dependencies & Constraints

- Requires a running OIDC-compliant identity provider accessible from the Parthenon deployment
- Super admin credentials must be securely stored and never logged
- Client secrets and sensitive OIDC configuration must be encrypted at rest in the database
- All changes must comply with the top-priority architecture rule: only Control Center connects to the database
- Agent identities must remain first-class OIDC principals with tokens resolved by Control Center and injected by Communication Hub
- Docker and Docker Compose remain required for the bundled Keycloak dev/demo flow
