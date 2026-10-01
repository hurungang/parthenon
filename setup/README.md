# Parthenon Setup Tool

Operator-invoked CLI for environment bootstrapping. This directory is separate from the runtime application (`backend/app/`) and should never be included in Docker images or deployed artifacts.

## Quick Start

```shell
# Full local development bootstrap
python -m setup.main dev

# Individual steps
python -m setup.main identity           # Provision Keycloak realms & clients
python -m setup.main database           # Seed roles, permissions, skills
python -m setup.main certificates       # Bootstrap certificate authority
python -m setup.main verify             # Check current state (read-only)

# JSON output for scripting
python -m setup.main dev --output json
```

## Sub-commands

| Command | Description |
|---------|-------------|
| `identity` | Provision Keycloak user/agent realms, OIDC clients, and admin user. With `--tenant-demo` (opt-in): seed a demo tenant realm instead |
| `database` | Seed system roles, permissions, skills, and system tools |
| `certificates` | Generate/load root CA certificate for mTLS |
| `dev` | Full dev bootstrap: identity → database → certificates |
| `verify` | Read-only state check (does not modify anything) |

## Environment Variables

All sub-commands read from `.env` and environment variables. Key variables:

- `KEYCLOAK_URL` — Keycloak base URL (default: `http://localhost:8082`)
- `KEYCLOAK_REALM` — User realm name (default: `parthenon`)
- `KEYCLOAK_ADMIN_USER` / `KEYCLOAK_ADMIN_PASSWORD` — Master realm admin credentials
- `INITIAL_ADMIN_PASSWORD` — Password for the initial admin user
- `KEYCLOAK_TENANT_DEMO_REALM` — Demo tenant realm name for `identity --tenant-demo` (default: `parthenon-acme`)
- `DATABASE_URL` — PostgreSQL connection URL
- `BOOTSTRAP_ADMIN_EMAIL` — Email of admin user to assign system_admin role

## Idempotency

All operations are idempotent. Running `setup dev` twice will detect existing configuration and report what was skipped — no errors will be raised for resources that already exist.

## Demo tenant realm (opt-in)

For testing per-tenant OIDC in isolation (multi-tenancy ON), seed a dedicated
demo realm alongside the main one. This is **not** part of the `dev` bootstrap:

```shell
python -m setup.main identity --tenant-demo                 # realm: parthenon-acme
python -m setup.main identity --tenant-demo --tenant-demo-realm acme
```

Provisions, idempotently:
- a separate realm (default `parthenon-acme`),
- a public frontend client (`<client-id>-ui`) mirroring the main realm's UI client redirect URIs,
- demo users `acme-admin` / `acme-user` (passwords match the usernames).

After the run the tool prints the issuer URL to configure per-tenant in
Parthenon (System Config → Identity Providers, scoped to the tenant, or the
tenant settings), the test credentials, and a reminder to set the provider's
default tenant role if JIT onboarding is wanted.
