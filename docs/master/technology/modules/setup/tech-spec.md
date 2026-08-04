# Module: setup — Tech Spec

## Overview

The setup module provides a unified CLI tool for all environment bootstrapping tasks in the Parthenon platform. It consolidates the identity provider provisioning, database seeding, certificate authority initialization, and development environment setup into a single, idempotent operator-invoked command. The setup tool is distinct from the runtime application containers — it is an operator tool, not a runtime service. It operates independently of running services, directly accessing Keycloak Admin REST API, PostgreSQL, and the certificate authority storage layer during bootstrapping.

Each sub-command is idempotent: running it on an already-initialized environment detects existing state and reports it without side effects. Built-in help (`--help`) documents all options.

---

## Key Components

### Setup CLI (`setup/`)

| Component | Description |
|-----------|-------------|
| `main` (setup) | Consolidated setup CLI entry point with sub-commands: `identity`, `database`, `certificates`, `dev`, `verify` |
| `run_identity_setup` | Provisions Keycloak realms, OIDC clients, roles, and admin user via direct Keycloak Admin REST API access |
| `run_database_setup` | Verifies PostgreSQL readiness, then seeds system roles, permissions, skills, and system tools |
| `run_certificates_setup` | Bootstraps the certificate authority (generates or loads root CA certificate) |
| `run_dev_setup` | Full development environment bootstrap: runs identity + database + certificates setup in sequence |
| `run_verify` | Checks the current state of all components without making any changes; reports what is configured and what is missing |

### Relation to Backend CLI

| Component | Description |
|-----------|-------------|
| `main` (Backend CLI) | Backend CLI entry point (`backend/app/cli.py`) with `setup-identity` and `seed-skills` sub-commands; these remain available for backward compatibility but delegate to the consolidated setup tool where applicable |

---

## Commands

| Command | Purpose | Idempotent |
|---------|---------|------------|
| `python -m setup.main identity` | Provisions Keycloak realms, clients, roles, admin user | Yes — detects existing realm and reports |
| `python -m setup.main database` | Verifies DB readiness, seeds roles, permissions, skills, system tools | Yes — detects existing state |
| `python -m setup.main certificates` | Bootstraps certificate authority | Yes — detects existing CA |
| `python -m setup.main dev` | Full dev bootstrap: identity + database + certificates | Yes — each step is independently idempotent |
| `python -m setup.main verify` | Checks current state of all components without changes | Read-only, always safe |
| `python -m setup.main --help` | Shows all available sub-commands and options | N/A |

---

## Data Access Patterns

The setup tool does not use any runtime service endpoints. It directly accesses:
- **Keycloak Admin REST API** — for realm, client, and user provisioning (authenticated with admin credentials from environment variables)
- **PostgreSQL** — for database seeding of roles, permissions, skills, and system tools
- **Certificate authority storage** — for CA bootstrapping (generating or loading root CA certificate)

The setup tool reads Keycloak admin credentials from environment variables (`KEYCLOAK_ADMIN_USER`, `KEYCLOAK_ADMIN_PASSWORD`) and discards them after use. These credentials are never available to the runtime Control Center.

---

## Security

- Keycloak admin credentials are only consumed by the setup tool — the runtime Control Center never has access to them
- Idempotent operations prevent accidental duplicate provisioning or data corruption
- The `verify` command is read-only and safe to run at any time, even in production

---

## Code Reference Map

### Setup CLI (`setup/`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `main` | function | Consolidated setup CLI entry point with sub-commands (`identity`, `database`, `certificates`, `dev`, `verify`) | `setup/main.py` |
| `run_identity_setup` | function | Provisions Keycloak realms, OIDC clients, roles, admin user via Keycloak Admin REST API | `setup/identity.py` |
| `run_database_setup` | function | Verifies PostgreSQL readiness; seeds system roles, permissions, skills, system tools | `setup/database.py` |
| `run_certificates_setup` | function | Bootstraps certificate authority (generates or loads root CA) | `setup/certificates.py` |
| `run_dev_setup` | function | Full dev bootstrap: runs identity + database + certificates setup in sequence | `setup/dev.py` |
| `run_verify` | function | Checks current state of all components without making changes; reports configured/missing | `setup/verify.py` |

### Backend CLI (backward compatibility)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `main` (CLI) | function | Backend CLI entry point; `setup-identity` and `seed-skills` sub-commands retained for backward compatibility | `backend/app/cli.py` |
| `_run_setup_identity` | function | Executes identity bootstrap via CLI; delegates to consolidated setup tool | `backend/app/cli.py` |
| `_run_seed_skills` | function | Executes skill seeder via CLI | `backend/app/cli.py` |

### Deprecated Scripts

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `LocalDevInitializer` | class | **DEPRECATED** — former dev environment initializer; consolidated into setup tool as `setup dev` | `scripts/init-local-dev.py` |
| `initialize` | method | Full initialization sequence (dev mode); replaced by `setup dev` | `scripts/init-local-dev.py` |

### Identity Bootstrap (called by setup)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `IdentityBootstrapService` | class | Orchestrates full identity provider setup for bundled Keycloak and external OIDC; called by `setup identity` | `backend/app/services/identity/bootstrap_service.py` |
| `RealmManager` | class | Manages agent realm lifecycle in Keycloak — create, validate, apply token policies; `initialize_agent_realm` called exclusively by setup tool | `backend/app/services/identity/realm_manager.py` |
| `KeycloakAdminClient` | class | Low-level Keycloak Admin REST API client — authenticate, create realms/clients/users | `backend/app/services/identity/keycloak_admin_client.py` |

### Bootstrap Services (called by setup)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `BootstrapService` | class | Seeds system roles and permission policies (runtime also calls this at startup) | `backend/app/services/permissions/bootstrap_service.py` |
| `SkillSeeder` | class | Idempotently seeds default platform skills | `backend/app/services/skill_seeder.py` |
| `initialize_ca` | function | Generates or loads root CA certificate | `backend/app/services/certificate_authority.py` |

### YAML Config (used during setup)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `OIDCConfigService` | class | CRUD service for `IdentityProviderConfig` DB records — used by bootstrap service | `backend/app/services/oidc_config_service.py` |
