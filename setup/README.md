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
| `identity` | Provision Keycloak user/agent realms, OIDC clients, and admin user |
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
- `DATABASE_URL` — PostgreSQL connection URL
- `BOOTSTRAP_ADMIN_EMAIL` — Email of admin user to assign system_admin role

## Idempotency

All operations are idempotent. Running `setup dev` twice will detect existing configuration and report what was skipped — no errors will be raised for resources that already exist.
