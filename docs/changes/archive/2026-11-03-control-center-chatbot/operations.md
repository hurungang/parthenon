# Operations Notes: Control Center Assistant (Chatbot)

A conversational "Control Center Assistant" that performs Agents-menu management tasks (create / update / configure / read of skills, SOPs, agent types, roles, identities, model configurations, schedules, MCP Hub connections, data types) on behalf of the logged-in user, strictly within that user's own permission scope. It is a **delegated actor** — never elevated, never deleting. Its management actions are **MCP tools** exposed on the Communication Hub MCP protocol server (`/mcp`) and authenticated via **OAuth/OIDC** (the user's Bearer token). The same surface and the same permission resolution serve both the in-app chatbot and any external MCP client the user connects with their own OAuth credentials.

## 1. Monitoring

New metrics to instrument on Control Center (the sole DB owner and enforcer), following the existing `parthenon_cc_*` / `internal_*` counter conventions:

- **Delegated-action audit volume** — `internal_management_tool_calls_total` (labels: `tool_name`, `outcome`) — every assistant management-tool call, by outcome (`success`, `permission_denied`, `scope_rejected`, `delete_rejected`, `error`).
- **Permission-denial rate** — `internal_management_tool_permission_denials_total` (labels: `tool_name`, `resource_type`, `reason`) — assistant attempts the user cannot authorize; sustained non-zero rate signals mis-scoped roles/grants.
- **Delete-rejection events** — `internal_management_tool_delete_rejections_total` (labels: `tool_name`) — all in-band delete attempts declined (expected to be low; a spike suggests misuse or a scope-regression in the assistant).
- **Out-of-scope rejections** — `internal_management_tool_scope_rejections_total` (labels: `tool_name`, `requested_scope`) — requests outside the Agents-menu / MCP Hub management scope.
- **Tool-call latency** — `internal_management_tool_duration_seconds` (p99, labels: `tool_name`) — end-to-end handler time (authorize + persist); rising p99 indicates CC/DB pressure.
- **OAuth identity-resolution failures** — `internal_management_tool_identity_resolution_failures_total` — fail-closed cases where the OAuth Bearer identity could not resolve to a `PlatformUser`; any non-zero rate needs triage.
- **MCP auth rejections** — `mcp_oauth_auth_rejections_total` (labels: `reason` — `missing_token`, `invalid_token`, `expired_token`, `unknown_identity`) — OAuth/OIDC Bearer-token rejections at the MCP protocol server.
- **Assistant seed health** — `assistant.seed.success` / `assistant.seed.skipped` / `assistant.seed.failed` — idempotent `AssistantSeeder` outcome at startup; `failed` means the assistant is unavailable.

Alerts to configure:

| Alert | Condition | Severity | Action |
|-------|-----------|----------|--------|
| `AssistantPermissionDenialSpike` | `rate(internal_management_tool_permission_denials_total) > baseline` for 5 min | Warning | Review the authenticated user's role/`agent::*` grants; distinguish user-scope denials from parity-map regression |
| `AssistantIdentityResolutionFailure` | `rate(internal_management_tool_identity_resolution_failures_total) > 0` for 2 min | Critical | Fail-closed enforcement is rejecting valid actions; see Common Issues §2 |
| `McpOAuthAuthRejectionSpike` | `rate(mcp_oauth_auth_rejections_total) > baseline` for 5 min | Warning | Investigate token issuer/clock-skew/identity-provisioning problems; see Common Issues §1 |
| `AssistantDeleteRejectionSurge` | `rate(internal_management_tool_delete_rejections_total) > baseline` for 5 min | Warning | Investigate for misuse or an assistant instruction regression (deletion is never supported) |
| `AssistantSeedFailed` | `assistant.seed.failed` present at startup | Critical | Assistant agent type/tools missing; see Common Issues §3 |

Dashboard addition: add a **Control Center Assistant** panel group (or extend the existing Agent Runtime / Service Segregation Boundary dashboards) with delegated-action volume by outcome, permission-denial rate by resource type, delete-rejection count, tool latency p99, OAuth identity-resolution failure count, and MCP auth rejection rate.

## 2. Logging

What is logged and where to find it — all backend logs live in `backend/logs/` (rotated at ~10 MB, `.1`/`.2` kept).

| Concern | Log file | What to look for |
|---------|----------|------------------|
| Management-tool execution (create/update/read) | `backend/logs/control-center.log` | Proposed events `management_tool.*`: `call_allowed`, `call_failed`, and the handler outcome per tool |
| Permission decisions | `backend/logs/control-center.log` | `management_tool.permission_denied` / `scope_rejected` / `delete_rejected` — carries `tool_name`, `resource_type`, `action`, `subject` |
| OAuth identity resolution | `backend/logs/control-center.log` | `management_tool.identity_resolution_failed` — fail-closed; no write performed |
| MCP auth (OAuth Bearer) | `backend/logs/communication-hub.log` | `mcp.oauth.*` (`authenticated`, `rejected`) — token validation outcomes at the MCP protocol server |
| Assistant seed | `backend/logs/control-center.log` | `assistant.seed.*` (`success`/`skipped`/`failed`) at startup |
| Assistant conversational turns / tool selection | `backend/logs/agent-runtime.log` | Assistant agent turn dispatch, selected management tool, tool-call path (agents run only in AR) |
| Management tool routing (AR → CH → CC) | `backend/logs/communication-hub.log` | MCP `tools/call` routing of management calls to CC; `tenant.signature.*` verify outcomes |
| MCP session / catalog | `backend/logs/communication-hub.log` | `tools/list` catalog build (permission-filtered) and `tools/call` dispatch |
| Certificate rejections | `backend/logs/agent-runtime.log` (AR cert middleware) / `backend/logs/communication-hub.log` (CH control-plane) | `rejected` lines per the existing `logs.troubleshooting_notes` convention |
| OTEL export health | `backend/logs/otel.log` | Trace/log export diagnostics for assistant-tool spans (rotated separately) |

Audit attribution (database-backed, not log-derived): every management action is attributed to the **OAuth-authenticated user** and recorded in `ToolCallRecord` (`tool_name`, `tool_input`, `tool_output`, `error`) plus `RuntimeToolCall`. These are the authoritative audit trail — query the conversation store directly for compliance review.

Sensitive-data exclusion (reinforces existing logging conventions): identity tokens, DB credentials, and decrypted MCP/provider credentials are never logged and never returned in tool results; read handlers omit them and write handlers never echo them. No new log field may carry credential material.

## 3. Common Issues

- **MCP client / assistant receives 401 on `/mcp` (OAuth auth rejected).**
  - Likely cause: missing, invalid, or expired OAuth/OIDC Bearer token, or the token's identity is not provisioned as a `PlatformUser`.
  - Check `communication-hub.log` for `mcp.oauth.rejected` (reason label) and `control-center.log` for the identity resolution.
  - Resolution: confirm the OIDC issuer/JWKS configuration matches the identity provider; verify the user has signed in through the Control Center and holds a role; check clock skew on token validation. See runbooks `oidc-integration.md` and `service-segregation-boundary-enforcement.md`.

- **Permission-denied on actions the user can do in the UI (identity-resolution / parity failure).**
  - Likely cause: the OAuth identity could not resolve to a `PlatformUser`, or the parity map diverges from the REST endpoint's `require_permission`.
  - Check `control-center.log` for `management_tool.identity_resolution_failed` and compare the tool's `(resource_type, action)` against the matching REST endpoint.
  - Resolution: fix the identity mapping for the authenticated user; correct the parity map in the management-tool registry so it matches the REST router (skills → `agent::skills`, SOPs → `agent::sops`, schedules → `agent::schedules`, data types → `agent::data_types`, MCP Hub → `integration::mcp_hub`, agent types/roles/identities/model configs → bare `agent`).

- **Assistant entry point missing / "assistant not found" after a migration.**
  - Likely cause: the `AssistantSeeder` did not run or the `is_system` migration was not applied.
  - Check `control-center.log` for `assistant.seed.failed` and confirm `alembic current` matches the latest revision in `backend/alembic/versions/`.
  - Resolution: apply pending migrations (`alembic upgrade head`), restart CC so the idempotent seeder provisions the system `AgentType` (`is_system=true`) and its management MCP tools.

- **Certificate rejections after code changes / restarts.**
  - Check `agent-runtime.log` for `rejected` lines (AR cert middleware) and `communication-hub.log` for control-plane middleware rejections.
  - Resolution: restart `communication-hub,agent-runtime` via `parthenon.ps1` (CC first) to rebootstrap certs; see `certificate-security.md`.

- **Management MCP tool missing from `tools/list` / "tool not permitted".**
  - Likely cause: the management tool was not registered in `SystemToolRegistry`, or the authenticated user's permissions do not grant the tool's `(resource_type, action)`.
  - Check `communication-hub.log` for the catalog build and `control-center.log` for `management_tool.permission_denied`.
  - Resolution: register the tool in `SystemToolRegistry` with its parity `(resource_type, action)`; confirm the user's role/policy grants that resource type (a missing grant is expected behavior, not a defect).

- **Assistant declines a delete request.** Expected behavior — deletion is not supported at this stage (no delete tool is registered) and every delete attempt returns a structured non-mutating denial. No action required unless the denial rate is abnormal (see Monitoring).

- **System agent type cannot be edited/deleted from the UI.** Expected behavior — the Control Center Assistant is `is_system=true` and protected. To change its configuration, update the seeder/seed data and restart CC (idempotent re-seed), not the UI.

## 4. Master Operations Update Instructions

Update `docs/master/operations/`:

- **`monitoring.md`**
  - Add the new Control Center Assistant metrics to the "Key Metrics by Component" table (delegated-action volume, permission-denial rate, delete-rejection count, out-of-scope rejections, tool latency p99, OAuth identity-resolution failures, MCP auth rejections, seed health).
  - Add a "Control Center Assistant" dashboard/panel group under "Dashboards to Create".
  - Add the assistant alerts (`AssistantPermissionDenialSpike`, `AssistantIdentityResolutionFailure`, `McpOAuthAuthRejectionSpike`, `AssistantDeleteRejectionSurge`, `AssistantSeedFailed`) to the "Alerts to Configure" tables.

- **`logging.md`**
  - Add a "Control Center Assistant — Management Tool Events" subsection to the per-component log event table documenting the `management_tool.*` events (allowed / permission_denied / scope_rejected / delete_rejected / call_failed / identity_resolution_failed), the `mcp.oauth.*` auth events, and `assistant.seed.*` events, with levels, key fields, and log-file locations.
  - Note the audit attribution (OAuth-authenticated user → `ToolCallRecord` / `RuntimeToolCall`) and the sensitive-data exclusion (no identity tokens, DB credentials, or decrypted MCP/provider credentials in tool results or logs).

- **`README.md`**
  - Add a row to the Dashboards table for the Control Center Assistant panel group.
  - Add a runbook row for the new assistant runbook (see below).

- **`runbooks/`** — add a new `control-center-assistant.md` runbook covering the OAuth 401/403 triage, identity-resolution permission denials, missing-seed recovery, cert rejections, and catalog/registration drift, cross-referencing `oidc-integration.md`, `certificate-security.md`, and `service-segregation-boundary-enforcement.md` where they overlap.
