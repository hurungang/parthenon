# Deployment: MCP Protocol Server

> Protocol/transport change on the Communication Hub (CH). **No database migration**, no new services/ports. One Control Center internal endpoint is extended but backward-compatible.

## 1. Environment Variables

### New Environment Variables

| Variable | Service | Description | Secret | Default |
|----------|---------|-------------|--------|---------|
| `CH_MCP_PROTOCOL_SERVER_ENABLED` | CH | Feature flag to enable the standard MCP protocol endpoint (SSE + Streamable HTTP). When `false`, the endpoint is not registered and the existing REST `/mcp/tools/load_skills` + internal mTLS paths remain exactly as today. | — | `false` |

### Prerequisite Variables (Unchanged)

The MCP protocol server reuses the existing API-key authentication path. These variables must already be in place:

| Variable | Service | Role in MCP Protocol Flow |
|----------|---------|---------------------------|
| `CH_API_KEY_AUTH_ENABLED` | CH | Must be `true` — MCP protocol sessions authenticate via the existing API-key middleware. Documented in `docs/changes/archive/2026-07-31-api-key-mcp-hub/deployment.md`. |
| `API_KEY_HASH_SECRET` | CC | Already set; used when CC validates the hashed API key during the MCP handshake — no change. |
| `CONTROL_CENTER_URL` | CH | Already set; CH calls CC `validate-api-key`, `skills/resolve`, and `mcp/proxy-tool` over mTLS — no change. |
| `SERVICE_BOOTSTRAP_KEY` | CH | Already set; CH→CC certificate bootstrap — no change. |
| `CREDENTIAL_VAULT_KEY` | CC | Already set; decrypts the bound identity token at call time during proxying — no change. |

### Deployment Checklist

Before enabling:
- Confirm `CH_API_KEY_AUTH_ENABLED=true` on the Communication Hub (the MCP protocol endpoint authenticates exclusively via API keys).
- Leave `CH_MCP_PROTOCOL_SERVER_ENABLED=false` for the initial deploy to verify the dependency loads and the Hub starts cleanly, then flip it on after smoke-testing.
- Verify the `mcp` Python dependency installs in the CH image (see Infrastructure Changes).

---

## 2. Infrastructure Changes

### No New Services, Ports, or Volumes

No new containers, pods, networks, or ports are introduced. This change extends the existing Communication Hub only.

### New Python Dependency

- **`mcp>=1.1.2`** added to `backend/pyproject.toml` (runtime dependencies) and locked in `backend/uv.lock`. Provides the official MCP SDK protocol types, `Server`, and transport primitives. Pulls in transitive dependencies; regenerate `backend/uv.lock` and rebuild the CH image before deploy.

### New CH MCP Endpoint Paths (gated by the flag)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/mcp` | Streamable HTTP — JSON-RPC `initialize` / `tools/list` / `tools/call` |
| `GET` | `/mcp/sse` | SSE event stream |
| `POST` | `/mcp/sse/messages` | SSE message posting |

All three are served by the existing Communication Hub (port 8002) and fronted by the existing API-key middleware (Bearer header or `?apiKey=` query). When the flag is off, none of these paths are registered.

### Communication Hub Changes

- New `backend/app/communication_hub/mcp/` package: protocol server, session manager, Streamable HTTP + SSE transports, and the tool registry bridge (per `tech-spec.md`).
- `ApiKeyAuthMiddleware` now also fronts the MCP protocol endpoint (reused, not reimplemented).

### Control Center Changes

- `POST /api/v1/internal/mcp/proxy-tool` is **extended** to resolve an MCP session from an agent role + identity (what an API key yields) in addition to the existing agent-type path. Backward-compatible — the existing agent-type call path is unchanged.

### Database Changes

**None.** No schema changes, no new tables, no data backfill.

---

## 3. Migration Steps

Deploy in the following order. Each step must complete before the next.

### Step 1 — Build the Updated Communication Hub Image with the `mcp` Dependency

1. Regenerate `backend/uv.lock` so the pinned graph includes `mcp` and its transitive deps.
2. Rebuild the `communication-hub` image so `mcp` is installed.
3. Verify the SDK imports in the CH environment (`from mcp.server import Server; from mcp import types`) succeed.

### Step 2 — Confirm API-key Authentication Prerequisite

- Verify `CH_API_KEY_AUTH_ENABLED=true` on the Communication Hub. If not already enabled, follow `docs/changes/archive/2026-07-31-api-key-mcp-hub/deployment.md` first (including creating an API key for a test agent identity/role).
- Verify `API_KEY_HASH_SECRET` is set on Control Center (API keys were already being validated).

### Step 3 — Deploy with the Flag Off (Audit Mode)

1. Set `CH_MCP_PROTOCOL_SERVER_ENABLED=false` on the Communication Hub.
2. Restart the backend stack in the mandated order via `parthenon.ps1` — `infra → control-center → agent-runtime → communication-hub → frontend` (start order matters; CH/AR depend on CC for certificate bootstrap).
3. Confirm `/health` responds and startup logs show the flag value and that `log_config_sources()` reports `CH_MCP_PROTOCOL_SERVER_ENABLED`.
4. Confirm the MCP protocol paths are **not** served (404) and the existing REST `/mcp/tools/load_skills` still works.

### Step 4 — Enable the MCP Protocol Endpoint

1. Set `CH_MCP_PROTOCOL_SERVER_ENABLED=true` on the Communication Hub.
2. Restart the Communication Hub (or restart `backend` via `parthenon.ps1` so CH rebootstrap certificates against CC correctly).
3. Verify startup logs show the flag enabled and the MCP protocol router registered.

### Step 5 — Smoke Test

1. Point an MCP client (or a standard MCP SDK client) at the CH endpoint with a valid API key (Bearer or `?apiKey=`).
2. Complete `initialize`, then `tools/list` — confirm permitted system tools (incl. `load_skills`) and proxied MCP tools appear.
3. Invoke a permitted tool via `tools/call` — confirm a result returns.
4. Verify permission filtering: a tool outside the bound role is absent from `tools/list` and rejected on `tools/call`.
5. Verify `load_skills` returns skills with `updated_at` timestamps, and honors the `since` parameter.
6. Confirm an invalid/revoked key yields a clear authentication error.
7. Confirm no regression: internal Agent Runtime mTLS path and REST `load_skills` still work.

---

## 4. Rollback Procedure

### Trigger Conditions

- CH fails to start or the `mcp` dependency causes import errors.
- MCP protocol endpoint behaves incorrectly (handshake, listing, or calls fail).
- Regression in the existing REST `load_skills` endpoint or internal mTLS tool path.

### Step R1 — Disable the Feature Flag

1. Set `CH_MCP_PROTOCOL_SERVER_ENABLED=false` on the Communication Hub.
2. Restart only the Communication Hub (`parthenon.ps1 restart -Services communication-hub -Force`).
3. Confirm the MCP protocol paths are no longer served and existing REST + mTLS paths are back to normal.

> This is the primary rollback — no data, schema, or state is removed. The feature is a transport layer; disabling the flag returns the Hub to its pre-change surface.

### Step R2 — Revert the Dependency (Conditional)

Only if the `mcp` package itself causes import/startup problems after Step R1:

1. Revert `backend/pyproject.toml` to remove `mcp>=1.1.2`.
2. Regenerate `backend/uv.lock`.
3. Rebuild the previous CH image and redeploy, restarting the backend stack in standard order.

### Step R3 — Validate Rollback

1. Confirm all service `/health` endpoints respond.
2. Verify internal Agent Runtime (mTLS cert) MCP connections work — connect, discover skills, invoke a tool.
3. Verify REST `GET/POST /mcp/tools/load_skills` still works with an API key.
4. Confirm the Web UI loads and API-key/role/MCP-server management pages function normally.

### Rollback Guardrails

- No database migration exists — **never** run `alembic downgrade` for this change; there is nothing to reverse.
- Do not leave `CH_MCP_PROTOCOL_SERVER_ENABLED=true` after rollback — set it `false` (or remove it) to avoid accidental re-enable on the next CH restart.
- `CH_API_KEY_AUTH_ENABLED` is a **separate, pre-existing** flag — leave it unchanged during this rollback.
- Control Center's extended `proxy-tool` endpoint is backward-compatible; it can remain deployed with no client change.

---

## 5. Master Deployment Update Instructions

After this change is implemented and verified, update `docs/master/deployment/`:

### `docs/master/deployment/environment-variables.md`

- Add a row for `CH_MCP_PROTOCOL_SERVER_ENABLED` (CH, feature flag, default `false`) under a new "MCP Protocol Server" subsection (or under the existing Communication Hub section, adjacent to `CH_API_KEY_AUTH_ENABLED`).
- Note the dependency: enabling the MCP protocol endpoint requires `CH_API_KEY_AUTH_ENABLED=true`.

### `docs/master/deployment/services.md`

- Update the Communication Hub row in the Service Inventory table: CH now exposes a standard MCP protocol endpoint (`POST /mcp`, `GET /mcp/sse`, `POST /mcp/sse/messages`) in addition to the REST `/mcp/tools/load_skills` endpoint, authenticated by API keys.
- Extend the Control Center internal API boundary note: `POST /api/v1/internal/mcp/proxy-tool` now also accepts role + identity session resolution (in addition to agent type). No new callers are introduced.

### `docs/master/deployment/first-time-deployment.md`

- Note that `CH_MCP_PROTOCOL_SERVER_ENABLED` defaults to `false` on first deployment and may be enabled after API-key auth is verified.

### `docs/master/deployment/rollback.md`

- Add a "Change-Specific Rollback: MCP Protocol Server" section: trigger conditions (CH startup failure, protocol misbehavior, REST/mTLS regression), Steps R1–R3 from Section 4, and the guardrails (no DB downgrade, keep `CH_API_KEY_AUTH_ENABLED` unchanged).

### No updates needed for

- `database-migrations.md` — No schema change; no migration row.
- `configuration-files.md` — No new configuration files introduced.
- `github-pages-showcase.md` — No showcase change.
