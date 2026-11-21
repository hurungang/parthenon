# Agent Entities — Runtime Control & Guardrails

[← Agent entities hub](entities.md) · [Data model overview](../../overview.md)

Model-usage guardrails, evaluation outcomes, usage posture, and the runtime
control / termination / recursion-validation entities.

## Model Guardrail and Runtime Control Entities

The following entities support the **vendor → model → guardrail hierarchy** for model-usage guardrails and the **Runtime Control Dashboard** for live execution visibility and operator-controlled termination.

```mermaid
erDiagram
    ModelGuardrailConfiguration {
        uuid id
        uuid model_id
        string model_name
        enum period
        int max_units
        enum enforcement_posture
        boolean is_active
        datetime created_at
        datetime updated_at
    }
    ModelAvailability {
        uuid id
        uuid model_id
        string model_name
        boolean is_disabled
        enum disabled_reason
        datetime disabled_at
        datetime created_at
        datetime updated_at
    }
    ModelUsagePosture {
        uuid id
        uuid model_id
        string model_name
        enum period
        enum posture_state
        int current_units
        datetime last_updated_at
    }
    AgentInstance {
        uuid id
        uuid agent_type_id
        string instance_id
        enum status
        datetime created_at
        datetime closed_at
    }
    AgentRunRelationship {
        uuid id
        uuid parent_session_id
        uuid child_session_id
        enum relationship_type
        datetime created_at
    }
    TerminationRequest {
        uuid id
        uuid target_session_id
        string target_node_kind
        uuid requested_by
        enum status
        enum outcome
        datetime requested_at
        datetime completed_at
    }
    TerminationCascadeOutcome {
        uuid id
        uuid termination_request_id
        uuid affected_session_id
        enum outcome
        datetime observed_at
    }
    GuardrailThresholdEvent {
        uuid id
        uuid guardrail_id
        uuid session_id
        enum event_category
        enum posture_state
        int units_at_event
        datetime occurred_at
    }
    SopRecursionValidationCheck {
        uuid id
        uuid agent_type_id
        uuid triggered_by_user_id
        enum check_trigger
        enum result
        datetime performed_at
    }
    SopRecursionValidationFinding {
        uuid id
        uuid check_id
        uuid sop_id
        string cycle_path_json
    }

    ModelGuardrailConfiguration }o--|| ModelConfig : "applies to"
    ModelAvailability }o--|| ModelConfig : "applies to"
    ModelUsagePosture }o--|| ModelConfig : "applies to"
    AgentInstance }o--|| AgentType : "instantiated from"
    AgentRunRelationship }o--|| AgentSession : "parent"
    AgentRunRelationship }o--|| AgentSession : "child"
    TerminationRequest }o--o| AgentSession : "targets"
    TerminationCascadeOutcome }o--|| TerminationRequest : "cascade from"
    GuardrailThresholdEvent }o--|| ModelGuardrailConfiguration : "raised against"
    SopRecursionValidationFinding }o--|| SopRecursionValidationCheck : "found by"
```

**Sources**: `backend/app/db/models/model_guardrail_configuration.py`, `backend/app/db/models/model_usage_posture.py`, `backend/app/db/models/model_availability.py`, `backend/app/db/models/guardrail_threshold_event.py`, `backend/app/db/models/agent_run_relationship.py`, `backend/app/db/models/termination_request.py`, `backend/app/db/models/termination_cascade_outcome.py`, `backend/app/db/models/sop_recursion_validation_check.py`, `backend/app/db/models/sop_recursion_validation_finding.py`

| Entity | Description |
|--------|-------------|
| **ModelGuardrailConfiguration** | One guardrail per model per period (hour/day/week/month). `enforcement_posture` is `terminate` (default) or `observe-only`; `is_active` toggles the period independently. |
| **ModelAvailability** | Per-model availability state. `is_disabled=True` blocks execution; `disabled_reason` is `vendor_disabled` (cascade from vendor-level disable) or `model_disabled` (manual). |
| **ModelUsagePosture** | Current usage posture against a guardrail limit. `posture_state` is `within_limit`, `approaching_limit`, or `breached`. When `breached` and the guardrail's `enforcement_posture` is `terminate`, the agent execution is blocked. |
| **AgentInstance** | A logical agent instance in the dashboard; `instance_id` is the canonical key for `AgentInstanceCertificate` lookup. `status` is `created` / `active` / `closed` / `error`. |
| **AgentRunRelationship** | Parent/child edges between `AgentSession` records for delegated execution. The relationship graph is rendered in the runtime topology diagram and walked during cascade termination. |
| **TerminationRequest** | An operator-initiated termination against a session. `target_node_kind` is `agent` (live job) or `conversation` (idle session); `status` is `pending`/`completed`/`failed`, `outcome` `cancelled`/`not_found`/`error`. |
| **TerminationCascadeOutcome** | One row per delegated child affected by a parent termination. Captures whether each child was successfully cancelled, not found, or errored. |
| **GuardrailThresholdEvent** | Append-only log of guardrail threshold transitions. `event_category` is one of `model_disabled`, `vendor_disabled`, `guardrail_breached`. `posture_state` is the new state at the time of the event. |
| **SopRecursionValidationCheck** | Records a recursion/dead-loop risk validation at create, update, or run initiation. `check_trigger` is `create` / `update` / `run`; `result` is `pass` / `fail`. |
| **SopRecursionValidationFinding** | The specific cycle path(s) found by a `SopRecursionValidationCheck`. Stores the cycle path as a JSON array of SOP IDs. |
| **ModelGuardrailEvaluation** | Per-run evaluation outcome for model guardrail policy checks. Records the guardrail configuration, agent job, policy name, evaluated period, threshold value, observed value, posture state, and evaluation outcome (pass/fail/error). |
| **ExecutionLogEntry** | Immutable audit trail of agent session execution events (LLM calls, tool calls, system events, errors). Categorised by event type and actor type; referenced by `agent_job_id` for session-scoped queries. |

**Business rules:**
- A model may have one to four `ModelGuardrailConfiguration` records (one per period); there is no forced four-period entry.
- `ModelAvailability.disabled_reason = vendor_disabled` indicates a cascade from vendor-level disable; the model's guardrail records stay visible as the cascade source.
- `AgentJob.status` accepts `terminated` as a distinct value from `failed`, enabling operators to distinguish operator-initiated stops from execution errors.
- `ExecutionEventCategory` accepts `model_disabled`, `vendor_disabled`, and `guardrail_breached` as user-visible event categories for execution logs. These are distinct from standard execution failures.
- `SopRecursionValidationCheck` runs at every agent create, update, and run; `result = fail` blocks the action.
