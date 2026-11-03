# Runbook: Control Center Assistant

Covers the conversational Control Center Assistant and the OAuth MCP plane it shares: delegated `cc____` management tools, the confirmation/HITL flow, conversational turns over the Communication Hub WebSocket, and the per-tenant Control Center (`cc`) MCP entity.

Related: [oidc-token-failure.md](oidc-token-failure.md) (token/JWKS/issuer), [tenant-context-missing.md](tenant-context-missing.md) (signed tenant headers), [certificate-security.md](certificate-security.md) (cert lifecycle), [service-segregation-boundary-enforcement.md](service-segregation-boundary-enforcement.md) (mTLS/allowlist denials), [agent-runtime.md](agent-runtime.md) (session stuck/timeouts).

Log files: `backend/logs/control-center.log`, `communication-hub.log`, `agent-runtime.log`, `otel.log`. Most assistant signals are **log-derived today** — see the Control Center Assistant sections of [monitoring.md](../monitoring.md) and [logging.md](../logging.md).

---

## 1. Chat 401 / 403 (OAuth token, issuer, clock skew)

**Symptoms**: WebSocket closes immediately (`1008`), `/mcp` returns 401 `auth_type: oauth`, chat shows a generic connect failure, external MCP client cannot list tools.

**Where to look**

- `communication-hub.log`: `OAuth middleware: invalid user token`, `token missing sub claim`, `CC resolve returned HTTP <n> for sub`, `failed to resolve user via CC`.
- `control-center.log`: `auth.oidc.jwt_invalid` with `reason` (`signature`/`expired`/`audience`/`issuer`/`claims`), `oidc.discovery.*`, `oidc.jwks.*`.
- `communication-hub.log`: `WebSocket rejected: invalid token` vs `WebSocket rejected: <tenant reason>` — the latter is a tenant binding failure, not a token failure.

**Triage**

1. `invalid_token` → validate issuer/audience/client config against the tenant's identity provider; confirm the token is unexpired. Follow [oidc-token-failure.md](oidc-token-failure.md).
2. `expired`/`issuer`/`signature` concentrated on one provider → JWKS cache or key rotation; check `oidc.jwks.fetch_failure` and registry reload errors.
3. Fan-out of signature failures across all users right after a restart → clock skew between the platform host and the IdP; compare token `iat`/`nbf` against host time (tolerance is minutes, not hours).
4. `CC resolve returned HTTP 403` → the token is *valid* but the identity is not provisioned (no `PlatformUser` sub match) or the tenant slug does not resolve. Fix the identity/tenant mapping — do not relax validation.
5. `CC resolve returned HTTP 503` → root tenant not provisioned; see [startup-validation-failure.md](startup-validation-failure.md).
6. WebSocket closes with `4003` and a tenant reason → triage per [tenant-context-missing.md](tenant-context-missing.md); WebSockets bypass HTTP tenant middleware and bind context at connect time.

**Never**: disable token validation, widen audience, or bypass identity resolution to restore chat.

---

## 2. Permission denied on actions the UI allows (parity drift)

**Symptoms**: the user can create/update the same resource in the Agents UI, but the assistant answers "you do not have permission" or the tool is absent from its catalog.

**Where to look**

- `control-center.log`: `Management resolve: … permitted=<n>` — `0` means the user holds no management grants in the resolved tenant.
- `control-center.log`: `authorize_identity DENIED: user_id=… module=… action=… reason=…` — the response carries `PermissionDeniedDetail` with `resource_type`/`action`.
- `communication-hub.log`: `MCP tool call: tool=cc____…`.
- DB: the user's role grants for the resource type; `ToolCallRecord` for the denied attempt.

**Triage**

1. Confirm the authenticated identity: `sub` in the resolve line must belong to the signed-in user and to an active tenant membership.
2. Compare the tool's `(resource_type, action)` parity with the matching REST endpoint's `require_permission`. Known mapping: skills → `agent::skills`, SOPs → `agent::sops`, schedules → `agent::schedules`, data types → `agent::data_types`, MCP Hub servers/tools → `integration::mcp_hub`, the `cc` entity → `integration::control_center`, agent types/roles/identities/model configs → bare `agent`.
3. Wildcards are honored (`agent::*`, `integration::*`, `*::*`) but only **within the session tenant** — a wildcard in another tenant does not apply.
4. If the REST endpoint allows and the tool denies with the same identity and tenant, treat it as a parity defect: the registry parity entry is wrong, not the user's grants.
5. An unknown resource type yields 403 for **everyone**, including wildcard admins — verify any newly referenced resource type is registered in the manifest (backend and frontend).

---

## 3. Missing or blank assistant (seed failure, model not configured)

**Symptoms**: the Agents menu has no Control Center Assistant; the entry exists but opening it shows nothing; every first message fails with "No model is configured for this workspace yet".

**Where to look**

- `control-center.log` at startup: `AssistantSeeder complete: …`, `AssistantSeeder failed; …`, `AssistantSeeder: provisioning failed for tenant …`, `AssistantSeeder: management tool '…' could not be provisioned`.
- DB: the tenant's assistant `AgentType` (`is_system = true`), the `cc` MCP server (slug `cc`), its `cc____` tool rows, and the seeded management skill's tool bindings.
- Schema drift: `alembic current` vs the latest revision in `backend/alembic/versions/`.

**Triage**

1. Seeder ERROR at startup → apply pending migrations (`alembic upgrade head`), then restart Control Center. The seeder is idempotent and per tenant; a single tenant's failure rolls back only that tenant.
2. Missing `cc` entity or missing tool rows for one tenant → re-run the seeder by restarting Control Center; verify the `cc` server exists with slug `cc` and `base_url` empty (the seeder is its only writer).
3. Management skill present but zero tool bindings → see §8.
4. Never edit or delete the assistant through the UI/API: it is `is_system = true` and returns 403 by design. Configure it by changing the seeder/seed data and restarting.
5. "No model is configured for this workspace" is **configuration, not a defect**: an administrator must select a model per workspace (System Config → Assistant model). The selection is tenant-scoped and validated against that tenant's enabled model list; a rejected 422 means the chosen model is not enabled by any model configuration in that workspace.
6. Model bound but turns fail with `model_binding_error` → the model configuration's credential/provider is unavailable; triage the provider config, not the assistant.

---

## 4. Turn hangs or times out (watchdog, LLM timeout, iteration limit)

**Symptoms**: "thinking" spinner never resolves; the user sees a timeout message; long turns repeat after reconnect; a task stops with a step-limit message.

**Where to look**

- `communication-hub.log`: `Conversation turn watchdog fired …` (no reply yet) vs `Conversation turn persistence exceeded the watchdog …` (reply delivered, CC write hung); `Conversation turn blocked …: code=…`.
- `agent-runtime.log`: `Conversation turn timed out after …s (session=…, bound=…)`, `Conversation guardrail stop …: reason=…`, `Conversation turn … paused on human_intervene`.
- `control-center.log`: `dispatcher.stalled`, session status transitions, conversation turn persistence failures.
- `otel.log`: exporter errors are irrelevant to turn latency — do not chase them first.

**Triage order**

1. Is a confirmation pending? `paused on human_intervene` plus `waiting_for_human` means the assistant is legitimately waiting for the operator (bounded by `conversation_intervention_timeout_seconds`). Answer or cancel the confirmation; new chat messages are blocked meanwhile and return `chat_blocked`.
2. `watchdog fired` without any AR log → the AR call never started or the socket/turn task was orphaned; check CH→AR connectivity and certificates (§6).
3. `Conversation turn timed out … bound=…` in AR → the provider call exceeded `conversation_llm_timeout_seconds`. Check provider latency and the model's tool count; retry once before escalating.
4. `reason=iteration_limit` / UI step-limit message → the agentic loop hit `max_iterations` for the assistant. Typical causes: an oversized tool catalog, repeated schema lookups, or a model that re-discovers tools each step. Reduce catalog noise (scope the user's grants), prefer `get_mcp_server` discovery results, and raise the limit only with a documented reason.
5. `guardrail_timeout_limit_hit_total` / other stop reasons → follow [agent-execution-guardrails.md](agent-execution-guardrails.md) and [agent-runtime.md](agent-runtime.md).
6. Persistence-tail timeouts are cosmetic for the user but leave the stored turn incomplete: verify the error turn was persisted once (no duplicates) before closing.

---

## 5. WebSocket reconnect and reply delivery

**Symptoms**: the reply never appears in the UI though the run completed; the transcript shows a gap; the socket drops repeatedly during long turns.

**Where to look**

- `communication-hub.log`: `WebSocket connected` / `WebSocket disconnected: … code=… reason=…`, `WebSocket send failed for session …`, `Cancelled pending conversation turn`.
- DB: conversation turns for the session (user turn without an agent turn = interrupted delivery).
- Browser: the client reconnects with the **same session id**; the newest socket becomes the live target.

**Triage**

1. `code=1006`/no close frame and no server error → idle proxy or network closed the socket; heartbeats every 15 s normally prevent this. Verify the client is not behind a proxy that strips WS keepalives.
2. `WebSocket send failed` → send attempted on a dead socket. Replies resolve the **live** socket at send time, so a stale-socket send should self-heal on the next event; persistent failures mean the session never re-registered.
3. Reply persisted but not shown → confirm the turn row in the Conversation Sessions view; re-open the conversation. If the row is missing, the turn was canceled (§4) or persistence failed.
4. `code=1008` → invalid token (§1). `code=4003` → tenant binding failure ([tenant-context-missing.md](tenant-context-missing.md)).
5. Duplicate error bubbles → dedupe guard failed; collect the session id and the watchdog log pair before escalating.

---

## 6. End-session never stops the turn (CC → CH → AR chain)

**Symptoms**: the user ends the conversation but the assistant keeps "thinking"; the turn only stops after the watchdog; AR still shows an active session.

**Where to look**

- `control-center.log`: `In-flight conversation execution terminated for session …` / `No in-flight execution to terminate for conversation session …` / `Best-effort termination failed for conversation session …`. Note that termination is **best-effort** — failures are logged and never raised, so the user-facing "end" can succeed while the turn keeps running.
- `communication-hub.log`: `Agent termination request forwarded: session=… reason=…`, `Cancelled pending conversation turn for session …`, retry lines (`Retrying Agent Runtime termination`).
- `agent-runtime.log`: `/terminate` receipt and the AR cancellation; `cert.validation.failed` / `rejected` lines if mTLS failed.
- `communication-hub.log`: `No certificate manager available — Agent Runtime call may fail authentication`.

**Triage**

1. CH must forward the terminate with its **service** certificate (`CN=service:communication-hub`); AR rejects the Control Center cert on `/terminate`. A 401/403 at AR with a valid operator action is a certificate-class problem → [certificate-security.md](certificate-security.md) and [service-segregation-boundary-enforcement.md](service-segregation-boundary-enforcement.md).
2. `cert.validation.failed` with `expired`/`revoked` → rebootstrap: restart backend services in enforced order (Control Center → Agent Runtime → Communication Hub) so certificates re-issue — `parthenon.ps1` on Windows, `./scripts/restart-backend.sh` on macOS.
3. No certificate manager at all → restart `communication-hub,agent-runtime` after Control Center is healthy.
4. `Best-effort termination failed for conversation session …` → the CC→CH call itself failed (CH down, cert, or timeout); the turn will end at the watchdog. Report as a defect with the session id.
5. AR reports `already_terminal` → the session had already finished; verify the UI state rather than re-terminating.

---

## 7. `cc` entity errors (system-managed, permission gate, catalog truncation)

**Symptoms**: 403 "The Control Center integration is system-managed and cannot be modified", 403 mentioning `integration::control_center`, "Sessions are not supported for the Control Center integration", or the assistant reports a management tool/server that is not visible in the UI.

**Where to look**

- `control-center.log`: the MCP Hub REST 403/404 for the `cc` row; `integration::control_center` permission decisions.
- `communication-hub.log`: `tools/list` catalog and `MCP tool call` lines.
- DB: `mcp_servers` row with slug `cc` (name "Control Center", empty `base_url`), its `mcp_tools` rows (`cc____…`), and which roles/skills hold grants.

**Triage**

1. `system_managed_integration` on update/delete/sync/OAuth → **expected**. The entity is immutable for everyone, including `integration::control_center:manage` holders; the seeder is the only writer. Change seed data and restart, never the UI.
2. Sessions-unsupported variant → expected. Access to `cc` tools flows through role and skill grants only; do not attempt to create MCP sessions for it.
3. `integration::control_center:read` missing → the entity and its tools are hidden (list omitted, direct read returns 404 to avoid leaking existence). Grant the entity read permission if the operator legitimately needs visibility.
4. Grants on `cc` tools missing → tool-grant operations require `integration::control_center:manage`; grant it deliberately, it exposes the whole entity catalogue.
5. "Tool not in `tools/list`" → first check whether the tool simply is not in the caller's permitted set (deny-by-default is correct). Then check the catalog itself: an empty catalog with `permitted>0` is a registration/canonical-name drift bug.
6. Pagination: management `list_*` returns at most 100 rows per page (default 50) with `offset`. A record "missing" from a large tenant is usually an un-paged second request, not truncation. The `cc` entity's absence from a list is permission filtering, not truncation.
7. The `system`/`decision` virtual entities always occupy the first two listing slots; offsets shift when the `cc` visibility changes for the caller.

---

## 8. Skill tool-binding failures (zero-bindings warning)

**Symptoms**: the assistant creates/updates a skill but says it "cannot invoke anything"; a skill shows no tools; binding an MCP tool fails with 404.

**Where to look**

- Tool result: the non-fatal warning text "This skill has no tools bound — it cannot invoke anything."
- `control-center.log`: `AssistantSeeder: management tool '…' could not be provisioned … binding skipped`.
- DB: `skill_tool_bindings` for the skill; `mcp_tools` rows in the **calling tenant** with the exact canonical `server____tool` name.

**Triage**

1. Zero bindings is allowed (warning, not error) — the assistant is instructed to self-correct immediately. Confirm it then issues `update_skill` with `tool_ids`/`tool_names`.
2. `404 MCP tool not found in this workspace` → the tool name is wrong, the tool is inactive, or it belongs to another tenant. Names must be the canonical `server____tool` (e.g. `supabase____run_sql`, `cc____create_skill`), resolved within the calling tenant only.
3. Discover first: use the MCP server's `tools` list (via `get_mcp_server`) and bind the exact names returned; do not guess names from the UI label.
4. Bindings are **additive** on update — an omitted list keeps existing bindings; an empty list does not clear them. To reason about "why does this skill still have tools", inspect the binding rows rather than the request payload.
5. Decision tools are virtual (no `mcp_tools` row) and degrade to the bare tool id; a missing binding for a decision tool is usually a readiness problem, not a name problem.
6. Seeder-time `binding skipped` errors mean the `cc____` tool row was not provisioned for that tenant → §3 step 2.
7. **Inherent skills are not tenant skill rows.** The built-in self-context / self-optimisation skills are derived from the system-tool registry and injected into every agent's execution context, so they never appear in the tenant skill list and cannot be bound or granted. "A skill is missing from the list" is expected for these; check the tool schemas the agent receives instead.

---

## Where to Look (summary)

| Concern | Location |
|---------|----------|
| OAuth token / identity / tenant binding | `communication-hub.log` (`OAuth middleware:*`), `control-center.log` (`auth.oidc.*`, `oidc.*`, `Management resolve:*`) |
| Management tool outcome / permission denial | `control-center.log` (HTTP status + structured detail), `communication-hub.log` (`MCP tool call:*`) |
| `cc` entity guards | `control-center.log` (403 codes `system_managed_integration`), MCP Hub REST handlers |
| Conversation turns / watchdog / heartbeats | `communication-hub.log`, `agent-runtime.log` |
| Interventions (confirmation/HITL) | `agent-runtime.log` (pause/resume), `control-center.log` (request state), spans `intervene.*` |
| Termination chain | `control-center.log` → `communication-hub.log` → `agent-runtime.log` (in that order) |
| Certificate rejections | `agent-runtime.log` / `communication-hub.log` `rejected` lines; [certificate-security.md](certificate-security.md) |
| Audit trail (authoritative) | DB `ToolCallRecord` + `RuntimeToolCall`; conversation store turns |

**Never** remediate by disabling authentication, widening permissions, bypassing identity resolution, or editing the system-managed `cc` entity / assistant agent type.
