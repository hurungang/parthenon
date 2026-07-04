# Deployment Documentation — Parthenon Enterprise AI Harness

This section contains all deployment documentation for the Parthenon platform. Guides cover both supported deployment targets and reference material for environment configuration and service inventory.

---

## Deployment Targets

| Target | Guide | Use Case |
|--------|-------|----------|
| Docker Compose (self-hosted) | [First-Time Deployment](first-time-deployment.md) | Local development, internal self-hosted deployments |
| Kubernetes / Helm (production) | [First-Time Deployment](first-time-deployment.md) | Enterprise production deployments with HA and autoscaling |
| GitHub Pages | [GitHub Pages Project Showcase](github-pages-showcase.md) | Static showcase site published via GitHub Actions (independent of main app stack) |

---

## Contents

| Document | Description |
|----------|-------------|
| [first-time-deployment.md](first-time-deployment.md) | Ordered step-by-step runbook for the initial deployment of a fresh Parthenon instance |
| [environment-variables.md](environment-variables.md) | Master reference table of all environment variables for every service; update whenever new services are added or variables change |
| [services.md](services.md) | Master inventory of all containers and pods with their roles; update whenever services are added, removed, or renamed |
| [operational-runbooks.md](operational-runbooks.md) | Targeted runbooks for specific operational tasks including permission rollout, service-segregation allowlist cutover, deny-event triage, and certificate failure response |
| [rollback.md](rollback.md) | Runbook for rolling back a failed deployment to the last known-good state, including service-segregation policy rollback sequence |
| [configuration-files.md](configuration-files.md) | Reference for platform-managed configuration files (e.g., `config/telemetry.yaml`); covers resolution order, Docker Compose bind-mounts, and Kubernetes ConfigMap mounting |
| [database-migrations.md](database-migrations.md) | Chronological log of all Alembic migration revisions applied to production; update whenever a migration is promoted |
| [github-pages-showcase.md](github-pages-showcase.md) | Deployment guide for the GitHub Pages static showcase site — trigger, setup, rollback, and custom domain configuration |

---

## Service-Segregation Security Rollout Order

Use this sequence for caller-specific internal API allowlist deployment:

1. Confirm required variables and secrets in [environment-variables.md](environment-variables.md)
2. Validate caller/service boundary expectations in [services.md](services.md)
3. Execute audit-to-enforce operational procedure in [operational-runbooks.md](operational-runbooks.md)
4. If cutover issues occur, execute the rollback sequence in [rollback.md](rollback.md)

---

## Agent Execution Guardrails Rollout Order

Use this sequence for `add-agent-execution-guardrails` and subsequent guardrail updates:

1. Confirm guardrail variables and required flags by service in [environment-variables.md](environment-variables.md)
2. Confirm service responsibility boundaries and rollout order in [services.md](services.md)
3. Execute post-deploy guardrail verification checklist in [operational-runbooks.md](operational-runbooks.md)
4. If rollout instability is detected, execute guardrail rollback sequence in [rollback.md](rollback.md)

### Rollout prerequisites

- Guardrail contract-compatible versions are prepared for Control Center, Communication Hub, and Agent Runtime.
- Required guardrail environment variables are configured before cutover.
- Guardrail threshold defaults and token fallback policy are approved for the environment.

### Verification expectations

- Guardrail outcomes are classified clearly (cycle detection, cumulative iteration, timeout, delegation depth/steps, token budget/fallback).
- Conversational token usage is continuously visible and continuation behavior is preserved.
- Guardrail metadata is preserved and persisted across direct and delegated execution paths.

---

## Quick Reference

- **Infrastructure dependencies**: PostgreSQL 16 and Redis must be healthy before any backend service starts. When `IDENTITY_PROVIDER_TYPE=keycloak_bundled`, the bundled Keycloak container is also an infrastructure dependency and must be healthy before the Platform API starts. Ensure host port `8080` is free before starting the stack in bundled mode.
- **Startup order**: Platform API must be up before MCP Hub, Skill Engine, Agent Engine, Scheduling Engine, Notification Engine, Communication Hub, and Agent Gateway
- **Secrets management**: All sensitive environment variables must be supplied via Docker secrets (Docker Compose) or Kubernetes Secrets — never in plain-text configuration files
- **Migrations**: Alembic migrations in `backend/alembic/` must be applied against the database before the Platform API starts
- **OIDC**: For bundled Keycloak, the Bootstrap Service provisions the realm and client automatically via the setup wizard or CLI — do not register clients manually. For external providers (Keycloak or Azure EntraID), manual client registration is required before running the setup wizard or CLI.
- **Identity configuration file**: `config/identity.yaml` is written automatically by the setup wizard or CLI and serves as the secondary configuration source for resolved OIDC settings. Environment variables always take precedence over values in this file. The file is safe to commit to source control — client secrets are never written to it.
