# Deployment: Implement Agent Runtime with Gateway

---

## 1. Environment Variables

### New Variables

#### Agent Runtime

| Variable | Description | Secret |
|----------|-------------|--------|
| `AGENT_RUNTIME_MAX_CONCURRENT_SESSIONS` | Maximum number of agent sessions that can execute simultaneously across all agent types; limits resource saturation at the runtime level | |
| `AGENT_RUNTIME_SESSION_TIMEOUT_SECONDS` | Wall-clock timeout applied to a single agent session execution; sessions exceeding this are marked `failed` and their runtime instances are reclaimed | |
| `AGENT_RUNTIME_OIDC_TOKEN_ENDPOINT` | Token endpoint used by the Agent Runtime to exchange agent client credentials for access tokens before executing OIDC-authenticated tool calls | |

#### Agent Session Queue

| Variable | Description | Secret |
|----------|-------------|--------|
| `AGENT_SESSION_QUEUE_NAME` | Redis list key used as the primary session dispatch queue between the Platform API and the Agent Runtime worker; must be consistent across all horizontally scaled worker instances | |
| `AGENT_SESSION_QUEUE_RESULT_TTL_SECONDS` | Time-to-live for persisted session results in Redis before they are evicted; results are also stored in PostgreSQL for long-term audit | |
| `AGENT_SESSION_WORKER_CONCURRENCY` | Number of parallel session consumer threads (or async tasks) within a single `agent-session-worker` container; tune with `AGENT_RUNTIME_MAX_CONCURRENT_SESSIONS` to avoid over-scheduling | |

#### Agent Permission Manager

| Variable | Description | Secret |
|----------|-------------|--------|
| `AGENT_PERMISSION_CACHE_TTL_SECONDS` | TTL for cached permission calculations (role → SOP → Skill → MCP tool resolution) stored in Redis; lower values increase consistency at the cost of more frequent recalculation | |
| `AGENT_PERMISSION_CACHE_ENABLED` | Set to `false` to disable Redis caching of permission decisions; intended only for debugging — always `true` in production | |

#### Agent Gateway (Communication Hub Extension)

| Variable | Description | Secret |
|----------|-------------|--------|
| `AGENT_GATEWAY_BASE_URL` | Public base URL at which the Agent Gateway lifecycle endpoints are reachable; used when constructing callback URIs returned to callers | |
| `AGENT_GATEWAY_REQUEST_TIMEOUT_SECONDS` | Timeout for inbound agent execution requests before the gateway returns a timeout error; should be greater than `AGENT_RUNTIME_JOB_TIMEOUT_SECONDS` | |

### Changed Variables

| Variable | Previous Behaviour | New Behaviour |
|----------|--------------------|---------------|
| `AGENT_ENGINE_DEFAULT_MAX_INSTANCES` | Controlled concurrent instances per agent type in the former Agent Engine | Superseded by `AGENT_RUNTIME_MAX_CONCURRENT_SESSIONS` for overall session concurrency; retain for per-type cap enforcement via the Agent Runtime until fully migrated |

---

## 2. Infrastructure Changes

### New Service: Agent Session Worker

A dedicated background process — `agent-session-worker` — must be deployed alongside the existing backend services. It polls the Redis session queue (`AGENT_SESSION_QUEUE_NAME`), dispatches sessions to the Agent Runtime (powered by **LangGraph**), and updates session state in PostgreSQL.

- **Runs as**: a separate container (Docker Compose service or Kubernetes Deployment)
- **Depends on**: `postgres`, `redis`, and the OIDC provider being healthy
- **Python dependencies**: Requires **LangGraph** (`pip install langgraph`) for agent state machine execution
- **Scales horizontally**: multiple worker replicas may be deployed; each processes sessions independently via the shared Redis queue
- **Does NOT expose an HTTP port**: it is a consumer-only background process

### Modified Service: Communication Hub

The existing `communication-hub` container gains the Agent Gateway role — no new container is needed. The Communication Hub now handles inbound agent lifecycle protocol requests (init / request / question / answer / close) in addition to its existing WebSocket brokering responsibilities. For conversational agents, it maintains bidirectional WebSocket connections for chat message streaming.

- **No new container**: extend the existing `communication-hub` deployment
- **New env vars apply to this container**: `AGENT_GATEWAY_BASE_URL`, `AGENT_GATEWAY_REQUEST_TIMEOUT_SECONDS`

### Modified Service: Platform API

The Platform API gains new REST endpoints for agent role management, agent type configuration, identity provisioning, and session status polling. No new container is required; the existing `platform-api` container is updated.

- **New env vars apply to this container**: all `AGENT_RUNTIME_*`, `AGENT_PERMISSION_*`, and `AGENT_SESSION_QUEUE_*` variables

### Redis Queue Channels

No new Redis instance is required. Two new Redis constructs are added within the existing `redis` service:

| Construct | Key / Channel | Purpose |
|-----------|---------------|---------|
| Session Queue | value of `AGENT_SESSION_QUEUE_NAME` | Ordered list for async session dispatch to `agent-session-worker` |
---

## 3. Migration Steps

Follow these steps in order. Do not proceed to the next step until the previous step's completion condition is verified.

### Step 1 — Database Migration

Apply the Alembic migration to create new tables and modify `AgentType`.

- Run `alembic upgrade head` against the production database.
- **Completion condition**: `alembic current` reports the new migration ID with no pending upgrades. The tables `agent_role`, `agent_role_sop`, `agent_role_skill`, `agent_identity`, and `agent_job` are present in the database. The `agent_type` table has columns `identity_id`, `role_id`, `system_instruction`, `input_type`, `input_schema`, `output_type`, `output_schema` and no longer has `sop_id`, `identity_subject`, `system_prompt`, or `mode` columns.

### Step 2 — Data Migration (AgentType field backfill)

For any existing `AgentType` records, the removed fields (`sop_id`, `identity_subject`, `system_prompt`, `mode`) must be migrated to their replacements.

- For each existing AgentType: create a corresponding `AgentIdentity` record and set `identity_id`; populate `system_instruction` from `system_prompt`; create an `AgentRole` + `AgentRoleSOP` or `AgentRoleSkill` record reflecting the previous `sop_id` or Skill assignments.
- This migration may be performed via the new admin UI or a one-time CLI script run on the production host.
- **Completion condition**: No `AgentType` records have a null `role_id` or `identity_id` after the backfill; confirm by querying the `agent_type` table.

### Step 3 — Deploy Updated Platform API

Deploy the updated `platform-api` container image with all new environment variables set.

- Set `AGENT_RUNTIME_MAX_CONCURRENT_SESSIONS`, `AGENT_RUNTIME_SESSION_TIMEOUT_SECONDS`, `AGENT_RUNTIME_OIDC_TOKEN_ENDPOINT`, `AGENT_SESSION_QUEUE_NAME`, `AGENT_SESSION_QUEUE_RESULT_TTL_SECONDS`, `AGENT_PERMISSION_CACHE_TTL_SECONDS`, and `AGENT_PERMISSION_CACHE_ENABLED`.
- **Completion condition**: `GET /health` on the Platform API returns HTTP 200. New endpoints `GET /api/v1/agent-roles` and `GET /api/v1/agent-identities` respond without error.

### Step 4 — Deploy Agent Session Worker

Deploy the new `agent-session-worker` container with **LangGraph** dependency installed.

- Set `AGENT_SESSION_QUEUE_NAME` and `AGENT_SESSION_WORKER_CONCURRENCY` to match the values used by the Platform API.
- Ensure LangGraph is installed in the container image: `pip install langgraph`
- **Completion condition**: The worker container starts without error, connects to Redis, and logs that it is listening on the configured queue. Verify by submitting a test session via the Platform API and confirming the session transitions from `queued` → `running` → `completed` in the database.

### Step 5 — Deploy Updated Communication Hub

Deploy the updated `communication-hub` container image with Agent Gateway variables set.

- Set `AGENT_GATEWAY_BASE_URL` and `AGENT_GATEWAY_REQUEST_TIMEOUT_SECONDS`.
- **Completion condition**: `GET /health` on the Communication Hub returns HTTP 200. The Agent Gateway lifecycle endpoint (e.g., `POST /gateway/init`) responds with a valid Session ID. An end-to-end agent execution initiated from the Web UI completes successfully and the result appears in the Session dashboard.

### Step 6 — Permission Engine Verification

Confirm the Agent Permission Manager is computing and caching role permissions correctly.

- Navigate to the Agent Role management page in the Web UI; create a test role with one SOP and one direct Skill assignment. Verify the MCP tool preview panel shows the expected combined tool set.
- **Completion condition**: Tool preview for the test role shows the union of tools from the SOP's Skills and the directly assigned Skill, without duplicates. Redis shows a populated permission cache key for the test role ID.

---

## 4. Rollback Procedure

### Trigger Conditions

Initiate rollback if any of the following occur after deployment:

- Platform API health check fails and cannot be restored by restart
- Agent Session Worker fails to dequeue sessions and the queue length grows unbounded
- LangGraph dependency issues or state machine errors prevent session execution
- Database migration caused unexpected constraint violations or data loss
- The Agent Gateway returns 5xx errors for all inbound requests

### Rollback Steps

Execute in order:

**Step R1 — Revert Communication Hub**

Deploy the previous `communication-hub` image. Remove `AGENT_GATEWAY_BASE_URL` and `AGENT_GATEWAY_REQUEST_TIMEOUT_SECONDS` from its environment.

- **Completion condition**: Communication Hub health check passes; WebSocket messaging for existing conversations is restored.

**Step R2 — Stop Agent Session Worker

Stop and remove the `agent-session-worker` container.

- **Completion condition**: No worker containers are running. Any sessions in the `AGENT_SESSION_QUEUE_NAME` Redis list will remain queued and can be discarded or replayed after the incident is resolved.

**Step R3 — Revert Platform API**

Deploy the previous `platform-api` image. Remove all new `AGENT_RUNTIME_*`, `AGENT_SESSION_*`, `AGENT_PERMISSION_*`, and `AGENT_GATEWAY_*` environment variables.

- **Completion condition**: Platform API health check passes; existing endpoints respond normally.

**Step R4 — Database Rollback**

If the Alembic migration must be reversed, run `alembic downgrade -1` to revert the most recent migration.

- **Warning**: Running `alembic downgrade` will drop the `agent_role`, `agent_role_sop`, `agent_role_skill`, `agent_identity`, and `agent_session` tables and revert `agent_type` column changes. Any data entered via the new UI will be lost. Confirm with the team before executing.
- **Completion condition**: `alembic current` reports the previous migration ID. The `agent_role` table does not exist in the database. The `agent_type` table has its original columns (`sop_id`, `identity_subject`, `system_prompt`, `mode`).

**Step R5 — Cache Flush**

Flush the Redis permission cache keys to prevent stale data if rollback is later followed by a redeployment attempt.

- Remove all keys matching the pattern `agentperm:*` from Redis.
- **Completion condition**: No `agentperm:*` keys exist in Redis.

---

## 5. Master Deployment Update Instructions

When this change is promoted, update the following files in `docs/master/deployment/`:

| File | Update Required |
|------|----------------|
| `environment-variables.md` | Add all new variables from Section 1 under a new **Agent Runtime** group and an **Agent Session Queue** group; add the **Agent Permission Manager** group; add the **Agent Gateway** variables under the Communication Hub section; note the `AGENT_ENGINE_DEFAULT_MAX_INSTANCES` change; document LangGraph dependency requirement |
| `services.md` | Add `agent-session-worker` to the Service Inventory table as a new background worker (requires **LangGraph** dependency); update the `communication-hub` row to note Agent Gateway responsibility (including WebSocket support for conversational agents); update the service dependency graph to show `agent-session-worker` depending on `postgres` and `redis`, and `communication-hub` linking to `agent-session-worker` via the session queue |
| `database-migrations.md` | Document the migration step that creates `agent_role`, `agent_role_sop`, `agent_role_skill`, `agent_identity`, and `agent_session`; note the `agent_type` column additions and removals; document the `AgentSkillAssignment` table drop |
| `rollback.md` | Add rollback procedure for this change covering the `agent-session-worker` stop, Communication Hub revert, Platform API revert, and optional `alembic downgrade` path with the data-loss warning |
