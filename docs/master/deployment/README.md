# Deployment Documentation — Parthenon Enterprise AI Harness

This section contains all deployment documentation for the Parthenon platform. Guides cover both supported deployment targets and reference material for environment configuration and service inventory.

---

## Deployment Targets

| Target | Guide | Use Case |
|--------|-------|----------|
| Docker Compose (self-hosted) | [First-Time Deployment](first-time-deployment.md) | Local development, internal self-hosted deployments |
| Kubernetes / Helm (production) | [First-Time Deployment](first-time-deployment.md) | Enterprise production deployments with HA and autoscaling |

---

## Contents

| Document | Description |
|----------|-------------|
| [environment-variables.md](environment-variables.md) | Master reference table of all environment variables for every service; update whenever new services are added or variables change |
| [configuration-files.md](configuration-files.md) | Reference for platform-managed configuration files (e.g., `config/telemetry.yaml`); covers resolution order, Docker Compose bind-mounts, and Kubernetes ConfigMap mounting |
| [services.md](services.md) | Master inventory of all containers and pods with their roles; update whenever services are added, removed, or renamed |
| [database-migrations.md](database-migrations.md) | Chronological log of all Alembic migration revisions applied to production; update whenever a migration is promoted |
| [first-time-deployment.md](first-time-deployment.md) | Ordered step-by-step runbook for the initial deployment of a fresh Parthenon instance |
| [rollback.md](rollback.md) | Runbook for rolling back a failed deployment to the last known-good state |
| [operational-runbooks.md](operational-runbooks.md) | Targeted runbooks for specific operational tasks: Permission Engine mode toggling, audit → enforce rollout pattern, role seeding, and latency monitoring |

---

## Quick Reference

- **Infrastructure dependencies**: PostgreSQL 16 and Redis must be healthy before any backend service starts. When `IDENTITY_PROVIDER_TYPE=keycloak_bundled`, the bundled Keycloak container is also an infrastructure dependency and must be healthy before the Platform API starts. Ensure host port `8080` is free before starting the stack in bundled mode.
- **Startup order**: Platform API must be up before MCP Hub, Skill Engine, Agent Engine, Scheduling Engine, Notification Engine, Communication Hub, and Agent Gateway
- **Secrets management**: All sensitive environment variables must be supplied via Docker secrets (Docker Compose) or Kubernetes Secrets — never in plain-text configuration files
- **Migrations**: Alembic migrations in `backend/alembic/` must be applied against the database before the Platform API starts
- **OIDC**: For bundled Keycloak, the Bootstrap Service provisions the realm and client automatically via the setup wizard or CLI — do not register clients manually. For external providers (Keycloak or Azure EntraID), manual client registration is required before running the setup wizard or CLI.
- **Identity configuration file**: `config/identity.yaml` is written automatically by the setup wizard or CLI and serves as the secondary configuration source for resolved OIDC settings. Environment variables always take precedence over values in this file. The file is safe to commit to source control — client secrets are never written to it.
