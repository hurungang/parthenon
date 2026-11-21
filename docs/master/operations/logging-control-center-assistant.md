# Logging — Assistant Management Plane

The assistant's management plane: delegated `cc____` tool calls, the MCP OAuth identity plane, `cc` entity guards, assistant seeding, progressive tool disclosure, and catalog anomalies. The conversational turn lifecycle lives in [logging-conversation-turns.md](logging-conversation-turns.md).

Hub: [logging.md](logging.md) · Operations index: [README.md](README.md)

## Control Center Assistant Events

The Control Center Assistant is a **delegated actor**: it acts as the signed-in OAuth user, never elevated, never deleting. Management tools are `cc____<bare>` tools on the Communication Hub MCP protocol server; both the in-app chatbot and external MCP clients use the same OAuth identity plane and the same permission resolution.

> **Instrumentation note**: the assistant emits **plain structured log lines today** — there are no dedicated `management_tool.*` OTel counters or JSON event names yet. The *Proposed event* column is the stable taxonomy to adopt when counters/events are instrumented; use the *Observed message* column for live greps.

---

### Management Tool Execution and Permission Decisions

**Log source**: `backend/logs/control-center.log`

| Observed message | Proposed event | Level | Key fields | When logged |
|------------------|----------------|-------|-----------|-------------|
| `Management resolve: sub=… user=… tenant=… permitted=…` | `management_tool.session_resolved` | INFO | `sub`, `platform_user_id`, `tenant_id`, `permitted_count` | OAuth MCP session creation; `permitted=0` means the user holds no management grants in the resolved tenant |
| `authorize_identity DENIED: user_id=… module=… action=… reason=…` | `management_tool.permission_denied` | WARN | `user_id`, `resource_type` (`module`), `action`, `reason` | Parity authorization failed for the user's own scope on `/{tool_name}` or the `invoke_management_tool` wrapper; the HTTP response carries `PermissionDeniedDetail` |
| `authorize_identity ALLOWED: user_id=… module=… action=…` / `ALLOWED via membership: …` | `management_tool.call_allowed` | DEBUG | `user_id`, `module`, `action` | Successful per-call re-authorization (debug level; enable temporarily when tracing a denial) |
| `authorize_identity: user_id=… has no active membership in resolved tenant=… — no_access_to_workspace` | `management_tool.tenant_membership_denied` | WARN | `user_id`, `tenant_id` | Identity is valid but holds no membership in the resolved tenant; returns the structured `no_access_to_workspace` 403 |
| Tool result body `{"error":"out_of_scope"}` returned by the Communication Hub (no CC write attempted) | `management_tool.scope_rejected` | WARN | `tool_name`, `requested_scope` | Request outside the Agents-menu / MCP Hub management surface |
| Tool result body `{"error":"deletion_not_supported"}` | `management_tool.delete_rejected` | WARN | `tool_name` | Any delete-shaped `cc____delete_*` attempt; deliberately non-mutating |
| Tool result body `{"error":"permission_denied"}` returned by the Communication Hub | `management_tool.permission_denied` (CH-side) | WARN | `tool_name` | Canonical name is not in the OAuth session's permitted set; denied before the CC call |
| HTTP 404 `Unknown or out-of-scope management tool` / `Unknown management verb` | `management_tool.unknown_tool` | WARN | `tool_name`, `verb` | Unregistered tool or delete-verb backstop at the CC dispatch layer |
| `authorize_identity: PlatformUser not found for sub=… — user must re-authenticate` | `management_tool.identity_resolution_failed` | WARN | `sub` | OAuth identity could not resolve to a `PlatformUser`; fail-closed, no write performed |
| `Created intervene request …` / `Submitted response …` from the intervene service | see Intervention lifecycle below | INFO | `request_id`, `session_id`, `operator` | Confirmation/HITL lifecycle |

**Dispatch path**: Communication Hub `tools/call` → `POST /api/v1/internal/management-tools/{tool_name}` (or the meta wrapper `invoke_management_tool`) → re-authorization against the user's own `(resource_type, action)` → handler. The per-call denial is returned in-band (assistant relays it) — there is no elevated fallback path.

---

### MCP OAuth Identity Plane (Communication Hub)

**Log source**: `backend/logs/communication-hub.log`

| Observed message | Proposed event | Level | Key fields | When logged |
|------------------|----------------|-------|-----------|-------------|
| `OAuth middleware: authenticated user <sub> on <path>` | `mcp.oauth.authenticated` | INFO | `sub`, `path` | OIDC (or platform-account) Bearer token validated on `/mcp*` |
| `OAuth middleware: bound tenant <tenant_id> for user <sub>` | `mcp.oauth.tenant_bound` | INFO | `tenant_id`, `sub` | Multi-tenant mode: CC-signed header set bound for downstream calls |
| `OAuth middleware: invalid user token on <path>` | `mcp.oauth.rejected` (reason `invalid_token`) | WARN | `path` | Signature/expiry/issuer failure → HTTP 401, `auth_type=oauth` |
| `OAuth middleware: token missing sub claim on <path>` | `mcp.oauth.rejected` (reason `missing_subject`) | WARN | `path` | Valid signature but unusable identity → HTTP 401 |
| `OAuth middleware: CC resolve returned HTTP <n> for sub <sub>` | `mcp.oauth.rejected` (reason `identity_unresolvable` / `tenant_unresolvable`) | WARN | `sub`, `status_code` | CC `/resolve` denied (unknown user or unresolvable tenant) → HTTP 401 |
| `OAuth middleware: failed to resolve user via CC: <exc>` | `mcp.oauth.resolve_error` | ERROR | `sub`, `error` | Transport/CC failure during resolve; also fail-closed 401 |
| `OAuth middleware: unexpected OIDC error` / `platform token validation failed` | `mcp.oauth.validation_error` | WARN | `path` | Validation exceptions (JWKS fetch, clock skew, malformed token) |

Non-JWT (opaque `phn_sk_*`) tokens fall through untouched to the API-key middleware — see [API Key Log Events](logging-integrations.md).

---

### Control Center (cc) Entity Guards

**Log source**: `backend/logs/control-center.log` (MCP Hub REST surface)

| Response code | Proposed event | Level | Key fields | When returned |
|---------------|----------------|-------|-----------|---------------|
| `403` with `code = system_managed_integration` (detail: "system-managed and cannot be modified") | `cc.entity.system_managed_rejected` | WARN | `actor`, `operation` (`update`/`delete`/`sync`/`oauth`) | Any attempt to mutate/lifecycle the `cc` entity — locked for everyone; the seeder is the only writer |
| `403` with `code = system_managed_integration` (detail: "Sessions are not supported") | `cc.entity.sessions_unsupported` | WARN | `actor`, `operation` | Session operations against `cc`; access flows through role/skill grants only |
| `403` with `required_permission.resource_type = integration::control_center` | `cc.entity.permission_gated` | WARN | `actor`, `action` (`read`/`manage`) | Tool-grant operations on `cc` tools without the entity grant |
| `404 MCP server not found` (while the `cc` row exists) | `cc.entity.hidden` | DEBUG | `actor` | Read-visibility gate: the entity is hidden from callers lacking `integration::control_center:read` |
| `403 System agent types cannot be modified` / `cannot be deleted` | `assistant.agent_type.protected` | WARN | `agent_type_id`, `actor` | Direct REST mutation of the seeded `is_system=true` assistant agent type |

---

### Assistant Seed Events

**Log source**: `backend/logs/control-center.log` (startup)

| Observed message | Proposed event | Level | Key fields | When logged |
|------------------|----------------|-------|-----------|-------------|
| `AssistantSeeder complete: {summary}` | `assistant.seed.success` | INFO | `tenants`, `per_tenant` (created/updated) | Idempotent per-tenant seed finished |
| `AssistantSeeder failed; the assistant may be unavailable.` | `assistant.seed.failed` | ERROR | `error` (stack) | Seeder raised; assistant agent type/tools may be missing |
| `AssistantSeeder: provisioning failed for tenant … — rolling back this tenant only and continuing.` | `assistant.seed.tenant_failed` | ERROR | `tenant_id` | Per-tenant failure (other tenants unaffected) |
| `AssistantSeeder: management tool '…' could not be provisioned for tenant … — binding skipped.` | `assistant.seed.binding_skipped` | ERROR | `tool_name`, `tenant_id` | Registry/tool row mismatch; that management tool is unreachable through the skill |
| `AssistantSeeder: created management skill '…'` / `updated management skill '…'` | `assistant.seed.skill` | INFO | `skill_name`, `tenant_id` | Management skill upsert |
| `AssistantSeeder: provisioned management tool '…' for tenant …` | `assistant.seed.tool` | INFO | `tool_name` (`cc____…`), `tenant_id` | New `cc____` tool row created |
| `AssistantSeeder: provisioned/refreshed per-tenant Control Center (cc) server for tenant …` | `assistant.seed.cc_server` | INFO | `tenant_id` | Protected `cc` MCP entity upserted/drift-corrected |
| `AssistantSeeder: retired N legacy system____ management rows for tenant …` | `assistant.seed.legacy_retired` | INFO | `tenant_id`, `rows` | One-time `system____` → `cc____` namespace migration |
| `AssistantSeeder: created/updated assistant agent type '…'` | `assistant.seed.agent_type` | INFO | `agent_type`, `tenant_id` | Seeded `is_system=true` assistant agent type |
| `SkillSeeder complete: {summary}` / `SkillSeeder failed; …` | `skill.seed.*` | INFO / ERROR | `summary` | Companion seeder; a failure degrades default skills, not the assistant |

A seeded assistant with **no model bound** is valid: the first turn returns the structured `assistant_model_not_configured` error until an administrator picks a model per workspace (System Config → Assistant model).

---

### Knowledge and Meta-Tool Dispatch

**Log sources**: `backend/logs/communication-hub.log` (`MCP tool call: tool=…`), `backend/logs/control-center.log` (meta endpoints)

| Observed message | Proposed event | Level | Key fields | When logged |
|------------------|----------------|-------|-----------|-------------|
| `MCP tool call: tool=… session=… key=…` | `mcp.tools_call` | INFO | `tool_name` (canonical `cc____…`), `session_id`, `api_key_name` | Every `tools/call` reaching the protocol server (OAuth sessions show the session, not a key) |
| Meta dispatch of `invoke_management_tool` / `list_management_tools` / `get_management_tool_schema` / `search_assistant_knowledge` | `assistant.meta.dispatch` | INFO (proposed) | `meta_tool`, `target_tool`, `count` | Progressive tool disclosure: the assistant context carries only the constant meta tools, never the ~36 management schemas |
| `MCP method <m> failed` | `mcp.method.failed` | ERROR | `method`, `error` | Unhandled exception inside a JSON-RPC method (also covers catalog build failures) |

`list_management_tools` returns the cheap catalog (name + one-line description + `requires_permission`); `get_management_tool_schema` returns one full schema on demand. A `404 Unknown management tool` from either is a registry/parity mismatch, not a permission problem.

---

### Catalog Listing Anomalies

**Log source**: `backend/logs/communication-hub.log` (`tools/list`) and `backend/logs/control-center.log` (MCP Hub REST listing)

| Signal | Proposed event | Level | Key fields | Meaning |
|--------|----------------|-------|-----------|---------|
| OAuth `tools/list` returns an empty array while `/resolve` reported `permitted>0` | `assistant.catalog.empty` | WARN | `sub`, `permitted_count` | Bridge filtering dropped every permitted name (registration vs canonical-name drift) |
| REST list returns exactly `limit` rows (default 50, hard cap 100) | `assistant.catalog.page_truncated` | INFO | `resource`, `limit`, `offset` | Normal pagination — the assistant must page with `offset`; a "missing record" report is usually this |
| `cc` server visible to an identity without `integration::control_center:read` | `assistant.catalog.cc_entity_leak` | WARN | `actor` | Visibility-gate regression on the protected entity |
| `404 Unknown or out-of-scope management tool` at dispatch | `assistant.catalog.unknown_tool` | WARN | `tool_name` | Model called a tool that was never in its catalog (stale schema/instruction drift) |

---

### Audit Attribution and Sensitive Data

Audit attribution is **database-backed, not log-derived**: every management action is attributed to the OAuth-authenticated user and recorded in `ToolCallRecord` (`tool_name`, `tool_input`, `tool_output`, `error`) plus `RuntimeToolCall`. Query the conversation/tool-call store for compliance review; logs are the operational signal only.

Sensitive-data exclusion (reinforces the existing logging conventions):

- Never log identity tokens, refresh tokens, JWT bodies, DB credentials, API keys, or decrypted MCP/provider credentials.
- Read handlers omit credential material and write handlers never echo it back into tool results; no new assistant log field may carry credential material.
- Log operational identifiers only: `tool_name`, `resource_type`, `action`, `sub`/`tenant_id`, `session_id`, `request_id`, `code`/`reason`.
