# Spec Delta: Refine OIDC Integration

## Affected Spec Areas

- **Foundation Platform** (`docs/master/product/features/foundation-platform.md`) — Core auth, login flow, super admin role
- **Keycloak Identity Bootstrap** (`docs/master/product/features/keycloak-identity-bootstrap.md`) — Setup wizard, bundled Keycloak, external provider flow
- **Identity Provider Setup** (`docs/master/product/features/identity-provider-setup.md`) — Group membership mapper provisioning, identity config storage
- **Agent Identity Management** (`docs/master/product/features/agent-identity.md`) — Agent identity provider independence, token lifecycle
- **Control Center** (`docs/master/product/features/control-center.md`) — OIDC configuration management, database-backed config

## New Capabilities

### 1. Built-in Super Admin
- A platform-internal administrative account that authenticates independently of any OIDC provider
- Credentials sourced from the existing config system with environment variable override
- Provides guaranteed administrative access for bootstrap and disaster recovery
- Accessible on the standard login page alongside the OIDC login option (when enabled)
- Full platform access (all modules, all admin functions)

### 2. UI-Based OIDC Provider Configuration
- System config module in the web UI where operators configure OIDC identity providers
- Separate configuration forms for user identity provider and agent identity provider
- Configuration fields: issuer URL, client ID, client secret, authorization endpoint, token endpoint, JWKS URI, scopes, claims mapping
- All configuration persisted to the database as system config records
- Replaces static `config/identity.yaml` as the source of truth

### 3. Independent User and Agent Identity Providers
- User identity provider and agent identity provider are separate, independently configurable entities
- A deployment can use the same provider for both, or different providers
- Each provider has its own OIDC client registration, claims mapping, and token validation
- Changes to either provider do not affect the other

### 4. OIDC Configuration Testing
- "Test Connection" action: validates provider reachability and client credentials without performing a full login
- "Test Login" action: initiates a real OIDC login flow from the UI so the operator can verify the full authentication and claims response
- Test results displayed inline in the system config UI with pass/fail indicators and diagnostic messages

### 5. Super Admin Enable/Disable Toggle
- Super admin account can be disabled via a configuration setting
- Environment variable override takes precedence: `PARTHENON_SUPER_ADMIN_ENABLED=true|false`
- When disabled, super admin login is rejected; only OIDC-authenticated users can access the platform
- Disablement requires at least one working OIDC provider to be configured (guard rail)

## Modified Capabilities

### Setup Wizard

| Aspect | Before | After |
|--------|--------|-------|
| Trigger | First launch with no `config/identity.yaml` | First launch with no OIDC config in database and no super admin enabled |
| Provider options | Bundled Keycloak, external Keycloak, Azure EntraID | Bundled Keycloak, external OIDC (any provider) |
| Config storage | Writes `config/identity.yaml` | Writes to database system config |
| Dual-identity support | None (single provider for both) | Optionally configures separate user and agent providers |

### Identity Provider Support

| Aspect | Before | After |
|--------|--------|-------|
| Supported providers | Keycloak, Azure EntraID (hardcoded) | Any OIDC-compliant provider (discovery-driven) |
| Provider configuration | Static YAML file (`config/identity.yaml`) | Database-backed system config via web UI |
| Custom claims mapping | Not configurable | Configurable per provider via UI |
| Provider coupling | Single provider for user + agent | Independent providers for user and agent |

### Authentication Flow

| Aspect | Before | After |
|--------|--------|-------|
| Login page | OIDC redirect button only | OIDC redirect button + super admin credential login (when enabled) |
| Fallback auth | None (if OIDC down, platform inaccessible) | Super admin credential login (if enabled) |
| Auth config source | `config/identity.yaml` | Database system config |

### Agent Identity

| Aspect | Before | After |
|--------|--------|-------|
| Identity provider | Same as user identity provider | Independent agent identity provider |
| Provider config | Shared with user identity | Separate config, separate client, separate realm |
| Token management | Control Center manages all tokens | Control Center manages tokens from agent-specific provider |

## Removed Capabilities

- **`config/identity.yaml` as source of truth** — The YAML file is deprecated. On upgrade, existing values are migrated to the database. After migration, the YAML file is no longer read. Operators no longer hand-edit identity configuration files.

## Spec Update Instructions

### `docs/master/product/features/keycloak-identity-bootstrap.md`
- Update Epic Overview to note that the wizard now writes to database system config, not `config/identity.yaml`
- Add acceptance criteria for the wizard supporting any external OIDC provider (not just Keycloak/Azure EntraID)
- Add note about optional independent agent identity provider configuration during wizard flow
- Update "Out of Scope" to reflect broader OIDC support

### `docs/master/product/features/identity-provider-setup.md`
- Rename or reframe from Keycloak-specific group mapper to general OIDC claims mapping
- Add section on UI-based provider configuration replacing YAML file
- Document the one-time migration path from `config/identity.yaml` to database

### `docs/master/product/features/foundation-platform.md`
- Add super admin capability: bootstrap, access scope, enable/disable lifecycle
- Add dual-provider auth flow: user identity provider + agent identity provider
- Update authentication architecture description to include database-backed OIDC config
- Document OIDC provider testing capability

### `docs/master/product/features/agent-identity.md`
- Add section on agent identity provider independence (separate from user identity provider)
- Update token management description to reference agent-specific OIDC provider

### `docs/master/product/features/control-center.md`
- Add system config module: OIDC provider configuration management
- Add super admin management capability

### `docs/master/product/README.md`
- Update Foundation Platform feature description to reflect broadened OIDC support and super admin
