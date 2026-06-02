# Deployment Guide: Harden Agent Guardrails and Runtime Control Dashboard

Feature: harden-agent-guardrails-and-runtime-control-dashboard
Date: 2026-06-01
Status: Reconciled post-implementation

## Deployment Intent
Deploy runtime-control APIs, recursion validation gates, cascade termination orchestration, model-usage guardrails, and dashboard visibility updates while preserving service boundaries:
- Agent Runtime executes sessions.
- Control Center owns governance persistence.
- Communication Hub remains transport/orchestration.
- Frontend consumes backend APIs only.

## Implemented Artifacts
### Database migration
- Migration file: `backend/alembic/versions/aad0f4a3b3bc_harden_agent_guardrails_runtime_.py`
- Revision: `aad0f4a3b3bc`
- Creates governance tables:
  - `termination_requests`
  - `termination_cascade_outcomes`
  - `agent_run_relationships`
  - `model_guardrail_configurations`
  - `model_guardrail_evaluations`
  - `model_usage_postures`
  - `guardrail_threshold_events`
  - `sop_recursion_validation_checks`
  - `sop_recursion_validation_findings`
- Extends:
  - `agent_jobs` (parent/root/depth/termination/model guardrail links)
  - `agent_types` (recursion validation mode + last status/time)
  - `execution_log_entries` (`event_category`, `correlation_id`, `actor_type`)

### Runtime-control API surface
Implemented in `backend/app/api/v1/agents.py` via `RuntimeControlRouter`:
- `GET /api/v1/agents/runtime/topology`
- `POST /api/v1/agents/runtime/terminate`
- `GET /api/v1/agents/runtime/terminate/{request_id}`
- `GET /api/v1/agents/runtime/policy-events`

Model-usage API surface:
- `GET /api/v1/agents/guardrails/model-usage-limits`
- `POST /api/v1/agents/guardrails/model-usage-limits`
- `GET /api/v1/agents/guardrails/model-usage-limits/{config_id}`
- `PUT /api/v1/agents/guardrails/model-usage-limits/{config_id}`
- `DELETE /api/v1/agents/guardrails/model-usage-limits/{config_id}`
- `GET /api/v1/agents/guardrails/model-usage-posture?refresh=true`

## Configuration Notes
No new mandatory environment variables were introduced by this change in the current implementation.

Operational behavior is controlled primarily by persisted configuration and schema defaults:
- New model-usage guardrail records default to `terminate` enforcement posture.
- Topology and termination polling cadence is currently defined in frontend hooks:
  - `frontend/src/hooks/useRuntimeTopology.ts` (`refetchInterval: 5000`)
  - `frontend/src/hooks/useNodeTermination.ts` (`refetchInterval: 3000`)
  - `frontend/src/hooks/useModelUsagePosture.ts` (`refetchInterval: 15000`)

## Ordered Deployment Steps
1. Pre-deploy
- Ensure backend and frontend images include reconciled runtime-control code paths.
- Confirm database backup/snapshot policy is active.

2. Apply database migration
- Run `alembic upgrade head` in backend deployment context.
- Verify revision with `alembic current` and confirm `aad0f4a3b3bc` is active.

3. Deploy backend services
- Deploy Control Center first.
- Deploy Communication Hub second.
- Deploy Agent Runtime third.

4. Deploy frontend
- Deploy runtime dashboard updates after backend routes are available.

5. Post-deploy verification
- `GET /api/v1/agents/runtime/topology` returns 200/authorized response.
- `POST /api/v1/agents/runtime/terminate` accepts valid payload and returns structured request status.
- `GET /api/v1/agents/runtime/policy-events` returns filtered policy event entries.
- `GET /api/v1/agents/guardrails/model-usage-posture?refresh=true` returns posture rows.

## Rollback Procedure
### Triggers
- Runtime-control APIs fail consistently after rollout.
- Termination request lifecycle cannot complete.
- Policy-event filtering/log classification regresses.

### Steps
1. Roll back frontend release.
2. Roll back backend services in reverse order (Agent Runtime, Communication Hub, Control Center).
3. If required, run Alembic downgrade to previous revision (`e2a947f81c33`) after data impact assessment.
4. Re-run health and smoke checks for agent sessions and logs.

## Master Docs Follow-up
Update `docs/master/deployment/` after release finalization:
- `environment-variables.md` (no new required vars for this change; document polling constants if promoted to config later)
- `database-migrations.md` (add revision `aad0f4a3b3bc`)
- `services.md` (runtime-control API ownership and rollout sequence)
- `rollback.md` (runtime-control rollback sequence)
