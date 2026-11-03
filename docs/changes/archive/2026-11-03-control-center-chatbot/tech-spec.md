# Technical Specification: Control Center Assistant (Chatbot)

## 1. Technical Overview

The Control Center Assistant is a seeded, system-provided conversational `AgentType` running in Agent Runtime (AR) that lets a Control Center user perform Agents-menu management tasks (create / update / read of skills, SOPs, agent types, roles, identities, model configurations, schedules, data types, MCP Hub connections) in natural language.

Management operations are exposed as **MCP tools** on the existing Communication Hub MCP protocol server (`/mcp`), authenticated via **OAuth/OIDC** — the *user's* Bearer token. One tool surface serves two consumers: (a) the in-app chatbot (an agent in AR) and (b) external MCP clients/agents holding the user's OAuth credentials — both use the same tools.

OAuth is the identity plane: the MCP session authenticates as the user, so the permission scope of every call is the user's own scope. This is parallel to the existing API-key auth path (`backend/app/communication_hub/middleware/api_key_auth.py`) and reuses the permission-filtered catalog in `backend/app/communication_hub/mcp/tool_registry_bridge.py`. The same security layer applies to both the UI and MCP surfaces: every management call is authorized by the permission engine against the same `(resource_type, action)` the corresponding REST endpoint enforces. There is no elevated path — deletion is simply not a registered tool.

The change is additive. It reuses the existing MCP protocol server (`McpProtocolServer`), the `ToolRegistryBridge`, `SystemToolRegistry`, the session manager and both transports, the conversational chat channel (`backend/app/api/ws/chat.py`, `frontend/src/components/agents/ConversationDialog.tsx`, `frontend/src/hooks/useChatSession.ts`), and the permission/resource-type definitions (`backend/app/core/resource_types.py`, `backend/app/api/deps.py`). The only schema change is a new `is_system` boolean on `AgentType`.

## 2. Component Breakdown

### Backend

- **`AgentType.is_system`** — new boolean on the `AgentType` model marking system-provided agent types (the Control Center Assistant) as protected from user edit/delete and surfaced specially in the UI, mirroring the existing `Skill.is_system` / `Role.is_system` convention.
- **OAuth/OIDC Bearer-token auth on the MCP server (new)** — a new auth path added to the MCP protocol server, parallel to `ApiKeyAuthMiddleware`: validates the *user's* OIDC Bearer token on `/mcp*` paths, resolves the user's identity (`sub` → `PlatformUser`), permission scope, and tenant, and seeds the MCP session with that context. The identity token stays server-side (never returned to the client), mirroring the API-key path's holding rules.
- **Management MCP tools (new)** — create/update/read tools for the nine resource families, registered in `SystemToolRegistry` under the canonical `system____<verb>_<resource>` name pattern (e.g. `system____create_skill`, `system____update_skill`, `system____list_skills`, `system____get_skill`). Each tool carries its parity `(resource_type, action)`. No delete tools are registered.
- **Management-tool parity map** — a single source of truth keying each management tool to the exact `(resource_type, action)` its REST equivalent enforces (see §3), so an MCP call can never perform an action the REST API would deny.
- **Permission enforcement at `tools/list` / `tools/call`** — the permission-filtered catalog lists only the management tools the user is authorized for, and dispatch re-checks the tool's parity permission via the permission engine before any write. Out-of-scope resources and any delete verb are declined before mutation.
- **`SystemToolRegistry`** — existing registry extended with the management tools (stable UUIDs, schemas, CC endpoint paths); routing, schemas, and seeding derive automatically as for existing system tools.
- **CC management-tool write handlers (new)** — the DB-write implementations for the management tools, executed on Control Center (the sole DB owner) via the tools' registered CC endpoint paths, following the existing `SystemToolRequest` / `SystemToolResponse` contract. They exclude sensitive material (tokens, decrypted credentials) from results.
- **`AssistantSeeder` (new)** — idempotent seeder provisioning the assistant `AgentType` (conversational, `is_system=true`) and its management tool bindings, following the `SkillSeeder` pattern. The assistant is tenant-bound: the seeder provisions the management skill + assistant `AgentType` **for every tenant** (per-tenant commit; one tenant's failure never aborts the rest). The seeder never binds a model — model selection is per-tenant operator configuration via the dedicated assistant-model endpoints, which persist onto the tenant's assistant `AgentType.model_id` (resolved by `ModelBindingLayer.resolve_model_config` at conversation time).
- **Assistant meta tools — progressive tool disclosure (new)** — instead of loading all ~36 management execution schemas into every assistant turn (~large token payload), the conversational context carries ONLY a constant, small set of meta tools: `invoke_management_tool` (dispatches any registered management tool through the existing CC management-tools dispatch, re-enforcing permission parity per invocation against the signed-in user), `get_management_tool_schema` (one tool's exact OpenAI schema on demand), `list_management_tools` (cheap catalog: name + description + permission requirement), and `search_assistant_knowledge` (keyword search over the platform knowledge corpus). The execution tools stay registered and bound — they are what the wrapper dispatches to internally (in-process CC dispatch, no extra service hop beyond the normal AR→CH→CC system-tool route) and what the parity map / resolve endpoint / external MCP clients use. Meta tools carry NO parity entry.
- **Assistant knowledge base (new)** — `assistant_knowledge.py`: a structured, deterministic (no-LLM), tenant-agnostic corpus distilled from the specs. **FIX-20261102-100704 rewrote it to GENERIC PRINCIPLES + REFERENCE FACTS — no case-scripted workflow (see §15).** Principles: understand-before-acting, `resource-completeness` (a created resource must be complete/functional in its own context; derive "complete" from the resource type's facts), `prerequisite-ordering` (a reference can only point at what exists; derive the order from discovered dependencies), `role-grant-workflow` = grant-at-the-right-level (role grants for role-based agent types, direct bindings for role-less ones), `reuse-first`. Reference facts: agent types bind skills/SOPs, never raw MCP tools; skills wrap tools through tool bindings (`skill-tool-binding`, zero bindings ⇒ inert); SOPs compose skills; roles grant skills/SOPs and identities are assigned to roles (`role-identity-chain`); per-tenant Model Config enabled-models (`model-availability`); conversational vs typed output (`io-types`); MCP hub slug/session basics; per-tenant name/slug uniqueness; no-delete boundary; permission parity; canonical `confirmation-preview-format`. The management skill's seeded `instructions` and the assistant's `system_instruction` carry the principles + a concise facts digest plus pointers to `search_assistant_knowledge` / discovery tools (the seeder diffs both constants, so existing seeded rows refresh on restart).

### Frontend

- **Assistant entry point** — a launcher in the Control Center shell that resolves the seeded system assistant and opens the existing `ConversationDialog` with its `agentTypeId`, passing `assistantModelConfigCheck` so the dialog runs the assistant-specific model-config guard. On launch it ALSO resolves the user's most recent ACTIVE conversation session for the assistant agent type (`GET /conversations?agent_type_id=…`, filter `status === 'active'`, most recent `updated_at` first) and opens the dialog with that `sessionId` so prior turns resume; when none exists (or the lookup fails) it falls back to a new session. While resolving, the dialog is not mounted (no empty-conversation flash). Closing the dialog only disconnects the WebSocket — the session stays `active` on the backend and is re-resolved on reopen; only the explicit "End session" action closes it. FIX-20261031-091657: an explicit End ALSO best-effort terminates any in-flight execution for that session (CC → CH → AR termination chain) and sets a per-agent-type "force new session" flag — the NEXT open starts a NEW session instead of resuming a stale active one (plain exit keeps resume semantics; the resolver still filters `status === 'active'`).
- **`ConversationDialog`** — reused as the conversational surface (multi-turn context, thinking/working indicators, intervention handling). When opened with `assistantModelConfigCheck` (assistant only): queries the tenant's assistant-model selection via `useAssistantModelConfig`; when `selected_model_id` is null (or the backend surfaces `assistant_model_not_configured` mid-session), renders a guidance MUI Alert inside the chat surface with a "Configure model" action navigating to `/system-config`, and disables the input/send controls. Regular agent types are unaffected.
- **`useAssistantModelConfig` (new)** — typed react-query hook for `GET /agents/model-configs/assistant-model` (`AssistantModelConfig`), gated by an `enabled` flag so non-assistant surfaces skip the check.
- **`useChatSession`** — reused for WebSocket lifecycle and message/status state; extended to parse the structured backend `{"type": "chat_error", "code", "message"}` payload into `chatError` state so actionable error codes (e.g. `assistant_model_not_configured`) can map to dedicated guidance UI.
- **Agent Types list** — updated to mark `is_system` agent types and disable their edit/delete controls.

### Model-unconfigured guard (backend)

- **`backend/app/api/ws/chat.py`** — `ConversationTurnError` (typed, carrying a stable `code` + human `message`) and `_conversation_turn_error_from_http_status`, which maps Agent Runtime's pre-model 400 "Agent model is not configured" rejection onto the `assistant_model_not_configured` code (AR checks `model_id`/`model_config_id` in `agent_runtime/api/conversation.py` BEFORE any model call). The WebSocket turn runner surfaces it as a structured `{"type": "chat_error", ...}` payload instead of a generic crash string; other 400s map to a friendly generic message, `ModelBindingError` keeps its friendly mapping, and correctly-configured agents are unchanged.

## 3. API Changes

### MCP tool surface (on `/mcp`, OAuth-authenticated)

Management operations are MCP tools, not internal REST routes. Each tool enforces the parity permission shown below. Canonical naming follows `system____<verb>_<resource>`; `list_*` and `get_*` cover read, and there is no delete verb.

| Resource family | Resource type | Create action | Update action | Read action |
|-----------------|---------------|---------------|---------------|-------------|
| Skills | `agent::skills` | `create` | `update` | `read` |
| SOPs | `agent::sops` | `manage` | `manage` | `read` |
| Agent types | `agent` (bare `RT_AGENT`) | `create` | `update` | `read` |
| Agent roles | `agent` (bare `RT_AGENT`) | `create` | `update` | `read` |
| Agent identities | `agent` (bare `RT_AGENT`) | `create` | `update` | `read` |
| Model configs | `agent` (bare `RT_AGENT`) | `create` | `update` | `read` |
| Schedules | `agent::schedules` | `create` | `update` | `read` |
| Data types | `agent::data_types` | `create` | `update` | `read` |
| MCP Hub connections | `integration::mcp_hub` | `create` | `update` | `read` |

- Where a resource type declares a `create`/`update` action, the create/update tools map to it; where it only declares `manage` (SOPs), create/update map to `manage`. Read always maps to `read`.
- `tools/list` returns only the management tools whose parity `(resource_type, action)` the authenticated user can satisfy (deny-by-default, wildcards such as `agent::*` respected via the permission engine). `tools/call` re-checks the parity permission for the requested tool before dispatch.
- The same tools are listed and callable by the in-app chatbot (AR, acting on the user's cached JWT) and by external MCP clients presenting the user's OAuth Bearer token.

### Modified existing surface

- **`AgentType` REST schemas** — `is_system` added to read/create/update payloads; update/delete of `is_system=true` agent types rejected.
- **Reused (no change)** — `POST /conversations`, `POST /conversations/{id}/resume`, `POST /conversations/{id}/archive`, and the WebSocket `/ws/sessions/{session_id}` chat endpoint remain the assistant's conversational channel.

### Explicitly absent

- No delete tools are registered; any delete verb or out-of-scope resource is declined in-band with a fixed "not supported" / "out of scope" result before any write.

## 4. State Management

- **No new global client state** — the assistant reuses `useChatSession` for messages, connection state, chat status, guardrail usage, and delegation-cycle state.
- **Assistant entry point** holds only local state: the resolved assistant `agentTypeId` (fetched once via the existing agent-types query), the `open` state of the `ConversationDialog`, and the resolved resume `sessionId` + `resolving` flag used to mount the dialog only after the latest active session lookup completes.
- **`is_system` surfacing** is a read-only presentation concern in the Agent Types list (no new store); the flag arrives on the existing agent-type query response.
- **Server-side** the permission scope is resolved per MCP session from the user's OAuth token (stateless), never persisted on the client — attribution stays server-derived from the authenticated session, and the identity token never leaves the server.

## 5. Data Access Patterns

- **Server-side only** — every management action is a database write performed by Control Center (the sole DB owner), reached via the management tools' CC endpoint paths. The frontend never talks to the DB and never calls the management tools directly.
- **MCP layer (CH)** — the OAuth-authenticated MCP server filters and authorizes tool calls against the user's permission scope via the permission engine, then forwards the call to CC for execution; CH performs no writes and holds no credentials (forward-only).
- **Client-side (frontend)** — the assistant UI only issues conversational requests through the existing WebSocket/REST conversation channel and reads the normal agent-types query; it performs no management writes and holds no management business logic.
- **Why** — this preserves the top-priority segregation rules (only CC connects to PostgreSQL; agents run only in AR; CH is forward-only) and keeps authorization authoritative at the identity plane: the user's OAuth scope is the single permission boundary, with no elevated service-credential path into management operations.
- **Sensitive data** — identity tokens, DB credentials, and decrypted MCP/provider credentials never cross the service boundary and are never echoed into conversation responses (read handlers exclude them; write handlers never return them).

## 6. Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `McpProtocolServer` | class | Stateless JSON-RPC → tool-registry bridge; handles `initialize` / `tools/list` / `tools/call` | `backend/app/communication_hub/mcp/protocol_server.py` |
| `handle` | method | Dispatches a single JSON-RPC message to the bridge (or returns a JSON-RPC error) | `backend/app/communication_hub/mcp/protocol_server.py` |
| `_handle_initialize` | method | Capability negotiation (no auth required) | `backend/app/communication_hub/mcp/protocol_server.py` |
| `_handle_tools_call` | method | Authorizes and dispatches a `tools/call` | `backend/app/communication_hub/mcp/protocol_server.py` |
| `ToolRegistryBridge` | class | Builds the permission-filtered catalog and authorizes/dispatches tool calls | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `build_catalog` | method | Produces the `tools/list` payload filtered by session permissions | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `dispatch` | method | Authorizes a `tools/call` against permitted tools and routes it (system/MCP/decision/load_skills) | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `_call_system_tool` | method | Routes a system tool to its CC endpoint via `SystemToolRegistry.get_cc_endpoint_map` | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `_build_oauth_catalog` | method (new) | Builds the OAuth permission-filtered catalog (management tools only) | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `_call_management_tool` | method (new) | Routes a management tool to its CC endpoint forwarding the user's `sub` (no identity token) | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `_management_scope_denial` | function (new) | Defense-in-depth decline of delete verbs / out-of-scope management tools | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `LOAD_SKILLS_TOOL_NAME` | constant | CH meta tool name exposed for skill discovery | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `McpSession` | dataclass | Per-connection MCP state + server-side auth context (identity token, permissions, skills, tenant; OAuth fields `auth_method` / `platform_user_id` / `user_sub`) | `backend/app/communication_hub/mcp/session_manager.py` |
| `McpSessionManager` | class | In-memory session registry with TTL idle cleanup | `backend/app/communication_hub/mcp/session_manager.py` |
| `create_session` / `get_session` | method | Create / look up an MCP session seeded with the resolved auth context | `backend/app/communication_hub/mcp/session_manager.py` |
| `is_request_authenticated` | function | Fail-closed gate: `request.state.auth_method` ∈ {api_key, oauth} | `backend/app/communication_hub/mcp/session_manager.py` |
| `build_session_from_request` | function | Seeds an `McpSession` from the resolved auth context on `request.state` (API-key + OAuth) | `backend/app/communication_hub/mcp/session_manager.py` |
| `handle_streamable_http` | function | `POST /mcp` Streamable HTTP transport; seeds session from request auth context | `backend/app/communication_hub/mcp/streamable_http.py` |
| `handle_sse_open` / `handle_sse_message` | function | SSE transport endpoints sharing the same session/authorization semantics | `backend/app/communication_hub/mcp/sse_transport.py` |
| `register_mcp_protocol_server` | function | Registers the `/mcp` protocol router (gated by a settings flag) | `backend/app/communication_hub/mcp/router.py` |
| `ApiKeyAuthMiddleware` | class | Existing API-key auth on `/mcp*` paths (validates via CC, seeds auth context); the parallel pattern for the OAuth path | `backend/app/communication_hub/middleware/api_key_auth.py` |
| `OAuthBearerAuthMiddleware` | class (new) | OAuth/OIDC Bearer-token auth on `/mcp*` paths, resolving the user's identity, permission scope, and tenant into the MCP session | `backend/app/communication_hub/middleware/oauth_bearer_auth.py` (new) |
| `SystemTool` | class | Descriptor for a built-in system tool (name, schema, CC endpoint path, stable UUID) | `backend/app/services/agents/system_tool_registry.py` |
| `invoke_management_tool` | system tool (new) | Progressive-disclosure wrapper: dispatches any registered management tool via `management_tools._dispatch`, re-authorizing parity per invocation | `backend/app/services/agents/system_tool_registry.py` + `backend/app/api/v1/internal/management_tools.py` |
| `invoke_management_tool_meta` | function (new) | CC handler for the wrapper (literal route `/internal/management-tools/invoke_management_tool`); structured 404 for unknown/delete-shaped targets, 403 parity denials | `backend/app/api/v1/internal/management_tools.py` |
| `get_management_tool_schema_meta` | function (new) | CC handler: full OpenAI schema for one management tool, on demand | `backend/app/api/v1/internal/management_tools.py` |
| `list_management_tools_meta` | function (new) | CC handler: cheap catalog (name + description + permission requirement) | `backend/app/api/v1/internal/management_tools.py` |
| `search_assistant_knowledge_meta` | function (new) | CC handler: keyword search over the knowledge corpus (tenant-agnostic, read-only) | `backend/app/api/v1/internal/management_tools.py` |
| `get_meta_tool_names` | classmethod (new) | Bare names of the constant meta tools the assistant context loads (never in the parity map) | `backend/app/services/agents/system_tool_registry.py` |
| `search_knowledge` | function (new) | Deterministic keyword-scored search over the platform rule corpus | `backend/app/services/agents/assistant_knowledge.py` (new) |
| `_KNOWLEDGE_ENTRIES` | constant (new) | The structured domain-rule corpus (`{id, topic, keywords, rule_text}`) | `backend/app/services/agents/assistant_knowledge.py` (new) |
| `SystemToolRegistry` | class | Single source of truth for system tools; derives schemas, routing, seeding, name validation | `backend/app/services/agents/system_tool_registry.py` |
| `register` | classmethod | Registers a system tool (raises on duplicate name) | `backend/app/services/agents/system_tool_registry.py` |
| `get_cc_endpoint_map` | classmethod | Returns `{bare_name: cc_url}` for CommHub routing | `backend/app/services/agents/system_tool_registry.py` |
| `get_all_schemas` | classmethod | OpenAI function schemas for every tool (AR tool loader source) | `backend/app/services/agents/system_tool_registry.py` |
| `get_mcp_hub_entries` | classmethod | Data dicts for MCP Hub UI / DB seeding | `backend/app/services/agents/system_tool_registry.py` |
| `canonical_name` | property | Full `system____<name>` form of a tool | `backend/app/services/agents/system_tool_registry.py` |
| `parity` | field | Optional `(resource_type, action)` attached to management tools (absent for plain system tools) | `backend/app/services/agents/system_tool_registry.py` |
| `is_management_tool` | property | `True` when a `SystemTool` carries a permission parity mapping | `backend/app/services/agents/system_tool_registry.py` |
| `get_parity_map` | classmethod | `{bare_name: (resource_type, action)}` for management tools — single source of truth for permission parity | `backend/app/services/agents/system_tool_registry.py` |
| `get_management_tool_names` | classmethod | Bare names of every registered management tool | `backend/app/services/agents/system_tool_registry.py` |
| `is_management_tool` | classmethod | `True` when a name refers to a registered management tool (bare or canonical) | `backend/app/services/agents/system_tool_registry.py` |
| `SystemToolRequest` | class | Pydantic request body for an internal system-tool call | `backend/app/api/v1/internal/system_tools.py` |
| `SystemToolResponse` | class | Pydantic response envelope (`result` dict) for system tools | `backend/app/api/v1/internal/system_tools.py` |
| `ManagementToolRequest` | class (new) | Pydantic request body for a management-tool call (`session_id`, `user_sub`, `tool_args`) | `backend/app/api/v1/internal/management_tools.py` (new) |
| `ManagementToolResponse` | class (new) | Pydantic response envelope (`result` dict) for management tools | `backend/app/api/v1/internal/management_tools.py` (new) |
| `ManagementResolveRequest` / `ManagementResolveResponse` | classes (new) | Resolve an OAuth user's identity, tenant and permitted management tools | `backend/app/api/v1/internal/management_tools.py` (new) |
| management tool handlers | endpoints (new) | CC write/read-path handlers for the management tools (create/update/list/get, no delete) + `POST /resolve` | `backend/app/api/v1/internal/management_tools.py` (new) |
| `PermissionEngine` | class | Evaluates IAM-style policy statements; deny-by-default authorization | `backend/app/services/permissions/permission_engine.py` |
| `AuthorizationResult` | class | Result of an authorization check (`allowed`, `reason`) | `backend/app/services/permissions/permission_engine.py` |
| `authorize_identity` | function | Shared permission gate: resolves `PlatformUser` by `sub` and evaluates membership + policies | `backend/app/api/deps.py` |
| `require_permission` | dependency | Dependency factory enforcing `(module, action)` via `PermissionEngine` for REST endpoints | `backend/app/api/deps.py` |
| `require_service_certificate` | dependency | Enforces a valid service certificate on `/internal/*` endpoints (fail-closed 401/403) | `backend/app/api/deps.py` |
| `require_internal_tenant_context` | dependency | Verifies HMAC-signed `X-Internal-Tenant-*` headers; binds root tenant in single-tenant mode | `backend/app/api/deps.py` |
| `_CH_ALLOWLIST` | constant | Allowlist of internal endpoints callable by Communication Hub's service cert | `backend/app/api/deps.py` |
| `ResourceTypeManifest` | constant | Maps each `module::submodule` resource type to its allowed actions | `backend/app/core/resource_types.py` |
| `MODULE_GROUPS` | constant | Groups resource types by module (`agent`/`integration`/`system`/`platform`/`tenant`) | `backend/app/core/resource_types.py` |
| `RT_AGENT` / `RT_AGENT_SKILLS` / `RT_AGENT_SOPS` / `RT_AGENT_SCHEDULES` / `RT_AGENT_DATA_TYPES` / `RT_INTEGRATION_MCP_HUB` | constants | Resource-type identifiers used by the parity map | `backend/app/core/resource_types.py` |
| `websocket_chat` | endpoint | WebSocket chat endpoint for conversational agents | `backend/app/api/ws/chat.py` |
| `WebSocketServer` | class | WS auth + connection handling for chat sessions | `backend/app/api/ws/chat.py` |
| `_process_message` | function | Persists turn, dispatches to AR, persists agent reply | `backend/app/api/ws/chat.py` |
| `_call_llm` / `_delegate_conversation_turn_to_agent_runtime` | function | Delegate one conversational turn to AR's deep-agent framework | `backend/app/api/ws/chat.py` |
| `_bind_connection_tenant_context` / `_resolve_oidc_tenant_slug` | function (new) | WS connect-time tenant binding: platform-token slug path unchanged; OIDC tokens (no `tenant` claim) resolved server-side from the user's active membership (same mechanism as REST `/auth/tenant-memberships`); fail-closed 4003 when unresolvable under multi-tenancy | `backend/app/api/ws/chat.py` |
| `_send_to_live_socket` | function (FIX-20261031-071721 defect-1 follow-up) | Routes ALL reply/turn WS sends (agent reply, `chat_status`, `title_update`, `guardrail_update`, `chat_error`, `chat_blocked`, intervene status) through `ActiveSessionTracker.get_ws(session_id)` at SEND time instead of the socket captured at connection start — after a mid-turn disconnect+reconnect (same session id) the live reply reaches the NEW socket; falls back to the captured socket when the tracker has no entry; send failures logged + swallowed (never crash the turn pipeline). Persistence unchanged. `ActiveSessionTracker.unregister(session_id, websocket)` is now identity-checked so the old connection's cleanup cannot evict a reconnect's registration | `backend/app/api/ws/chat.py` |
| `run_conversation_turn` | function (new, FIX-20261031-091657) | Whole-turn watchdog wrapper replacing the inline `_run_turn_and_reply`: the ENTIRE turn (incl. the AR streaming delegation whose HTTP timeout is deliberately disabled) is bounded by `agent_question_timeout_seconds` via `asyncio.wait_for`. On watchdog fire (or end-session cancellation) it emits `timeout_or_failed`, delivers a clear persisted error message and dedupes (a delivered reply is never followed by a duplicate error; the error turn is persisted at most once). Also runs the `thinking_heartbeat` keepalive loop (every 15s while the turn is in flight) so proxies stay open and the UI keeps "thinking" alive. The live agent reply is delivered via the `on_reply` hook BEFORE persistence, so a slow persistence tail can never delay or swallow it | `backend/app/api/ws/chat.py` |
| `cancel_pending_conversation_turn` | function (new, FIX-20261031-091657) | Cancels the per-session pending turn task registered by `websocket_chat`; called by CH's `/internal/agent/terminate/{id}` forwarding so ending a session unblocks the WS turn immediately | `backend/app/api/ws/chat.py` |
| `terminate_in_flight_conversation_execution` | function (new, FIX-20261031-091657) | Best-effort termination of any in-flight execution bound to a conversation session: `POST /conversations/{id}/end` reuses the existing CC → CH (`/internal/agent/terminate/{id}`) → AR (`/terminate/{id}`) machinery; strictly logged best-effort — never fails the end call | `backend/app/services/conversations/termination.py` (new), `backend/app/api/v1/conversations.py` |
| `conversation_tasks` registry | mechanism (new, FIX-20261031-091657) | AR registers in-flight streaming conversation turn tasks on `app.state.conversation_tasks` (keyed by conversation session id); AR `/terminate/{id}` cancels them, closing the hung-turn gap | `backend/app/agent_runtime/api/conversation.py`, `backend/app/agent_runtime/api/terminate.py` |
| `conversation_llm_timeout_seconds` | setting (new, FIX-20261031-091657) | Hard bound (default 120s) for one conversational LLM completion: applied as an asyncio bound around the conversational agent invocation AND as the LangChain client `request_timeout`/`timeout` (ChatOpenAI / AzureChatOpenAI / ChatAnthropic). On timeout the executor returns `timeout_or_failed` + a clear persisted error message instead of hanging forever | `app/core/config.py`, `app/services/agents/runtime_executor.py`, `app/services/agents/langchain_model_factory.py` |
| `cache_user_jwt` / `get_user_jwt` | function | Cache/resolve the user's JWT per session, enabling the chatbot to act with the user's identity | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `AgentType` | model | Agent definition entity; gains `is_system` flag | `backend/app/db/models/agents.py` |
| `PlatformUser` | model | Platform user resolved by OIDC `sub`; target of `PermissionEngine` authorization | `backend/app/db/models/platform_user.py` |
| `Skill` | model | Named invocable unit wrapping tool bindings; has `is_system` | `backend/app/db/models/skills.py` |
| `Sop` | model | Standard Operating Procedure composing skills with sequencing | `backend/app/db/models/skills.py` |
| `ConversationSession` | model | Conversation context and attribution (audit trail) | `backend/app/db/models/conversations.py` |
| `ConversationTurn` | model | A single message in a conversation | `backend/app/db/models/conversations.py` |
| `ToolCallRecord` | model | Per-turn record of a tool invocation (audit trail) | `backend/app/db/models/conversations.py` |
| `SkillSeeder` | class | Idempotent seeder for system skills derived from `SystemToolRegistry` | `backend/app/services/skill_seeder.py` |
| `AssistantSeeder` | class (new) | Idempotently seeds the assistant `AgentType` and management tool bindings for every tenant (no model binding). Since FIX-20261031-035145 it also **self-seeds** the per-tenant management `McpTool` rows (`_ensure_management_tool_rows`: deterministic uuid5 ids from `mcp_hub_id`+tenant, plus an on-demand per-tenant mirror of the reserved `system` MCP server) — no dependency on another seeder | `backend/app/services/agents/assistant_seeder.py` (new) |
| `get_agent_context` (role-less branch) | endpoint logic (FIX-20261031-035145) | For agent types WITHOUT a role (e.g. the conversational assistant), resolves tools from the agent type's DIRECT `AgentTypeSkillBinding` → `SkillToolBinding` → `McpTool` graph (tenant-scoped, canonical `system____*` names) so the conversational delegation context carries real tools instead of an empty toolset | `backend/app/api/v1/internal/agent_data.py` |
| `_resolve_capability_ids` / `_bind_agent_type_capabilities` | functions (FIX-20261031-071721 defect 2) | Agent-type skill/SOP association in the management toolset: `create_agent_type` / `update_agent_type` `data` may include `skill_ids` / `sop_ids` (id or name, tenant-scoped); values are resolved BEFORE any write (unknown → structured 404, no partial write); bindings are **additive merge** — provided entries added, existing bindings never removed, re-binding an existing pair is an idempotent no-op; new bindings follow the `order` convention (0-based, appended after current max). Parity unchanged (`agent:create` / `agent:update`); tool schemas enriched in `SystemToolRegistry` (stable UUIDs kept) | `backend/app/api/v1/internal/management_tools.py` |
| `resolve_cert_path` / `ensure_cert_files_exist` / `BACKEND_ROOT` | module (FIX-20261031-131030 defect 1) | **CWD-independent certificate path resolution**: relative cert paths (`.env` `CC_CERT_PATH`/`CC_KEY_PATH`, `COMM_HUB_CERT_PATH`, `AGENT_CERT_PATH`, `CA_CERT_PATH`, `certs/control-center/…` defaults) anchor to the backend repo root (`Path(__file__).resolve().parents[2]`) instead of the process working directory; absolute paths / explicit absolute env config pass through untouched. `ensure_cert_files_exist` raises `CertValidationError` with an actionable message when a resolved cert file is missing. Used by CH/AR certificate managers, `cc_service_cert_renewal` (DEFAULT_CERT_DIR), and the CC outbound `CommunicationHubClient`/`AgentRuntimeClient` | `backend/app/core/cert_paths.py` (new) |
| `_load_certificate` (CH/AR mains) | startup hook (FIX-20261031-131030 defect 1) | **Fail-fast startup cert validation**: a missing/unloadable service or agent certificate raises a `RuntimeError` ("… startup FAILED", resolved cert path, required env vars, root error) instead of the previous silent warn-and-continue (`certificate_manager = None`) that broke chat lazily at LLM-call time while health probes stayed green | `backend/app/communication_hub/main.py`, `backend/app/agent_runtime/main.py` |
| `_bind_agent_role_capabilities` | function (FIX-20261031-131030 defect 2) | **Role skill/SOP grants in the management toolset**: `create_agent_role` / `update_agent_role` `data` may include `skill_ids` / `sop_ids` (id or name, tenant-scoped, via `_resolve_capability_ids`). ADDITIVE MERGE — grants added, existing grants never removed, re-grant idempotent no-op; whole set resolved before any write (unknown → structured 404 "Create the skill first (create_skill)…", no partial write). Writes `AgentRoleSkill` / `AgentRoleSOP` — the rows role-based agents resolve runtime tool access from. Parity unchanged (bare `agent` create/update, same as agent types/identities/model configs) | `backend/app/api/v1/internal/management_tools.py` |
| `get/put_assistant_model_config` | endpoint (new) | Per-tenant assistant model selection: options from the tenant's Model Configurations, selection persisted onto the tenant's assistant `AgentType.model_id` (`require_permission(RT_AGENT, "read"/"update")`) | `backend/app/api/v1/agents.py` (next to the workflow-generation endpoints) |
| `TenantSetting` | model (new) | Tenant-scoped key/value settings store (`tenant_settings`, unique `(tenant_id, key)`, FK tenants with CASCADE); unlike `PlatformSetting` it is per-tenant, not global | `backend/app/db/models/tenant_setting.py` (new) |
| `get_value` / `set_value` | functions (new) | Typed async tenant-scoped settings read/upsert helpers | `backend/app/services/tenancy/tenant_settings_service.py` (new) |
| `get/set_workflow_generation_model_id` | functions (rewritten) | Workflow-generation model selection is now DB-backed and per-tenant: resolved/persisted for the SESSION tenant (root tenant when multi-tenancy is off) under key `workflow_generation_model_id`; previously a single global value in `config/app.yaml` | `backend/app/services/agents/workflow_generation_settings.py` |
| `adopt_legacy_app_yaml_value` | function (new) | One-time idempotent startup adoption of the legacy app.yaml global selection into the ROOT tenant's row (never overwrites an existing selection; yaml value left in place); wired into CC startup next to `AssistantSeeder` | `backend/app/services/agents/workflow_generation_settings.py`, `backend/app/main.py` |
| Migration `6fba31147599` | migration (new) | Creates `tenant_settings` (revises `1a0ed55b8cf1`) | `backend/alembic/versions/6fba31147599_add_tenant_settings_table.py` |
| `SystemConfigPage` (workflow + assistant sections) | component | Both model selectors are per-workspace: workflow-generation now persists to the current tenant's `TenantSetting` row (same REST contract as before) | `frontend/src/pages/system/SystemConfigPage.tsx` |
| `ConversationDialog` | component | Reused conversational UI surface for the assistant; `assistantModelConfigCheck` gate renders the model-unconfigured guidance Alert ("Configure model" → `/system-config`) and disables input. Assistant/agent messages render via `ContentRenderer` in `auto` mode (sanitized HTML or formatted markdown); user messages stay plain-text bubbles. FIX-20261031-071721: watches `recoveryEpoch` from `useChatSession` and after a mid-turn WS reconnect re-fetches `POST /conversations/{id}/resume`, merging persisted turns via `mergeUnseenMessages` (dedupe against rendered + live messages) so a reply generated during the outage renders live; resume effect guarded against double-POST | `frontend/src/components/agents/ConversationDialog.tsx` |
| `ContentRenderer` (chat integration) | component | Auto-detects markdown vs HTML for agent replies in the conversation bubbles — headings, code blocks, links, lists and tables render formatted; HTML is DOMPurify-sanitized; empty content renders nothing | `frontend/src/components/ContentRenderer.tsx` |
| `openAssistant` | function (new) | Assistant launch handler: fetches the user's conversation sessions for the assistant agent type (`GET /conversations?agent_type_id=…`), picks the most recent `status === 'active'` session by `updated_at` (tenant/user scoping done server-side), and opens the dialog with that `sessionId`; falls back to a new session on empty result or error; dialog mounts only after resolution | `frontend/src/app/AppShell.tsx` |
| `useAssistantModelConfig` | hook (new) | Typed react-query hook for `GET /agents/model-configs/assistant-model`; `selected_model_id: null` drives the setup guidance | `frontend/src/hooks/useAssistantModelConfig.ts` |
| `useChatSession` | hook | WebSocket lifecycle + message/status/guardrail state for chat; parses structured `chat_error` payloads into `chatError` state. FIX-20261031-071721: unexpected WS close while a turn is in flight schedules auto-reconnect with the same session id (max 5 attempts, `intentionalCloseRef` guards unmount) and bumps `recoveryEpoch` on reconnect so consumers can recover missed replies | `frontend/src/hooks/useChatSession.ts` |
| `ConversationTurnError` | class (new) | Typed conversation-turn failure carrying a stable `code` + human `message` | `backend/app/api/ws/chat.py` |
| `_conversation_turn_error_from_http_status` | function (new) | Maps AR's pre-model 400 "Agent model is not configured" onto `assistant_model_not_configured` | `backend/app/api/ws/chat.py` |
| `useAgentTypes` | hook | Fetches agent types (used to resolve the assistant entry point) | `frontend/src/hooks/useAgentTypes.ts` |
| `apiClient` | client | Frontend HTTP client for REST calls | `frontend/src/api/apiClient.ts` |
| `RESOURCE_TYPE_MANIFEST` | constant | Frontend mirror of the resource-type manifest | `frontend/src/constants/resourceTypes.ts` |

## 7. FIX-20261031-133253 — Mandatory confirmation before create/update + agent-creation completeness

### Confirmation contract

Before ANY `invoke_management_tool` call whose wrapped action is a CREATE or an UPDATE (read/list/get unaffected), the assistant MUST: (1) build the exact payload; (2) present a markdown TABLE preview (operation, resource type, name, every field → value; updates: field-by-field old → new); (3) call `human_intervene(intervention_type="approval", prompt=<the table>)` and WAIT; (4) execute only if approved. Rejection → do not execute, ask what to change. For agent-type creation the preview MUST show model, identity, role, skills, and grants; an agent type without a working model AND (an identity or a role) is non-functional and is never created — the agent-type facts (`list_agent_identities` / `list_agent_roles` / `list_model_configs`, capabilities granted at the level the configuration consumes them) live in knowledge (`agent-creation-completeness`, `confirm-before-write`, `creation-payload-completeness`, `resource-completeness`, `prerequisite-ordering`) and in the assistant instruction (rules 2d/2e) plus the management skill digest. **FIX-20261102-100704**: these are reference facts + generic principles, not a scripted sequence — see §15.

### Design

- **Exposure** — `human_intervene` is the 5th entry in `SystemToolRegistry._META_MANAGEMENT_TOOL_NAMES`: the role-less assistant context (`agent_data.get_agent_context`) always loads its definition, `AssistantSeeder` provisions + binds its per-tenant `McpTool` row, and CH `tool_routing` forwards the signed-in user's `sub` for meta tools (parity map untouched — `human_intervene` carries no parity).
- **Conversational HITL** — `LangChainHumanInterveneTool`, when running a conversational turn (`conv_session_id` set), registers in `app/agent_runtime/conversation_resume.py` (in-process, keyed by conversation session) and awaits the operator INSIDE the tool call. CC persists the `InterveneRequest` (nullable `agent_session_id` — migration `a1c3e5d70427`; conversation-scoped requests carry `conversation_session_id`) and dispatches `intervene_request` over the existing CH intervention router to the chat WebSocket. The operator's `intervene_response` → CC `/internal/data/intervene/respond` → AR `/internal/resume`, which resolves the registry future FIRST (job-relaunch fallback unchanged). The tool returns the operator's response — or `status:"timeout"` ("operation was NOT executed") — as its tool result; no LangGraph `interrupt()` on the conversational path (its Command-resume replay re-registered duplicate requests). Task agents keep the existing interrupt flow unchanged.
- **Timeout co-existence (FIX-091657)** — the strict `conversation_llm_timeout_seconds` bound still fires for hanging providers; while `conversation_resume.is_pending(conv)` the executor re-arms the wait up to `conversation_intervention_timeout_seconds` (new setting, default 240s — below the CH turn watchdog). CC replay idempotency: a repeated `human_intervene` with the same conversation+reason returns the pending request deduped, or — if already responded — the stored operator response, so any replayed tool call completes without re-interrupting.
- **Frontend** — `InlineInterventionDialog` renders `reason` through `ContentRenderer` (auto mode → remark-gfm), so markdown table previews render as real tables; Approve/Deny still emit the existing `intervene_response` WS message flow.

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `human_intervene` (meta) | system tool | 5th always-loaded assistant meta definition (approval/choice/text; routes to the existing CC `/internal/system-tools/human-intervene`; AR wrapper maps it to the HITL tool) | `backend/app/services/agents/system_tool_registry.py` |
| `conversation_resume` | module (new) | In-process pending-intervention registry for conversational turns (`register` / `resolve` / `is_pending` / `wait_for_resume`) | `backend/app/agent_runtime/conversation_resume.py` (new) |
| `resume_session` (conversational branch) | endpoint change | Resolves a pending conversational intervention before the job-relaunch fallback | `backend/app/agent_runtime/api/intervene.py` |
| `human_intervene_tool` (conversation + replay support) | endpoint change | Conversation-only sessions accepted (nullable `agent_session_id`); prompt folded into reason; replay idempotency (pending dedupe / responded returns operator response) | `backend/app/api/v1/internal/system_tools.py` |
| `LangChainHumanInterveneTool` (conversational wait) | tool change | Conversational turns await `conversation_resume` instead of `interrupt()`; timeout → explicit not-executed result | `backend/app/services/agents/langchain_system_tools.py` |
| `InterveneRequest.agent_session_id` (nullable) | model + migration | Conversation-scoped requests carry NULL + `conversation_session_id` (revises `6fba31147599`) | `backend/app/db/models/intervene.py`, `backend/alembic/versions/a1c3e5d70427_conversation_scoped_intervene_requests.py` |
| `confirm-before-write` / `agent-creation-completeness` / `creation-payload-completeness` | knowledge entries (new) | The confirmation rule and the completeness workflows, retrievable via `search_assistant_knowledge` | `backend/app/services/agents/assistant_knowledge.py` |
| `ASSISTANT_SYSTEM_INSTRUCTION` rules 2d/2e, `MANAGEMENT_SKILL_INSTRUCTIONS` | constants | Always-on instruction digest; single shared skill-instruction constant so pre-fix seeded rows refresh on restart | `backend/app/services/agents/assistant_seeder.py` |
| `InlineInterventionDialog` (ContentRenderer) | component change | Markdown (table) preview rendering in the intervention surface | `frontend/src/components/conversations/InlineInterventionDialog.tsx` |
| `fix-20261031-133253-live.cjs` | script (new) | Live WS verification of the full confirmation round-trip (scripted LLM mock) | `scripts/fix-20261031-133253-live.cjs` |

## 8. FIX-20261101-000319 — `cc____` namespace, Control Center MCP entity, and Skill↔tool bindings

### Design

**Naming / permission model.** `SystemTool` gains `category` (`"general"` | `"management"`). The 36 management execution tools (create/update/list/get × 9 families) and the 4 management meta tools (`invoke_management_tool`, `get_management_tool_schema`, `list_management_tools`, `search_assistant_knowledge`) are `category="management"` and surface canonically as `cc____<bare>`; ALL other tools keep `system____<bare>` untouched (`save_data`, `get_data`, `get_output`, `query_result`, `send_notification`, `get_recipient_group`, `human_intervene`, optimization/script tools). `decision____` untouched. `cc` is a reserved server slug (`RESERVED_SERVER_NAMES`), so no custom MCP server can collide. Parity per (resource_type, action) is UNCHANGED — only the namespace and entity moved.

**Control Center MCP entity.** Every tenant gets its own "Control Center" `McpServer` (slug `cc`, deterministic uuid5 id `parthenon:cc-server:<tenant_id>` — a NEW reserved identity, never the System server's `…0001`) hosting per-tenant `cc____<bare>` `McpTool` rows (deterministic uuid5 from the stable registry `mcp_hub_id` + tenant, same convention as before). `get_mcp_hub_entries()` (generic System entity seeding/UI) now returns GENERAL tools only; `get_cc_mcp_hub_entries()` is the CC entity's catalog. `human_intervene` (a general meta tool) keeps a `system____`-named per-tenant row on the CC server purely as a binding anchor — routing always goes by bare name through `get_cc_endpoint_map`.

**Migration (idempotent, rows are data — no schema migration).** `AssistantSeeder._retire_legacy_management_rows` deletes every tenant `McpTool` row still named `system____<mgmt>` (and any `SkillToolBinding` referencing it), then `_ensure_management_tool_rows` provisions the `cc____` rows and `_ensure_skill_bindings` rebinds the management skill to them. General `system____` rows are never touched. `seed_system_tools` retires the global System entity's legacy rows (pure SQL — reserved all-digit UUIDs coerce to INTEGER under SQLite's NUMERIC affinity) with the same idempotency.

**Grantability / routing.** `cc____*` tools are first-class grantable tools: the OAuth resolve endpoint returns `cc____` canonical names (per-tool parity evaluation unchanged), the bridge lists them exactly when granted (ungranted → not listed; direct call → structured denial for OAuth, `PermissionError` for API keys), and dispatch routes them to the management handler WITH parity re-enforcement (`_authorize` per call, delete-shaped requests declined). `system____` routing is unchanged; `is_system_tool` accepts both namespaces so CH's internal routing treats `cc____` as the built-in system path.

**Skill ↔ tool association.** `create_skill` / `update_skill` `data` accepts `tool_ids` (McpTool UUIDs) and/or `tool_names` (canonical `server____tool` names — including `cc____` — or bare original names): create = bind all; update = ADDITIVE MERGE (existing bindings never removed, re-bind idempotent no-op); the WHOLE set is resolved within the tenant BEFORE any write (unknown → structured 404 with an actionable message, no partial write). Tool discovery: `get_mcp_server` now returns the server's synced `tools` (canonical names) so the assistant can find e.g. the supabase server's tool names before creating the skill.

**Assistant context.** The role-less context uses category-aware canonical names (`cc____` meta + `system____human_intervene`), emits sanitised canonical definitions (`cc__invoke_management_tool` — OpenAI-safe) and a populated `tool_name_map`; the `human_intervene` HITL special-case in the tool wrapper matches the sanitised canonical name so the confirmation/HITL flow is unchanged. New knowledge rule `skill-tool-binding` + instruction rules (2f / skill instructions) pin the workflow: discover the server's tools with `get_mcp_server`, bind at creation via `tool_names`, skills without bindings cannot do anything, `cc____` tools are granted deliberately via the Control Center entity.

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `SystemTool.category` / `server_slug` / `canonical_name` | field/property (changed) | Category-aware namespace: management → `cc____<bare>`, general → `system____<bare>` | `backend/app/services/agents/system_tool_registry.py` |
| `get_cc_mcp_hub_entries` | classmethod (new) | Data dicts for the Control Center entity's management + meta tools (`cc____<bare>`) | `backend/app/services/agents/system_tool_registry.py` |
| `is_cc_tool` (registry + tool_naming) | classmethod/function (new) | `True` for `cc____`-namespaced management tools | `backend/app/services/agents/system_tool_registry.py`, `backend/app/services/agents/tool_naming.py` |
| `RESERVED_SERVER_NAMES` / `CC_SERVER_SLUG` | constant (changed) | `{"system", "decision", "cc"}` | `backend/app/services/agents/tool_naming.py` |
| `_tenant_cc_server_id` | function (new) | Deterministic per-tenant "Control Center" McpServer id (uuid5 `parthenon:cc-server:<tenant>`) | `backend/app/services/agents/assistant_seeder.py` |
| `_retire_legacy_management_rows` | function (new) | Deletes legacy `system____<mgmt>` rows + bindings per tenant (idempotent migration) | `backend/app/services/agents/assistant_seeder.py` |
| `_resolve_skill_tool_ids` / `_bind_skill_tools` | functions (new) | Skill↔tool binding resolution (tenant-scoped, resolve-before-write, 404 no-partial-write) + additive merge binding | `backend/app/api/v1/internal/management_tools.py` |
| `get_mcp_server` (tools list) | handler change | Returns the server's synced tools (canonical names) for discovery | `backend/app/api/v1/internal/management_tools.py` |
| `_management_scope_denial` (cc) | function (changed) | Handles `cc____` prefix for delete/out-of-scope declines | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `_enrich_skill_tool_binding_schemas` | function (new) | `create_skill`/`update_skill` schema documents `tool_ids`/`tool_names` | `backend/app/services/agents/system_tool_registry.py` |
| `skill-tool-binding` | knowledge entry (new) | The binding rule (discover → bind at creation; no bindings → inert; `cc____` = deliberate grants) | `backend/app/services/agents/assistant_knowledge.py` |
| `fix-20261101-000319-live.cjs` | script (new) | Live WS verification: create-a-bound-skill turn + REST binding check + no-grant role check | `scripts/fix-20261101-000319-live.cjs` |

Tests: `tests/unit/test_cc_naming.py`, `tests/unit/test_cc_seeder_migration.py`, `tests/unit/test_cc_tool_registry_bridge.py`, `tests/unit/test_skill_tool_bindings_management.py`; prior-fix suites updated to the new canonical names.

## 9. FIX-20261101-014511 — `integration::control_center` entity-view permission

The per-tenant Control Center MCP entity (slug `cc`, seeded by `assistant_seeder.py`) is a PROTECTED integration: the permission system controls WHO CAN VIEW it and who can define anything around it (tool grants, configuration).

### Permission model
- New resource type **`integration::control_center`** with actions `["read", "manage"]`:
  - `read` — see the CC entity and its tools (MCP Hub REST list/detail, cc tool listing, management toolset reads).
  - `manage` — define/configure around it: update/delete/sync/rebind the entity, its sessions and OAuth configuration, and grant/revoke its tools to roles.
- **Deny-by-default** — the PermissionEngine rejects unknown/ungranted types. Existing wildcards (`integration::*`, `*::*`) cover admin roles because the RT is registered in `MODULE_GROUPS["integration"]`. No special seeding.
- **Dual registration convention (CRITICAL)** — the RT is registered in BOTH `backend/app/core/resource_types.py` (manifest + module group) AND `frontend/src/constants/resourceTypes.ts` (`RESOURCE_TYPE_MANIFEST` + `integrations` submodules). Missing either side yields 403-for-everyone; `ResourceTypeManifestMirror.test.ts` pins the mirror.

### Enforcement points
1. **MCP Hub REST (`backend/app/api/v1/mcp_hub.py`)** — `_gate_cc_server` / `_require_cc_permission` / `_cc_tool_gate` (non-raising probe via the new `identity_has_permission` in `app/api/deps.py`):
   - `GET /mcp/servers` filters the `cc` row out for callers without `read`.
   - `GET /mcp/servers/{id}` and `GET /mcp/servers/{id}/tools` → **404-without-leak** for `cc` without `read`.
   - `PUT`/`DELETE`/`POST .../sync`/OAuth authorize on `cc`, and every `cc` session mutation (create/update/delete/refresh-token) → **structured 403** (`PermissionDeniedDetail` with `required_permission.resource_type = integration::control_center`, `action = manage`) without `manage`.
   - Tool-grant surface on `cc` tools: `GET .../permissions` needs `read`; `POST`/`DELETE` grants need `manage` (structured 403).
   - Non-`cc` servers behave exactly as today (plain `integration::mcp_hub` rules).
2. **Management toolset (`backend/app/api/v1/internal/management_tools.py`)** — evaluated against the TRIGGERING USER (`body.user_sub`): `list_mcp_servers` omits the `cc` entity and `get_mcp_server(cc)` returns 404-without-leak when the user lacks `read` (the assistant acts with the user's scope; the wrapper/parity path is unchanged).
3. **Frontend (`frontend/src/pages/mcp/McpHubPage.tsx`)** — the API-filtered list hides the card entirely without `read`; when present, the row carries a "Control Center" protected chip (i18n `mcp.controlCenter.*`), and row-level action errors (delete/sync 403) surface via the standard `PermissionDeniedAlert` — never a raw 403 crash.
4. **External MCP protocol surface** — UNCHANGED: `tools/list` / `tools/call` remain controlled by role tool-grants + parity. The entity-view permission governs the MCP Hub ADMIN surface, not tool invocation (that is parity + grants).

Tests: `backend/tests/unit/test_cc_integration_permission.py`, updated manifest fixtures, and the `McpHubPage` gating tests in `frontend/src/__tests__/McpHubPage.test.tsx`.

## 10. FIX-20261101-090438 — cc entity lifecycle: system-managed + sessionless

The Control Center MCP entity (slug `cc`) is PLATFORM-PROVISIONED: the per-tenant seeder is its
only writer, and it is idempotent (drifted name/description/base_url/status are refreshed at seed
time; the slug can never drift — the router reserves it).

- **Marking convention** — no new DB column. The existing reserved-slug convention is the marker:
  `SYSTEM_MANAGED_SERVER_SLUGS = {"system", "decision", "cc"}` (`app/db/models/mcp_hub.py`).
  `McpServerRead.is_system_managed` (derived from the slug) exposes the flag on every read.
- **Immutability (unconditional)** — server update / delete / sync / OAuth authorize on the cc
  entity return structured `403 {"code": "system_managed_integration", ...}` for EVERYONE
  (including `integration::control_center:manage` holders and `integration::*` wildcards). The
  `_reject_cc_mutation` guard runs BEFORE the FIX-014511 manage gate — immutability is not a
  permission question. **Tool grants onto cc tools are exempt** — still governed solely by the
  FIX-014511 read/manage gate.
- **Sessionless** — MCP sessions don't apply to cc (access flows through role/skill grants):
  session create/update/delete/refresh-token → structured 403 "Sessions are not supported for the
  Control Center integration". Session LIST stays allowed (harmless).
- **Frontend** — `McpHubPage` renders a "System-managed" chip (`mcp.controlCenter.systemManaged`)
  on the cc row (API flag with slug fallback), hides edit/delete/sync/sessions controls, keeps the
  grant-related controls for manage holders.

Tests: `backend/tests/unit/test_cc_integration_permission.py` (TestCcSystemManagedImmutable,
TestSystemManagedFlag), `frontend/src/__tests__/McpHubPage.test.tsx` (cc gating block).

## 11. FIX-20261101-111439 — assistant iteration budget + guardrail error clarity + chat action bar

### Backend

- **Iteration budget** — `ASSISTANT_GUARDRAIL_MAX_ITERATIONS = 24` in `assistant_seeder.py`;
  set on create and refreshed on existing seeded rows (update branch diffs the field). The
  documented agent-creation workflow needs 11+ tool iterations (3 discovery lists + optional
  tool-schema lookup → create_skill → identity/role creation + role grant → create_agent_type);
  24 ≈ 2× headroom over the observed 11/10 exhaustion. The value flows per agent type via
  `GET /internal/data/agent-context` (`guardrail_policy.max_iterations`) into
  `RuntimeGuardrailState` (`runtime_executor._build_guardrail_state`); both `GuardrailCallback`
  and the inline executor checks read it — no schema change.
- **Guardrail stop surfacing** — AR `agent_runtime/api/conversation.py` forwards the stop reason
  + details on the NDJSON error chunk (`{"type": "error", "error_type", "error_details"}`).
  CH `api/ws/chat.py` maps `iteration_limit` to
  `ConversationTurnError("iteration_limit", "This task needed more steps than allowed (limit N).
  Try breaking it into smaller requests or ask an administrator to raise the step limit.")`
  (other guardrail reasons → `guardrail_<reason>` + generic message), and
  `run_conversation_turn` persists the clear error turn via
  `_persist_and_surface_turn_error(..., status_value=<code>)` (the `timeout_or_failed`
  structured-error pattern).

### Frontend

- `ConversationDialog.tsx` footer is a 4-option action bar (all conversational agents):
  **View All Sessions** (`SessionSwitcherList` reuses the `useConversationSessions` query;
  Resume → `POST /conversations/{id}/resume` in-place via `handleSwitchToSession`), **New
  Session** (`handleStartNewSession`: `resetForSessionSwitch()` clears messages/delegation/
  guardrail state, then `POST /conversations` — the previous session stays `active`, the
  end/archive API is never called, no force-new flag), **End Session** (unchanged: end mutation
  + `markAssistantSessionEnded` + close), **Exit** (unchanged `onClose`). Switch/end are blocked
  while `turnStreaming` (thinking/delegating/waiting/using_tool/waiting_for_human/
  delegation_resumed, pending question, intervention, or resuming).

Code Reference Map additions:

| Symbol | Kind | Purpose | Path |
|---|---|---|---|
| `ASSISTANT_GUARDRAIL_MAX_ITERATIONS` | constant (new) | Workflow-appropriate iteration budget (24) for the seeded assistant; seeder sets + refreshes it | `backend/app/services/agents/assistant_seeder.py` |
| `_conversation_turn_error_from_guardrail_stop` | function (new) | Maps AR-forwarded guardrail stop reasons to structured `ConversationTurnError`s | `backend/app/api/ws/chat.py` |
| `resetForSessionSwitch` / `handleStartNewSession` / `handleSwitchToSession` | functions (new) | Action-bar session lifecycle (fresh session without end/archive; in-place resume switch) | `frontend/src/components/agents/ConversationDialog.tsx` |
| `SessionSwitcherList` | component (new) | "View All Sessions" switcher list (reuses `useConversationSessions`) | `frontend/src/components/agents/ConversationDialog.tsx` |

## 11b. FIX-20261101-120618 Work Item 1 — View All Sessions upgrades + sessions list API

### Endpoint contract — `GET /api/v1/conversations/sessions` (new)

Paginated, filterable sessions listing; permission `agent::trails:read`; tenant-scoped.

| Param | Type | Default | Notes |
|---|---|---|---|
| `agent_type_id` | uuid | — | optional filter |
| `triggered_by_user_id` | uuid | — | optional filter |
| `status` | `active\|ended\|all` | `all` | `ended` = closed/archived/error; `active` = active only |
| `date_from` / `date_to` | datetime | — | explicit range; overrides the default window |
| `all_time` | bool | `false` | disables the default window |
| `page` / `page_size` | int | `1` / `10` | min 1; 422 otherwise |

Default time window: when no `date_from`/`date_to` and `all_time` is false, the lower
bound is `now − Settings.conversation_sessions_default_window_days` (default **7**,
configurable via env `CONVERSATION_SESSIONS_DEFAULT_WINDOW_DAYS`). Ordered
`updated_at` DESC. Response envelope `ConversationSessionPageRead`:
`{items, total, page, page_size, default_window_days}` — `default_window_days` mirrors
the backend setting so the UI can default its date-range inputs. The legacy
`GET /conversations` list endpoint is unchanged (backward compatible).

### Frontend — "View All Sessions" dialog (ConversationDialog)

`SessionSwitcherList` is upgraded to the sessions-tab experience: a **Show ended
sessions** switch (default off → `status=active`; on → `status=all`), **From/To** date
inputs defaulting to the last-7-days window (`DEFAULT_SESSIONS_WINDOW_DAYS` mirrors the
backend setting), **Pagination** (page size 10, `total`-driven), rows ordered time desc
showing title / status / updated time; ended sessions render an "Ended" chip and are
never resumable; active sessions keep the FIX-111439 in-place resume/switch
(`POST /conversations/{id}/resume`, never end/archive). All strings via `t()`.

### Code Reference Map additions

| Symbol | Kind | Purpose | Path |
|---|---|---|---|
| `conversation_sessions_default_window_days` | Settings field (new) | Configurable default query window (days) for the sessions list — default 7 | `backend/app/core/config.py` |
| `list_sessions_page` | method (new) | Paginated + status/date-filtered sessions query; returns `(items, total)`; status semantics active/ended/all; default window when no explicit range | `backend/app/services/conversations/store.py` |
| `ConversationSessionPageRead` | schema (new) | Response envelope `{items, total, page, page_size, default_window_days}` | `backend/app/schemas/conversations.py` |
| `list_conversation_sessions_paged` | endpoint (new) | `GET /conversations/sessions` — paginated sessions listing (declared before `/{session_id}`) | `backend/app/api/v1/conversations.py` |
| `useConversationSessionsPage` / `ConversationSessionsPageParams` / `ConversationSessionsPage` | hook + types (new) | Frontend query for the paginated sessions endpoint | `frontend/src/hooks/useConversationSessions.ts` |
| `SessionSwitcherList` (upgraded) | component | Sessions-tab experience inside View All Sessions (toggle/date-range/pagination/ended chips) | `frontend/src/components/agents/ConversationDialog.tsx` |
| `DEFAULT_SESSIONS_WINDOW_DAYS` / `SESSIONS_PAGE_SIZE` | constants (new) | Mirror the backend default window (7) and page size (10) | `frontend/src/components/agents/ConversationDialog.tsx` |

## 12. FIX-20261101-120618 Work Item 2 — Built-in inherent skills (self-context + workflow-optimization)

### Design
Every agent — role'd or role-less — can now know its own context and optimise its own work
WITHOUT user configuration and WITHOUT per-agent `AgentTypeSkillBinding` rows. Injection is
DYNAMIC at context-build time: `get_agent_context` (both branches) merges the inherent tool
set into `allowed_tools` and appends the two inherent skills to the `skills` summary. The
tool definitions then flow through the EXISTING system-tool schema loop, so AR builds
callable LangChain tools with canonical `system____<name>` names exactly like bound-skill
tools (all inherent tools are `general`-category — they stay in the `system____` namespace
per the FIX-000319 scope decision; no `cc____`, no management parity, no confirmation/HITL,
`execute_script` remains AR-sandboxed, and the `RuntimeGuardrailState` iteration budget
still applies).

The inherent set (registry-derived, validated against `SystemToolRegistry` at request time —
a stale definition raises `RuntimeError` at first context build):

| Inherent skill | Tools |
|---|---|
| `self-context` | `get_implementation_plan`, `get_optimized_implementation_plan`, `get_scripts`, `get_execution_log` |
| `workflow-optimization` | `generate_optimized_plan`, `generate_script`, `execute_script`, `list_scripts`, `get_script` (+ `get_implementation_plan`, `get_optimized_implementation_plan`, `get_scripts` for the Optimize & Verify loop) |

Skill ids in the `skills` summary are deterministic `uuid5` values (namespace
`00000000-0000-0000-0000-000000001206`) — they are NOT rows in `skills`; no database rows
are created anywhere. Skill/tool descriptions document the set so agents discover it via
their own context. Deliberate contract change: "empty role ⇒ zero system tools" no longer
holds — the inherent set is the only auto-injected system toolset (updated
`test_tool_naming_refactor.py`); assistant context is now exactly meta tools + inherent set
(updated FIX-035145 / FIX-133253 context tests).

### Code Reference Map additions

| Symbol | Kind | Purpose | Path |
|---|---|---|---|
| `InherentSkillDefinition` | dataclass (new) | Frozen built-in skill descriptor (name, description, tool_names) | `backend/app/services/agents/builtin_skills.py` (new) |
| `INHERENT_SKILL_DEFINITIONS` / `INHERENT_SKILL_NAMES` | constants (new) | The registry-derived inherent set (`self-context`, `workflow-optimization`) | `backend/app/services/agents/builtin_skills.py` |
| `get_inherent_skill_definitions` | function (new) | Returns the inherent skill definitions | `backend/app/services/agents/builtin_skills.py` |
| `get_inherent_tool_names` | function (new) | Union of inherent bare tool names, validated against `SystemToolRegistry` (fails closed on drift) | `backend/app/services/agents/builtin_skills.py` |
| `get_inherent_skill_summaries` | function (new) | Deterministic `[(uuid5 skill_id, name)]` pairs for the context skills summary | `backend/app/services/agents/builtin_skills.py` |
| `get_inherent_canonical_tool_names` | function (new) | Canonical `system____<bare>` names (asserts `general` category) | `backend/app/services/agents/builtin_skills.py` |
| inherent-skills injection | block (new) | In `get_agent_context`, after both role'd/role-less branches: `allowed_tools.update(...)` + skills-summary append — no `AgentTypeSkillBinding` rows | `backend/app/api/v1/internal/agent_data.py` |

---

## 13. FIX-20261101-223511 — binding visibility, zero-binding guard, canonical preview, expandable approval

### 13.1 Binding visibility (read paths)
- Management toolset (`management_tools.py`): `_attach_skill_tool_bindings` joins
  `SkillToolBinding ⟕ McpTool ⟕ McpServer` (LEFT joins — virtual/decision tool ids degrade to
  the stringified tool id) and attaches `record["tool_bindings"] =
  [{tool_id, name, original_name, server_slug, server_name}]` in binding order to every skill
  record returned by list/get/create/update. One batched query per list call.
- REST skills read (`schemas/skills.py`): `SkillRead.tool_bindings:
  list[SkillToolBindingRead]` (name, original_name, server_slug, server_name). The
  `populate_tool_ids` `mode="before"` validator builds a DETACHED `SimpleNamespace` snapshot —
  never assign dicts to the ORM's instrumented `tool_bindings` collection (raises
  `AttributeError: 'dict' object has no attribute '_sa_instance_state'`).
  `skills._SKILL_LOAD_OPTIONS` adds `selectinload(McpTool.server)`.
- Frontend `SkillListPage` (FIX-20261102-015138): table shows a tool COUNT —
  `t('skills.toolCountValue', {count})` ("N tools") with a native `title` tooltip listing
  the bound tool names; explicit muted "No tools bound" chip at zero bindings.
  Type: `Skill.tool_bindings?: SkillToolBindingInfo[]`.
- Frontend `SkillEditor` (FIX-20261102-015138; SUPERSEDED by FIX-20261102-062047 —
  see section 14.3 for the single-surface design): read-only **Bound Tools** card rendered
  whenever a skill is loaded — covers BOTH viewer (`mode="view"`) and editor modes (and
  system skills). Each binding renders as `original_name || name` (code) + owning-server
  chip (`server_name || server_slug`) + canonical `name` (muted caption); empty list shows
  "No tools bound". Data: `skillDetail?.tool_bindings ?? skill?.tool_bindings`; binding
  editing behavior unchanged. Tests: `SkillEditor.boundTools.test.tsx`,
  `SkillsToolBindingsVisibility.test.tsx` (table count, no chips).

### 13.2 Zero-binding guard (non-fatal warning)
`create_skill` / `update_skill` results gain `"warnings": [ZERO_BINDING_WARNING]` when the
skill ends with zero bindings (update: only when the payload touched `tool_ids`/`tool_names`).
The record is still returned — tool-less skills are allowed; the warning is a
self-correction signal for the assistant (knowledge `skill-tool-binding` + seeder rule 2f:
discover via `get_mcp_server`, bind immediately via `update_skill`, tell the user).

### 13.3 Canonical confirmation preview contract
Knowledge entry `confirmation-preview-format` + seeder rules 2e: EVERY create/update
confirmation (message AND `human_intervene` prompt) is EXACTLY
`**<Operation> <Resource Type>: <Name>**` + ONE `| Field | Value |` markdown table; updates
list only changed fields (old → new); agent-type creation includes model/identity/role/skills/
grants rows. No bullet lists, no prose-only previews — the intervention prompt IS the table.

### 13.4 Expandable approval card
`InlineInterventionDialog` gains an Expand toggle → 90vw × 80vh MUI Dialog rendering the SAME
`ContentRenderer` preview full-width (`min-width: 480px`); Approve/Deny in BOTH surfaces share
the same handlers (single source of truth — no state to desync); inline preview wraps in
`overflowX: auto`. Streaming-blocked / submitting states untouched. i18n keys
`conversations.sessions.intervention.expand|collapse|previewTitle`.

---

## 14. FIX-20261102-062047 — single-surface skill editor + complete, permission-correct tool listing

### 14.1 MCP listing contract (`backend/app/api/v1/mcp_hub.py`)

`GET /mcp/tools` (`list_all_tools`):

1. assemble `system (virtual) + decision (virtual, tenant) + DB tools`;
2. apply the cc permission filter (drop `server_slug == "cc"` unless
   `identity_has_permission(integration::control_center, read)`);
3. dedupe by tool id;
4. **sort over the FULL set** by `(server_slug, name, id)`;
5. slice `[offset:offset+limit]` (default `limit=200`, cap 200);
6. set `X-Total-Count` to the deduped total.

No item can be lost or duplicated across pages and the order never depends on
DB/insertion order.

`GET /mcp/servers` (`list_mcp_servers`): the virtual `system`/`decision`
exclusion and the cc permission filter are applied IN THE QUERY (never after
`offset/limit`), with `ORDER BY (name, id)`. Pagination runs over the full
logical ordering — virtual servers occupy slots 0–1, DB servers follow; the
handler maps the requested window onto the DB `offset/limit` accordingly.
`X-Total-Count` = DB total + 2.

`GET /mcp/tools/{tool_id}` (NEW, `get_mcp_tool`): resolves one tool by id —
DB tools, plus virtual system/decision ids. cc tools are visible here WITHOUT
`integration::control_center:read` only when a skill binding of the caller's
tenant references that exact tool (`_tool_referenced_by_skill`); otherwise
404-without-leak. It never exposes the cc catalogue.

CORS exposes `X-Total-Count` (`expose_headers`).

### 14.2 Frontend data access (`frontend/src/hooks/useMcpServers.ts`)

- `useAllTools()` / `useMcpServers()` (no args) page the complete set in
  200-item pages until a short page (safety cap 50 pages).
- `useAllTools(limit, offset)` / `useMcpServers(limit, offset)` keep their
  single-request semantics (McpToolBrowser paging unchanged).

### 14.3 One editor surface (`frontend/src/components/agents/SkillEditor.tsx`)

- `selectedToolIds` is the single source of truth. It initialises from
  `skill.tool_ids`; the detail payload (`GET /skills/{id}`) is applied once per
  skill and never overwrites a user change (`toolSelectionDirtyRef`).
- `buildSkillToolEntries(toolIds, allTools, tool_bindings)` resolves each id
  from the browsable catalogue, degrading to the binding payload
  (`tool_id`, `name`, `original_name`, `server_slug`, `server_name`) when the
  tool cannot be browsed. `groupToolEntries` groups by server slug, sorted.
- The grouped list under the Select Tools button IS the display and editor:
  `original_name || name` + owning-server chip + canonical name; edit mode adds
  a remove control per editable entry (explicit unbind: the REST PUT replaces
  bindings); view mode is the same list without controls.
- The separate read-only "Bound Tools" card is removed. The Skills table keeps
  its "N tools" count (FIX-015138 unchanged).
- Save payload = `selectedToolIds` (union). Permission-gated cc entries absent
  from the catalogue are pinned read-only and always included, so a save can
  never silently drop a dependency the caller cannot see. Other unbrowsable
  ids (stale/deleted tools) stay visible from the binding payload but remain
  removable.
- The picker lists the browsable catalogue PLUS a "Referenced (read-only)"
  group (checked + disabled + lock) for pinned entries.

### 14.4 Referenced cc visibility rule

Without `integration::control_center:read`:

- the cc server stays hidden from `GET /mcp/servers`;
- all cc tools stay hidden from `GET /mcp/tools`;
- a cc tool already bound to a skill is reconstructed from `tool_bindings`,
  shown pre-selected/read-only in the editor with the note
  `skills.editor.referencedToolReadOnlyNote` ("Access to this tool requires the
  Control Center integration permission — shown read-only because this skill
  uses it."), and is individually resolvable via `GET /mcp/tools/{id}`.

`SkillRead.tool_bindings` now includes `tool_id` (parity with the management
toolset's binding payload).

## 15. FIX-20261102-100704 Work Item 1 — generic assistant knowledge/instruction

### 15.1 Wording policy (why)

The corpus and both instruction surfaces previously encoded ONE observed
scenario as mandatory prose ("create the skill first → grant it to the role →
create the agent type", `Sequence: (1)(2)(3)`, `ASSOCIATION WORKFLOW`). The
user requirement is the opposite: *"the fix is generic … The instruction should
be generic so the LLM can make right decisions."* Each corpus entry is now
either a **GENERIC PRINCIPLE** or a **REFERENCE FACT** — never a case-scripted
workflow. The always-on instruction states the principles and points at the
discovery tools; the facts stay accurate but are presented as facts the model
consults.

Principles taught on both surfaces:

| Principle | Statement |
|---|---|
| Understand before acting | Establish the platform model first: `search_assistant_knowledge` + discovery tools (`list_*`, `get_mcp_server`, `get_management_tool_schema`) — never guess names/ids/fields |
| Completeness | A resource you create must be COMPLETE and functional in its own context; what "complete" means comes from that resource type's reference facts; no placeholders; unknown values are asked about |
| Prerequisite ordering | A reference can only point at something that exists: create what you reference; **derive** the order from discovered dependencies (X references Y ⇒ Y first) — no fixed global sequence |
| Grant at the right level | Access comes from the permission model at the level the configuration consumes it: role grants for role-based agent types, direct bindings for role-less ones |
| Reuse-first | Prefer an existing compatible entity; ask when several candidates fit |
| Confirm-before-write / no-delete | Unchanged (already generic) |

Reference facts kept: agent types bind skills/SOPs (never raw MCP tools);
skills wrap tools through tool bindings (zero bindings ⇒ inert); roles grant
skills/SOPs, identities are assigned to roles (validated per execution);
per-tenant Model Config enabled-models; conversational agent types have no
typed output; `cc____` (Control Center management caps) vs `system____`;
per-tenant name/slug uniqueness; model/identity-or-role ⇒ functional agent
type. `confirmation-preview-format` is retained verbatim — it is a format
standard, not a workflow.

### 15.2 Knowledge entries

Added `resource-completeness`, `prerequisite-ordering`, `reuse-first`.
Rewritten to principle/fact form: `agent-creation-completeness` (now a
reference fact), `creation-payload-completeness`, `agent-type-composition`,
`skills-first-prerequisite` (instance of prerequisite-ordering),
`role-identity-chain`, `role-grant-workflow` (now the grant-at-the-right-level
principle; keeps `create_agent_role`/`update_agent_role` `skill_ids`/`sop_ids`
mechanics), `sop-composition`, `progressive-context`. Retrieval keywords target
the user phrasings "how do I make an agent work", "what must exist before
creating X", "why can't my agent access Y".

### 15.3 Instruction refresh contract

`ASSISTANT_SYSTEM_INSTRUCTION` rules 2a/2b/2c carry the generic principles;
rule 8 lists reference FACTS + PRINCIPLES; rules 1/2/2d/2e/2f/3–7 and the
canonical preview table are unchanged. `MANAGEMENT_SKILL_INSTRUCTIONS` mirrors
the same principles + facts (the former "Composition chain" script is gone).
Both the create and the digest-compare refresh branches use the same
constants, so every previously seeded tenant converges on the next seeder
run/restart (verified: 27/27 tenants via
`scripts/fix-20261102-100704-seed-refresh-check.py`).

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `_KNOWLEDGE_ENTRIES` (`resource-completeness`, `prerequisite-ordering`, `reuse-first`) | knowledge entries (new) | Generic principles retrievable via `search_assistant_knowledge` | `backend/app/services/agents/assistant_knowledge.py` |
| `ASSISTANT_SYSTEM_INSTRUCTION` rules 2a–2c, 8 | constants | Generic principles + discovery pointer set + reference facts; fixed sequence removed | `backend/app/services/agents/assistant_seeder.py` |
| `MANAGEMENT_SKILL_INSTRUCTIONS` | constant | Same principles/facts digest (digest-compare refresh for existing tenants) | `backend/app/services/agents/assistant_seeder.py` |
| `fix-20261102-100704-seed-refresh-check.py` | script (new) | Runs the idempotent seeder refresh against the configured DB and reports per-tenant convergence | `scripts/fix-20261102-100704-seed-refresh-check.py` |

## 16. FIX-20261102-100704 Work Item 2 — canvas pending-load contract (topology)

### 16.1 Problem and scope

`PanelTopologyCanvas` composes labels from several independent react-query
lists/details. On a slow network it rendered the draft before those requests
resolved, so bound entities fell back to their **raw ids** (or generic labels)
with no feedback that loading was in progress. The canvas is the single
canonical topology view (Agent Management Panel **and** the Agent Type Details
preview), so the fix lives there — no preview-specific diagram.

### 16.2 Pending vs. genuinely missing vs. deliberately empty

Three distinct states, never conflated:

| State | Meaning | Rendering |
|---|---|---|
| **Pending** | The reference request is in flight AND the name is not already cached | Node gets `pending: true` + the `loading` label; the renderer draws an accessible spinner instead of the entity icon |
| **Genuinely missing** | The list/detail request COMPLETED but the referenced row is absent (deleted/unavailable) | Historical raw-id fallback is kept (`names[...] ?? id`) — no spinner |
| **Deliberately empty / set** | No binding at all, or an intentional contract state | Unchanged: dashed placeholders (`usage: 'empty'`), solid `None` / `Conversation` / `Auto` / locked-output nodes |

A name already present in the react-query cache is never marked pending, so
cached entities do not flicker while other lists load.

### 16.3 Pending flags (composer contract)

`buildPanelTopology(agentName, draft, names, labels, pending)` gains an
optional, typed `PanelTopologyPending` argument (default `NO_PENDING` — all
existing callers/tests keep resolved-or-missing semantics):

| Flag | Source query | Entities it makes pending |
|---|---|---|
| `identity` | `GET /agents/identities` | identity node |
| `role` | `GET /agents/roles` | role node |
| `model` | `GET /agents/model-configs` (available models) | model node |
| `dataTypes` | `GET /data-types` | typed input slot (schema → registry type lookup) and output data type |
| `skills` | `GET /skills` | directly bound **and** SOP-composed skill nodes; also gates the tools zone (tool ids unknown) |
| `sops` | `GET /sops` | SOP nodes |
| `sopDetails` | `GET /sops/{id}` for bound SOPs | a pending composition child (`sop_pending_<sopId>`, indented beneath the SOP) **and** the tools zone (composed skills' tools unknown) |
| `tools` | `GET /mcp/tools` + `GET /mcp/servers` | tools zone when the equipped skills do bind tool ids |

The flags come from each query's `isLoading` (`isPending && isFetching`; false
for completed or disabled queries — the bound-SOP detail query is disabled when
no SOP is bound).

### 16.4 Tools-zone placeholder rule

The `No tools` placeholder (`tool_empty`, dashed, `usage: 'empty'`) is reserved
for a **resolved** graph where nothing resolves. While tool resolution is in
flight the zone renders a pending `tool_pending` node instead (spinner +
loading label, no skill→tool route connectors yet) — showing "No tools" mid-load
would wrongly assert the agent has no tools.

### 16.5 Renderer contract (`TopologyDiagramRenderer`)

- `TopologyNode.pending?: boolean` — optional, backwards compatible (generic
  layered mode and plan-based renderers are unaffected).
- Pending nodes swap the entity-type icon for an SVG spinner **in the same
  viewBox slot** (icon gutter, `NODE_ICON_SIZE` diameter): geometry is
  unchanged, so the graph never jumps when the data arrives. All sizing is in
  viewBox units, so the spinner scales sanely under responsive width,
  fullscreen `fillHeight`, viewBox zoom and the font-scale cap
  (`TOPOLOGY_MAX_FONT_SCALE`).
- Accessibility: `role="progressbar"` + localized `aria-label` and `<title>`
  from `agents.panel.topologyLoading` ("Loading…"), animated with SMIL inside
  the SVG (no HTML overlay).
- Pending nodes are inert: click handlers (detail navigation) do not fire and
  the cursor stays default; the group is marked `data-pending="true"`.
- The renderer stays dumb: it renders the label/flags it is given; i18n text
  is resolved by the canvas (label) and the renderer (a11y text) via `t()`.

### 16.6 Code Reference Map additions

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `PanelTopologyPending`, `NO_PENDING` | types/const | Per-entity in-flight flags + all-resolved default | `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` |
| `PanelTopologyLabels.loading` | label | i18n loading label rendered for pending entities | `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` |
| `resolveRef` / `refLabel` | helpers | Resolved name → loading label (pending) → raw id (missing) | `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` |
| `TopologyNode.pending` | type field | Pending marker consumed by the renderer | `frontend/src/types/index.ts` |
| `PendingSpinner` | component | ViewBox-unit SVG spinner (`role="progressbar"`, SMIL) | `frontend/src/components/agents/TopologyDiagramRenderer.tsx` |
| `agents.panel.topologyLoading` | i18n key | "Loading…" | `frontend/src/i18n/locales/en.json` |
