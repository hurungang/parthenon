# Module: agent-runtime — Tech Spec

## Overview

The Agent Runtime is the execution-time security layer that runs alongside each agent instance. It operates under mutual TLS (mTLS): on startup, it loads an X.509 certificate issued by the Control Center CA, configures all outbound HTTP clients to present that certificate on every request, and monitors the certificate for expiration. When the certificate approaches its 80% lifetime threshold (approximately 19 hours into a 24-hour cert), a background task requests a renewal from the Control Center and performs an atomic in-memory swap with no downtime.

Metadata requests to the Control Center no longer return identity tokens. The runtime receives only non-sensitive configuration (agent type, SOPs, skills, model config, system instruction). All identity tokens are resolved on demand by the Control Center at the point of each tool call, proxied through the Communication Hub.

**Dependency on Control Center:** `POST /certificates/issue` for issuance, `GET /certificates/ca` for CA verification, and mutual TLS on all subsequent requests.

---

## Key Components

| Component | Description |
|-----------|-------------|
| `CertificateManager` | Startup: loads certificate and private key from files (`AGENT_CERT_PATH`, `AGENT_KEY_PATH`, `AGENT_CA_CERT_PATH` env vars); validates cert signature against CA public cert; configures all HTTP clients for mTLS. Background task (`run_renewal_task`): polls every hour; triggers renewal at 80% lifetime; atomically swaps to the new cert; shuts down gracefully if cert expires without renewal |
| `MetadataClient` | Calls `GET /agent/metadata` on the Control Center using the mTLS-configured HTTP client; asserts that the response does NOT contain `identity_token` or `access_token` fields via `verify_no_identity_tokens`; returns validated agent configuration |

---

## Security Properties

- Certificate and private key are read from the file system at startup only — paths are set by the orchestrator (Docker, Kubernetes) and never hardcoded
- `verify_no_identity_tokens` is a mandatory security assertion: if the Control Center response ever inadvertently includes a token, the runtime raises an error and does not proceed
- Certificate renewal is atomic: the old cert remains active until the new cert is fully validated; no window of uncertified operation
- Graceful shutdown on cert expiry prevents the agent from operating without a valid identity

## Tool Naming and Uniform Routing

All tool calls from the Agent Runtime use the unified `server____tool_name` convention (four underscores). The executor forwards **all** tool calls to the Communication Hub without distinction between system tools and MCP server tools — no branching logic by tool type exists in executor code.

The Communication Hub's Name Resolver routes calls:
- `system____*` → internal system tool handlers (e.g., Notification Service for `system____send_notification`)
- `<server>____*` → MCP Hub for proxying to the registered MCP server

**`tool_naming` module** (`backend/app/services/agents/tool_naming.py`):

| Symbol | Type | Description |
|--------|------|-------------|
| `parse_tool_name(name)` | function | Splits `server____tool` into `(server, tool)` tuple; handles legacy bare names for backward compat |
| `build_tool_name(server, tool)` | function | Constructs canonical `server____tool` string |
| `is_system_tool(name)` | function | Returns `True` if server segment equals `"system"` |

**Reserved names**: `system` is the reserved server prefix for built-in platform tools. MCP server names must not contain `____`.

## Explicit Result Saving

The Agent Runtime does **not** automatically call a `save_result` tool at agent completion. Intermediate named saves go through the `system____save_data` tool; the final typed result is persisted by the runtime completion flow through Control Center (`save_output` / typed-output persistence). This keeps saved data intentional and traceable to a specific step while guaranteeing the singular final output.

**`ResultStore`** (`backend/app/services/results/store.py`): persistence point for legacy result records, called by the AR result-submit path.

## Conversation Turn Durability and Activity

Conversational turns are no longer process-local state. AR keeps executing turns, but a paused turn is durable and instance-independent (full details: [conversations module](../conversations/tech-spec.md)).

| Component | Description |
|-----------|-------------|
| `DurableCheckpointSaver` | LangGraph checkpointer backed by CC's payload store through the transport client; coalesces intermediate super-step writes to the latest checkpoint, provides an explicit flush, and maps load/deserialization failures to a typed unavailable error |
| `CheckpointTransportClient` | AR's only path to pause state: save/load checkpoint, save resume index, claim, release, complete — all issued to CH over `internal_httpx_client` with the AR certificate. Courier only |
| Durable pause in the executor | The conversational turn builds the agent with the durable checkpointer, registers the resume index when a pause is detected, **flushes before reporting waiting**, and returns a pause result instead of awaiting an in-process future |
| `resume_conversation_turn` | `POST /internal/conversation/resume`: claim, load checkpoint, rebuild the agent, emit `thinking`, resume with the operator's value, stream status and a final (or another) `paused` chunk |
| `resume_session` (delegating) | Legacy job resume keeps the job path; conversation-scoped ids delegate to the conversational handler |
| Activity emission | Each transition (thinking / using_tool / delegating / waiting / waiting_for_human / timeout_or_failed / delegation_resumed) is emitted **only inside the NDJSON response stream** returned to CH; AR originates no outbound activity call and never touches the CC activity endpoints or the database (structurally enforced) |
| Claim identity | Process-unique (`<base>-<process-token>`) so two AR processes never share a lease holder; the holder may renew its own live lease |
| Live-test endpoint | `POST /internal/live-test/run` executes one approved saved script end to end in the real sandbox with the live session-bound CH client (`provenance="live_test"`), under the subject's own identity and grants, with a hard per-run wall clock; no LLM is involved and there is no per-operation execution |

## Sandboxed Scripting (replay and live-test)

Agent Runtime hosts the ONLY sandboxed script execution surface (full details: [sandboxed-scripting module](../sandboxed-scripting/tech-spec.md)).

| Component | Description |
|-----------|-------------|
| Sandbox engine + caps | RestrictedPython compile+exec, audited `safe_builtins` baseline, guarded attribute/write access, wall-time/memory caps, fail-closed typed errors, MCP-only `SandboxToolFacade` with tenant-header parity |
| Script runner / dispatcher / fallback | `execute_python_source` (optional per-call sink), optimized-plan preference, `initial_context` binding, `sandbox_violation` / `resource_limit_exceeded` fallbacks |
| Replay client | `ReplayToolClient` answers `tools.call` from the recorded transcript when `replay_required`; a miss is a typed error, never a live fallback |
| AR script-tool endpoint | `POST /internal/script-tools/execute` — session-bound live client for `script____<name>`; replay client for verification |
| Command toolset wiring | `_command_tool_schemas(command)` injects optimization tools; repeat-identical-tool-call guard enabled for command and optimization turns |

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `AGENT_CERT_PATH` | File path to agent instance certificate PEM |
| `AGENT_KEY_PATH` | File path to agent instance private key PEM |
| `AGENT_CA_CERT_PATH` | File path to Control Center CA public certificate PEM |

---

## Code Reference Map

### Runtime Application Surface

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `create_app` | function | Agent Runtime FastAPI application factory that wires middleware, routing, and runtime service clients | `backend/app/agent_runtime/main.py` |
| `startup_event` | coroutine | Startup lifecycle hook — validates Control Center reachability before certificate bootstrap, then loads certificate and starts renewal task | `backend/app/agent_runtime/main.py` |
| `_validate_control_center_reachable` | coroutine | **NEW** — validates Control Center health check reachability with retry logic before attempting certificate bootstrap; fails fast if CA is unavailable | `backend/app/agent_runtime/main.py` |
| `_load_certificate` | coroutine | Loads or bootstraps agent-instance certificate from Control Center (retained) | `backend/app/agent_runtime/main.py` |
| `_start_certificate_renewal` | coroutine | Starts background certificate renewal task (retained) | `backend/app/agent_runtime/main.py` |

### Runtime Boundary Enforcement

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ControlCenterCertificateMiddleware` | class | Validates service certificates on runtime control-plane requests and enforces internal trust boundary | `backend/app/agent_runtime/middleware.py` |
| `ControlCenterDataClient` | class | Fetches plans, context, model config, and session state from Control Center internal data APIs | `backend/app/agent_runtime/data_client.py` |
| `get_agent_context` | method | Loads effective context payload including guardrail policy snapshot before execution starts | `backend/app/agent_runtime/data_client.py` |
| `mark_session_failed` | method | Persists terminal guardrail stop outcomes through Control Center session-status APIs | `backend/app/agent_runtime/data_client.py` |
| `log_execution_event` | method | Emits structured guardrail decision events and runtime counter snapshots to execution logs | `backend/app/agent_runtime/data_client.py` |
| `record_tool_call` | method | Fire-and-forget write of one tool execution (name, MCP slug, route type, status, duration, error) to `POST /internal/data/tool-calls`; failures are logged and swallowed, never breaking tool execution | `backend/app/agent_runtime/data_client.py` |
| `_allow_insecure_internal_fallback` | function | Development-only opt-in guard; production/default behavior remains fail-closed for missing internal trust material | `backend/app/agent_runtime/data_client.py` |
| `CommHubToolClient` | class | Sends tool and A2A requests from Agent Runtime to Communication Hub internal routes with service identity headers or mTLS | `backend/app/agent_runtime/comm_hub_client.py` |
| `trigger_execution` | endpoint | Runtime execution trigger endpoint used by Communication Hub for asynchronous session execution | `backend/app/agent_runtime/api/execute.py` |
| `_execute_session` | function | Executes one queued session with control-plane state updates and tool routing through Communication Hub | `backend/app/agent_runtime/api/execute.py` |
| `execute_conversation_turn` | endpoint | Executes conversation turn requests delegated from Communication Hub chat flows; supports NDJSON status-event streaming before final payload | `backend/app/agent_runtime/api/conversation.py` |

### Certificate Manager (`backend/app/agent_runtime/certificate_manager.py`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `CertificateManager` | class | Manages agent instance certificate lifecycle: load, validate, configure mTLS, monitor expiration, renew | `backend/app/agent_runtime/certificate_manager.py` |
| `load_certificate` | method | Load certificate and private key PEM files from paths in env vars on startup | `backend/app/agent_runtime/certificate_manager.py` |
| `validate_certificate_against_ca` | method | Verify certificate signature against the CA public cert; raise on failure | `backend/app/agent_runtime/certificate_manager.py` |
| `configure_mtls_client` | method | Configure the shared HTTP client to present the agent certificate on every outbound TLS handshake | `backend/app/agent_runtime/certificate_manager.py` |
| `check_certificate_expiration` | method | One-shot check: return `True` if certificate is within 20% of expiry window | `backend/app/agent_runtime/certificate_manager.py` |
| `renew_certificate` | method | Call Control Center `POST /certificates/issue`; receive new cert and key | `backend/app/agent_runtime/certificate_manager.py` |
| `switch_certificate` | method | Atomically replace in-memory cert and key; reconfigure mTLS client; no connection interruption | `backend/app/agent_runtime/certificate_manager.py` |
| `run_renewal_task` | method | Async background coroutine; polls `check_certificate_expiration()` every hour; calls `renew_certificate()` and `switch_certificate()` when approaching expiry | `backend/app/agent_runtime/certificate_manager.py` |

### Metadata Client (`backend/app/agent_runtime/metadata_client.py`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `MetadataClient` | class | Fetches agent configuration from Control Center using mTLS-configured HTTP client; enforces zero-token response contract | `backend/app/agent_runtime/metadata_client.py` |
| `request_metadata` | method | Call `GET /agent/metadata` with client certificate; return parsed agent configuration dict | `backend/app/agent_runtime/metadata_client.py` |
| `verify_no_identity_tokens` | function | Assert that response body contains no `identity_token` or `access_token` keys; raise `SecurityViolationError` if found | `backend/app/agent_runtime/metadata_client.py` |

### Communication Hub Client (`backend/app/agent_runtime/comm_hub_client.py`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `CommHubToolClient` | class | Runtime-side client for Communication Hub coordination paths, including tool routing and A2A target-slug dispatch payloads | `backend/app/agent_runtime/comm_hub_client.py` |
| `call_a2a_request` | method | Sends delegated A2A requests whose results propagate guardrail stop reason metadata back to parent execution flow | `backend/app/agent_runtime/comm_hub_client.py` |

### Runtime Enforcement Loop (`backend/app/services/agents/runtime_executor.py`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `_run_task_loop_ar` | method | Task execution loop enforcing runtime guardrails such as iteration ceilings, delegated step budgets, timeout checks, and delegation depth limits | `backend/app/services/agents/runtime_executor.py` |
| `execute_conversation_turn` | method | Conversation loop applying mode-aware token guardrail behavior, continuation semantics, and guardrail usage logging | `backend/app/services/agents/runtime_executor.py` |
| Delegation Depth Guard | guardrail | Overrides `max_delegation_depth` to 1 for non-conversational agents; blocks sub-agent dispatch when `tree_depth + 1 > max_delegation_depth`; emits `delegation_depth_blocked` execution event | `backend/app/services/agents/runtime_executor.py` |
| Delegation Status Events | emission | Emits `delegation_started` before sub-agent dispatch, `delegation_waiting` after dispatch (parent blocked), `delegation_failed` on dispatch/runtime error, and `delegation_resumed` on sub-agent completion — all for non-conversational delegation paths | `backend/app/services/agents/runtime_executor.py` |
| HITL Intervention in Delegation | routing | When a delegated sub-agent calls `human_intervene`, the intervention flows through CH's Task Delegation Event Router to the parent agent's execution log NDJSON stream; response resumes the sub-agent and emits `delegation_resumed` | `backend/app/services/agents/runtime_executor.py` |
| Output Type Prompt Injection | system prompt | Injects output format instruction into system prompt based on `AgentType.output_type`: `markdown` → produce markdown output; `typed` → produce JSON matching `output_schema`; `auto` → no extra instruction | `backend/app/services/agents/runtime_executor.py` |
| `_resolve_content_type` | method | Maps `output_type` value to MIME content type (`text/markdown` or `application/json`); used by `save_result` tool for ResultRecord persistence | `backend/app/services/agents/runtime_executor.py` |

### Segregation Audit Coverage

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_agent_runtime_has_no_ast_db_or_sqlalchemy_imports` | integration test | Guardrail test that fails if Agent Runtime introduces direct database/session imports | `backend/tests/integration/test_database_isolation.py` |
| `test_make_client_without_cert_fails_closed_outside_dev_opt_in` | unit test | Ensures internal runtime/hub calls fail closed when certificate identity is unavailable in non-development profiles | `backend/tests/unit/test_control_center_comm_hub_client.py` |

---

## Multi-Tenancy Integration

Agent Runtime is tenant-bound via signed headers since the multi-tenant support change (full details: [multi-tenancy module](../multi-tenancy/tech-spec.md)).

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ControlCenterCertificateMiddleware` | middleware (modified) | Additionally verifies CC-signed tenant headers (verify-if-present) and binds the verified context to requests | `backend/app/agent_runtime/middleware.py` |
| `ControlCenterDataClient` (AR) | class (modified) | Forwards signed tenant headers to CC (`_get`/`_post`/`_patch`) | `backend/app/agent_runtime/data_client.py` |
| execute / terminate endpoints | routers (reference) | Unchanged — the runtime loader resolves configuration only within the middleware-bound tenant context; no widening path exists and agents still hold no tokens or credentials | `backend/app/agent_runtime/api/execute.py`, `backend/app/agent_runtime/api/terminate.py` |

## Strict Tenant Isolation

Agent Runtime is a virtual tenant: it resolves the calling tenant once from the signed context on the execution request and applies it to all tool/MCP/A2A resolution and every downstream internal call during the run.

- The tenant-verification middleware is **fail-closed**: execution requests without a valid signed `X-Internal-Tenant-*` binding are rejected (root-default when multi-tenancy is off).
- All AR→CC data calls go through `ControlCenterDataClient` (`backend/app/agent_runtime/data_client.py`) and the global egress hook `internal_httpx_client` / `attach_forwarded_tenant_headers` (`backend/app/core/internal_http.py`), which stamp the run's forwarded signed headers on every request — including the `agent_data` context fetch, decision toolset registration, and `save_data`/`get_data` hops.
- The LangChain tool wrapper carries the tenant through the run so `server____tool` and `agent____<slug>` names resolve only within the run's tenant; the runtime executor's MCP tool lookup is tenant-filtered and fails closed.

### Strict Tenant Isolation — Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| AR tenant-verification middleware | middleware | Requires a signed tenant binding on execution requests; fail-closed (verify-if-present replaced) | `backend/app/agent_runtime/middleware.py` |
| `ControlCenterDataClient` | class | AR→CC data client; forwards the run's signed tenant headers on every call (`_get`/`_post`/`_patch`) | `backend/app/agent_runtime/data_client.py` |
| `comm_hub_client` header forwarding | client behaviour | Every AR→CH/CC internal call stamps the run's forwarded signed tenant headers via the global egress hook | `backend/app/agent_runtime/comm_hub_client.py` |
| `internal_httpx_client` / `attach_forwarded_tenant_headers` | functions | Global egress hook (shared with CH) attaching forwarded tenant headers to all outbound internal requests | `backend/app/core/internal_http.py` |
| `build_langchain_tools_for_ar_path` | function | Tenant-aware tool-set construction for a run | `backend/app/services/agents/langchain_tool_wrapper.py` |
| runtime executor MCP lookup | function behaviour | `server____tool` lookup tenant-filtered, fails closed | `backend/app/services/agents/runtime_executor.py` |

---

## Code Reference Map — conversation durability, activity and live test

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `DurableCheckpointSaver` | class | LangGraph checkpointer backed by the CC-owned payload store; coalescing writes, explicit flush, typed unavailable error | `backend/app/agent_runtime/durable_checkpointer.py` |
| `CheckpointTransportClient` | class | AR → CH courier for checkpoint/index/claim/complete calls | `backend/app/agent_runtime/checkpoint_transport.py` |
| `ConversationTurnResumeService` | class | Orchestrates claim → checkpoint load → resume for a paused conversational turn; produces `ConversationResumeOutcome` | `backend/app/agent_runtime/turn_resume_service.py` |
| `resume_conversation_turn` | endpoint | `POST /internal/conversation/resume` (claim, load, `Command(resume=…)`, stream final/paused) | `backend/app/agent_runtime/api/conversation.py` |
| `resume_session` | endpoint | `POST /internal/resume`; delegates conversation-scoped resumes | `backend/app/agent_runtime/api/intervene.py` |
| `ResumeRequest` | schema | Resume body (`session_id`, `response_value`) | `backend/app/agent_runtime/api/intervene.py` |
| `LangChainHumanInterveneTool` | class | `human_intervene` tool; conversational path uses LangGraph `interrupt()` with an idempotent registration key | `backend/app/services/agents/langchain_system_tools.py` |
| `conversation_resume` | module | In-process resume registry, retained only as the legacy fallback — retired from production conversational paths | `backend/app/agent_runtime/conversation_resume.py` |
| `AgentRuntimeExecutor.execute_conversation_turn_from_context` | method | Conversational turn entry (suppression wrapper) | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._execute_conversation_turn_from_context_inner` | method | Builds the agent, swaps in the durable checkpointer, detects pauses | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._handle_conversational_pause` | method | Flushes the checkpoint, registers the resume index and reports waiting; a refused flush becomes `persistence_failed`, never `waiting_for_human` | `backend/app/services/agents/runtime_executor.py` |
| Activity transition emission | behaviour | `using_tool` / `delegating` / `waiting` / `waiting_for_human` transitions emitted on the NDJSON stream only | `backend/app/services/agents/runtime_executor.py`, `backend/app/services/agents/langchain_tool_wrapper.py` |
| `POST /internal/live-test/run` | endpoint | One approved-script sandbox run under the subject's identity/grants; grant pre-check; per-call ledger recording; hard wall clock | `backend/app/agent_runtime/api/live_test.py` |
| `JSON+ checkpoint serializer` | external dependency | LangGraph payload encoding used by the saver | `langgraph.checkpoint.serde.jsonplus` |
| `Command` | external dependency | LangGraph resume command carrying the operator response | `langgraph.types` |
| `test_durable_checkpointer` | test module | Saver round-trip, flush-before-waiting, fail-closed flush on a refused write | `backend/tests/agent_runtime/test_durable_checkpointer.py` |
| `test_conversational_resume_from_checkpoint` | test module | Resume on a second instance, contention, re-pause | `backend/tests/agent_runtime/test_conversational_resume_from_checkpoint.py` |
| `test_resume_registry_miss_orphan` | test module | Durable-state semantics replacing the legacy registry-miss orphan test | `backend/tests/agent_runtime/test_resume_registry_miss_orphan.py` |
| `test_live_test_execute` | test module | Live-test capability check, one end-to-end run, ledger pointer, run-record shape, hard cap | `backend/tests/agent_runtime/test_live_test_execute.py` |
| `test_ar_activity_persistence_boundaries` | test module | Structural guard: AR emits activity only on the response stream; no CC activity calls, no DB | `backend/tests/agent_runtime/test_ar_activity_persistence_boundaries.py` |
