# Module: control-center — Internal Data Plane

> Part of the [control-center hub](tech-spec.md) · [technology documentation](../../README.md).

## Overview

The internal data plane is the service-to-service contract between Control Center and the other two backend services. Every route under `/api/v1/internal/*` bypasses JWT authentication and is instead gated by a **service certificate plus a per-caller route allowlist** (deny by default). Agent-instance certificates are blocked from the entire plane; only `communication-hub` (and the allowlisted `agent-runtime` data routes) are accepted.

The plane also hosts the user-facing intervention endpoints that the operator UI and the chat transport call, and — for conversation-scoped sessions — the answer path that advances the durable resume record.

---

## Internal route families

| Family | Router | Notable routes |
|--------|--------|----------------|
| Agent data | `InternalAgentDataRouter` | Agent execution context (SOP/skill summaries, model identifiers, inherent skills, optimization mode), model/session reference reads |
| Session data | `InternalSessionDataRouter` | Conversation turn prepare/append, activity read/write/touch, resume read/write, checkpoint read/write, claim/release/complete, intervention respond, tool-call ingestion, session status/result, A2A preparation, execution log streaming |
| Outputs | `InternalOutputsRouter` | Typed output validation, persistence and query |
| System tools | `system_tools` router | `save_data`, `get_data`, `get_output`, `query_result`, notifications, `human_intervene`, optimization tools, `request_live_test` |
| Management tools | `management_tools` router | `cc____` management execution + meta tools, `/resolve` |
| Scripts | internal scripts router | Serving version, compiled graph, candidates, verifications, fallbacks, executions, repairs, promote, LLM reference |
| Authorization / certificates / API keys / bootstrap | dedicated routers | Certificate-only (non-data-plane) auth |
| MCP proxy | `proxy_mcp_tool` | Hub-forwarded MCP tool calls |

---

## Intervene endpoints (operator-facing)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/v1/intervene/requests` | JWT + `intervene:view` | List requests (status, type, agent session, pagination) |
| `GET` | `/api/v1/intervene/requests/{id}` | JWT + `intervene:view` | Single request with full context and response |
| `POST` | `/api/v1/intervene/requests/{id}/respond` | JWT + `intervene:respond` | Submit an answer (approval / choice / text). Conversation-scoped answers advance the resume record in the same transaction and dispatch once; a duplicate answer returns the stored outcome |
| `POST` | `/api/v1/intervene/requests/{id}/cancel` | JWT + `intervene:respond` | Cancel a pending request |
| `GET` | `/api/v1/intervene/metrics` | JWT + `intervene:view` | Pending count, average response time, resolution rate |

---

## Conversation activity and resume data plane

These routes are CH-only, service-certificate gated, and require a signed internal tenant context (fail-closed 401). They are the persistence surface for the [conversations module](../conversations/tech-spec.md).

| Route | Purpose |
|-------|---------|
| `POST /internal/data/conversations/{id}/prepare-turn` | Persist the user turn, set activity `thinking`, refuse while a decision is pending |
| `POST /internal/data/conversations/{id}/append-turn` | Persist the agent turn, resolve activity terminal |
| `PUT` / `GET /internal/data/conversations/{id}/activity` | Upsert / hydrate activity (refuses waiting without a live resume record) |
| `POST /internal/data/conversations/{id}/activity/touch` | Heartbeat refresh of a live working row |
| `PUT` / `GET /internal/data/conversations/{id}/resume` | Create-or-reuse / read the live resume record (CC owns the expiry window) |
| `PUT` / `GET /internal/data/conversations/{id}/resume/checkpoint` | Upsert / load the opaque checkpoint payload |
| `POST /internal/data/conversations/{id}/resume/claim` | Acquire/renew the turn claim |
| `POST /internal/data/conversations/{id}/resume/release` | Best-effort claim release |
| `POST /internal/data/conversations/{id}/resume/complete` | Single-transaction closer (outcome turn, terminal state, checkpoint consumption, activity resolution) |
| `POST /internal/data/intervene/respond` | Hub-facing answer path (threads the verified tenant context) |
| `POST /internal/data/tool-calls` | Batched `RuntimeToolCall` ingestion (optional live-test ledger pointer) |
| `POST /internal/data/conversations/{id}/activity` (view) | Hydration used by `status_ping`/reconnect |

---

## Data access patterns

- **Tenant-aware dispatch:** all internal data-plane calls carry HMAC-signed `X-Internal-Tenant-*` headers minted by Control Center and forwarded (never re-signed) by CH/AR. A missing/stale/invalid set fails closed.
- **Single transaction boundaries:** the answer-advance and the exactly-once applied marker commit with their writes; the outcome turn and terminal transition commit together (guarded by `outcome_turn_id`).
- **No cross-service DB access:** CH and AR never connect to PostgreSQL; every read/write on this plane is performed by a CC handler or the reaper's own session.
- **Allowlist denials are audited** with endpoint and caller metadata; unknown callers are denied by default.

---

## Code Reference Map

### Internal segregation enforcement

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `JWTAuthMiddleware._is_public` | method | Bypasses JWT auth for `/api/v1/internal/*`; strict service-certificate enforcement applies instead | `backend/app/middleware/auth.py` |
| `require_service_certificate` | dependency | Enforces service certificate validity and caller-specific endpoint allowlists (deny by default) | `backend/app/api/deps.py` |
| `require_internal_tenant_context` | dependency | Requires a valid signed tenant context on data-plane routers | `backend/app/api/deps.py` |
| `_normalize_internal_caller` | function | Maps caller identity (`agent-runtime`, `communication-hub`) to policy caller types | `backend/app/api/deps.py` |
| `_resolve_route_template` | function | Canonical route template used for allowlist matching and deny audit metadata | `backend/app/api/deps.py` |
| `_raise_internal_policy_deny` | function | Structured deny event + deterministic 403 payload | `backend/app/api/deps.py` |
| `_CH_ALLOWLIST` | constant | CH-only route templates, including activity, resume and checkpoint routes | `backend/app/api/deps.py` |
| `guard_non_root_membership` | function | Rejects membership mutations targeting the immutable tenant root | `backend/app/api/deps.py` |
| `authorize_identity` | function | Identity-based authorisation used by handlers (tenant-bound) | `backend/app/api/deps.py` |
| `require_permission` | function | Dependency factory for tenant-bound RBAC on public endpoints | `backend/app/api/deps.py` |

### Internal routers and endpoints

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `InternalAgentDataRouter` | router | Internal runtime context and model/session reference endpoints | `backend/app/api/v1/internal/agent_data.py` |
| `get_agent_context` | endpoint | Effective runtime payload: allowed tools, bindings, guardrail snapshot, model identifiers, inherent skills, optimization mode | `backend/app/api/v1/internal/agent_data.py` |
| `AgentContextResponse` | schema | Internal context response model | `backend/app/api/v1/internal/agent_data.py` |
| `InternalSessionDataRouter` | router | Session, conversation, activity, resume, permission and A2A coordination endpoints | `backend/app/api/v1/internal/session_data.py` |
| `update_session_status` | endpoint | Terminal session outcomes including guardrail stop reasons | `backend/app/api/v1/internal/session_data.py` |
| `LogExecutionEventRequest` | schema | Structured guardrail decision/counter log payload | `backend/app/api/v1/internal/session_data.py` |
| `post_session_result` | endpoint | Execution completion result persistence | `backend/app/api/v1/internal/session_data.py` |
| `prepare_a2a_request` | endpoint | A2A preparation/delegation enqueue and parent/child linkage | `backend/app/api/v1/internal/session_data.py` |
| `record_tool_calls` | endpoint | Persists `RuntimeToolCall` batches reported by AR | `backend/app/api/v1/internal/session_data.py` |
| `prepare_conversation_turn` / `append_conversation_turn` | endpoints | Conversation turn persistence + activity transitions | `backend/app/api/v1/internal/session_data.py` |
| `upsert_conversation_activity` / `get_conversation_activity` / `touch_conversation_activity` | endpoints | Activity write / hydration / heartbeat | `backend/app/api/v1/internal/session_data.py` |
| `save_conversation_turn_resume` / `get_conversation_turn_resume` | endpoints | Resume index write/read | `backend/app/api/v1/internal/session_data.py` |
| `save_conversation_turn_checkpoint` / `get_conversation_turn_checkpoint` | endpoints | Checkpoint payload write/read | `backend/app/api/v1/internal/session_data.py` |
| `claim_conversation_turn_resume` / `release_conversation_turn_resume` / `complete_conversation_turn_resume` | endpoints | Claim arbitration, release, single-transaction closer | `backend/app/api/v1/internal/session_data.py` |
| `internal_intervene_respond` | endpoint | Hub-facing answer path with tenant context threading | `backend/app/api/v1/internal/session_data.py` |
| `ConversationActivityUpsertRequest` / `ConversationActivityResponse` / `_activity_response` | schemas / function | Activity read/write models (resume fields, terminal reason) | `backend/app/api/v1/internal/session_data.py` |
| `InternalOutputsRouter` | router | Typed output validation/persistence/query | `backend/app/api/v1/internal/outputs.py` |
| `validate_output` / `create_internal_output` / `query_internal_outputs` | endpoints | Output validation, persistence, filtered query | `backend/app/api/v1/internal/outputs.py` |
| `system_tools` (router) | router | Internal system-tool dispatch | `backend/app/api/v1/internal/system_tools.py` |
| `save_data_tool` / `get_data_tool` / `get_output_tool` / `query_result_tool` | endpoints | Named data saves, data/output queries | `backend/app/api/v1/internal/system_tools.py` |
| `human_intervene_tool` | endpoint | Creates the intervention request and persists `waiting_for_human` activity; conversation-scoped requests carry a nullable job id | `backend/app/api/v1/internal/system_tools.py` |
| `resolve_skills_internal` | endpoint | Resolve skills for a role with optional `since` | `backend/app/api/v1/internal/system_tools.py` |
| `request-live-test` handler | endpoint | Validates and records one script-scoped live-test proposal + approval intervention (see [plans & optimization](../agents/plans-optimization.md)) | `backend/app/api/v1/internal/system_tools.py` |
| `management_tools` router (`router` / `resolve_router` / `meta_router`) | routers | `cc____` management execution, resolve, meta tools | `backend/app/api/v1/internal/management_tools.py` |
| `execute_management_tool` | endpoint | Confirmed-write chokepoint; honours the turn idempotency key and commits the applied marker with the write | `backend/app/api/v1/internal/management_tools.py` |
| `proxy_mcp_tool` | endpoint | MCP proxy for hub-forwarded tool calls | `backend/app/api/v1/internal/mcp_proxy.py` |
| `bootstrap_service_certificate` | endpoint | Service identity onboarding under the bootstrap key policy | `backend/app/api/v1/internal/bootstrap.py` |
| `validate_api_key_internal` | endpoint | API-key validation (see [security layer](security-layer.md)) | `backend/app/api/v1/internal/validate_api_key.py` |

### Intervene surface

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `InterveneRouter` | router | `/api/v1/intervene/*` endpoints | `backend/app/api/v1/intervene.py` |
| `InterveneRequestStore` | service | CRUD + metrics; pending lists by job/conversation; response submission (auto-creates the `intervene_response` turn); stamps the tenant resume TTL on the pause path | `backend/app/services/agents/intervene_service.py` |
| `respond_to_intervene_request` | endpoint | Dialog-facing answer; transactional resume advance | `backend/app/api/v1/intervene.py` |
| `_resume_agent_session` | function | Dispatches one resume through CH | `backend/app/api/v1/intervene.py` |

### Outbound clients

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `CommunicationHubClient` | class | CC → CH client; fail-closed certificate requirement outside explicit dev opt-in; signed tenant headers; `forward_sandboxed_script` (replay contract) and `forward_live_test` | `backend/app/services/control_center/comm_hub_client.py` |
| `AgentRuntimeClient` | class | CC → CH client for execute/resume/terminate forwarding (signed tenant headers) | `backend/app/services/control_center/agent_runtime_client.py` |
| `internal_httpx_client` | function | Shared egress client that forwards the signed tenant headers | `backend/app/core/internal_http.py` |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_agent_runtime_denied_for_communication_hub_only_endpoint` | integration test | Caller-specific allowlist partitioning blocks AR from CH-only routes | `backend/tests/integration/test_internal_allowlist_partitioning.py` |
| `test_communication_hub_denied_for_agent_runtime_only_endpoint` | integration test | Partitioning blocks CH from AR-only routes | `backend/tests/integration/test_internal_allowlist_partitioning.py` |
| `test_policy_denial_emits_structured_audit_event` | integration test | Deny-by-default decisions emit structured audit events | `backend/tests/integration/test_internal_allowlist_partitioning.py` |
| `test_unknown_internal_service_is_denied_by_default` / `..._emits_structured_event` | integration tests | Unknown callers denied with a structured event | `backend/tests/integration/test_internal_deny_audit_events.py` |
| `test_internal_system_tools_rejects_missing_service_certificate` | integration test | Internal system-tools routes reject missing certificates | `backend/tests/integration/test_internal_deny_audit_events.py` |
| `test_turn_checkpoint_endpoints` | unit test | New activity/resume/checkpoint routes, allowlist membership, cross-tenant denial | `backend/tests/unit/test_turn_checkpoint_endpoints.py` |
| `test_internal_allowlist_activity` | unit test | Activity routes are allowlisted (regression) | `backend/tests/unit/test_internal_allowlist_activity.py` |
| `test_human_intervene_persists_activity` | unit test | A pause persists `waiting_for_human` with the pending intervention | `backend/tests/unit/test_human_intervene_persists_activity.py` |
| `test_internal_intervene_respond` | integration test | Answer path advances the resume record and dispatches once | `backend/tests/integration/test_internal_intervene_respond.py` |
| `test_service_auth` | integration test | Service certificate enforcement across internal routes | `backend/tests/integration/test_service_auth.py` |
