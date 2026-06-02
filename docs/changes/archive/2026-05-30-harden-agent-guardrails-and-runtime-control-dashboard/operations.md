# Operations: Harden Agent Guardrails and Runtime Control Dashboard

## Purpose
Define runtime-control monitoring and incident-response guidance for implemented features:
- recursion/dead-loop validation outcomes,
- runtime topology visibility,
- permission-gated node termination and cascade outcomes,
- model-usage guardrail posture,
- policy-event filtering in execution logs.

This operations guidance preserves platform boundaries:
- Agent Runtime executes.
- Control Center governs and persists.
- Communication Hub transports/orchestrates.
- Sensitive credentials and tokens are never exposed in operator surfaces.

## Implemented Observability Surface
### Execution log fields (persisted)
Execution log entries now include:
- `event_category` (`functional`, `guardrail`, `posture`, `termination`, `validation`)
- `correlation_id`
- `actor_type` (`system`, `user`, `operator`)

Primary model: `backend/app/db/models/session_logs.py`

### Runtime-control APIs used for operations
- `GET /api/v1/agents/runtime/topology`
- `POST /api/v1/agents/runtime/terminate`
- `GET /api/v1/agents/runtime/terminate/{request_id}`
- `GET /api/v1/agents/runtime/policy-events`
- `GET /api/v1/agents/sessions/{session_id}/logs`

Primary router: `backend/app/api/v1/agents.py`

### Frontend operator surfaces
- Runtime dashboard and controls: `frontend/src/pages/agents/AgentInstanceDashboardPage.tsx`
- Topology panel: `frontend/src/components/agents/RuntimeTopologyPanel.tsx`
- Termination dialog: `frontend/src/components/agents/NodeTerminationDialog.tsx`
- Model usage posture panel: `frontend/src/components/agents/ModelUsageGuardrailPanel.tsx`
- Execution log rendering: `frontend/src/components/executions/LogViewer.tsx`, `frontend/src/components/executions/WorkingStepsPanel.tsx`

## Operational Checks
### Daily checks
1. Confirm topology endpoint returns active nodes/edges for running sessions.
2. Confirm policy-events endpoint returns entries for `guardrail`, `termination`, and `validation` categories when applicable.
3. Confirm model-usage posture endpoint returns posture rows for configured limits.

### Termination workflow checks
1. Submit a node-only termination for a known running node in non-production validation environments.
2. Verify request record is returned and outcomes are retrievable.
3. Verify failed/denied requests preserve explicit reason text.

### Recursion validation checks
1. Validate create/update/run paths return `recursion_validation_failed` contract for known cycle fixture scenarios.
2. Confirm findings are persisted in recursion validation check/finding tables.

## Common Failure Modes and Response
### 1) Topology panel empty during active runs
Likely causes:
- no running sessions,
- stale polling client state,
- backend route auth/context mismatch.

Response:
1. Call `GET /api/v1/agents/runtime/topology?include_terminal=true` directly.
2. If API has nodes but UI is empty, inspect frontend query state and browser auth.
3. If API is empty unexpectedly, inspect active `agent_jobs` and relationship records.

### 2) Termination request accepted but no cascade outcomes
Likely causes:
- partial runtime execution failure,
- stale request id lookup,
- orchestration exception after request creation.

Response:
1. Query `GET /api/v1/agents/runtime/terminate/{request_id}`.
2. Inspect `termination_requests` and `termination_cascade_outcomes` for the same request id.
3. Re-issue targeted termination for remaining active nodes if required.

### 3) Recursion blocks spike after SOP changes
Likely causes:
- newly introduced delegation cycle,
- changed recursion validation mode expectations.

Response:
1. Aggregate recent failed create/update/run requests.
2. Review stored findings path signatures.
3. Roll back offending SOP/delegation change and retest.

### 4) Model usage posture appears stale
Likely causes:
- no recent session activity for configured models,
- posture refresh path not invoked,
- inconsistent model mapping.

Response:
1. Query `GET /api/v1/agents/guardrails/model-usage-posture?refresh=true` directly.
2. Validate active model guardrail configurations exist and are active.
3. Inspect recent model guardrail evaluation and posture records.

## Runbook References to Update
Update master docs under `docs/master/operations`:
- `monitoring.md`
- `logging.md`
- `runbooks/agent-execution-guardrails.md`
- `README.md`

## Operational Acceptance Criteria
- Operators can inspect topology, termination lifecycle, and policy events from backend APIs and UI.
- Termination denial/partial outcomes are visible and auditable.
- Recursion validation outcomes are queryable and actionable.
- Model-usage posture can be refreshed and inspected for configured limits.
- Policy-event categories are distinguishable from functional failures.
