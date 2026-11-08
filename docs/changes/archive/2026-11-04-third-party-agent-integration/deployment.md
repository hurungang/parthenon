# Deployment Notes: third-party-agent-integration

## Environment Variables

| Variable | Service | Purpose | Default |
|----------|---------|---------|---------|
| `INTEGRATION_GATEWAY_ENABLED` | Communication Hub | Enables the `/integrate/*` public gateway (chat, submit, widget, SDK) | `false` |
| `INTEGRATION_PUBLIC_BASE_URL` | Communication Hub | Public base URL used in embed snippets, origin checks, and SDK references | (none — required when enabled) |
| `INTEGRATION_CORS_ORIGINS` | Communication Hub | Deployment-level origin allowlist (defense in depth, on top of per-client origins) | (empty = reject all) |
| `INTEGRATION_RATE_LIMIT_REDIS_*` | Communication Hub | Redis connection for per-client rate-limit counters (`HOST/PORT/PASSWORD/DB`) | per-component Redis defaults |
| `INTEGRATION_SDK_CDN_BASE` | Communication Hub | Base URL advertised for SDK distribution (CDN/npm/pip) | `INTEGRATION_PUBLIC_BASE_URL` |

Per-client origins, rate limits, and white-label theming are database-backed (set via the client-management UI); the env vars above are edge defaults and the public URL/branding overrides.

## Infrastructure Changes

- **Communication Hub** gains the `/integrate/*` routes and widget/theme/SDK serving; enable via `INTEGRATION_GATEWAY_ENABLED`. Redis is required for rate-limit counters (reuse the existing instance; no new service).
- **Control Center** runs the Alembic migration adding the `agent_clients` and `agent_client_usage_logs` tables. No new service, no DB topology change.
- **nginx reverse proxy** — expose `POST /integrate/chat`, `POST /integrate/submit`, `GET /integrate/{client_ref}/config`, and `GET /integrate/sdk/*` publicly; keep `/api/v1/*` and `/internal/*` behind existing auth.
- **SDK distribution** — publish the JS SDK to npm (and/or a CDN bundle served by CH) and the Python SDK to PyPI, or serve both from CH's `/integrate/sdk/*` for self-hosted consumers.
- **Runnable dev example** — `examples/third-party-integration/` runs against a local Parthenon with no external dependencies.

## Migration Steps

1. Apply the migration: `cd backend && python -m alembic upgrade head` (adds `agent_clients` + `agent_client_usage_logs`).
2. Deploy Control Center (client models, service, endpoints, internal validation router).
3. Set `INTEGRATION_GATEWAY_ENABLED=true` and `INTEGRATION_PUBLIC_BASE_URL` on Communication Hub; restart backend services via `parthenon.ps1 restart -Services backend -Force` so certificates re-bootstrap correctly.
4. Configure the nginx public routes for `/integrate/*`.
5. Publish/serve the JS + Python SDKs and update `INTEGRATION_SDK_CDN_BASE`.
6. Verify the runnable example connects and both integration paths work end-to-end.

## Rollback Procedure

- **Application-level rollback** (no schema revert): set `INTEGRATION_GATEWAY_ENABLED=false` and remove the nginx `/integrate/*` routes. The MCP protocol server and REST skills endpoint are unaffected; clients simply have no public surface.
- **Database rollback**: run `python -m alembic downgrade -1` to drop the client tables. Client data is audit/access-grant only and may be exported before downgrade.
- **SDK rollback**: unpublish the SDK versions and revert `INTEGRATION_SDK_CDN_BASE`; existing embed snippets fail closed (widget asset 404s), never silently exposing data.

## Master Deployment Update Instructions

- **`docs/master/deployment/environment-variables.md`** — add the `INTEGRATION_*` variables table above.
- **`docs/master/deployment/services.md`** — note the Communication Hub integration gateway and its public `/integrate/*` routes, and the Redis rate-limit counter dependency.
- **`docs/master/deployment/configuration-files.md`** — document the nginx public route additions and origin handling.
- **`docs/master/deployment/database-migrations.md`** — add the third-party-integration migration to the history.
- **`docs/master/deployment/first-time-deployment.md`** — add optional integration-gateway enablement to the first-run guide.
