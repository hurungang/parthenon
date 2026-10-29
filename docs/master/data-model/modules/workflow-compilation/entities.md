# Workflow Compilation (Script Registry) — Entities

Model-authored, sandboxed workflow scripts and their lifecycle evidence:
definitions, immutable versions, verification runs, execution records,
fallback events, and repair attempts. All entities are Control-Center-owned
(`tenant_id` FK, `SET NULL`); Agent Runtime consumes them exclusively via
mTLS Control Center REST APIs. Lifecycle is `draft → verified → compiled → retired`;
script version content is immutable. There is **no execution-mode
configuration** — script-first execution with unconditional LLM fallback is
fixed platform behavior, not configuration.

```mermaid
erDiagram
    AgentType ||--o{ ScriptDefinition : "owns"
    AgentPlan ||--o{ ScriptDefinition : "compiled from"
    OptimizedImplementationPlan ||--o{ ScriptDefinition : "authored"
    ScriptDefinition ||--o{ ScriptVersion : "has"
    ScriptDefinition |o--o| ScriptVersion : "current compiled version"
    ScriptVersion ||--o{ VerificationRun : "verified by"
    ScriptVersion ||--o{ ScriptExecutionRecord : "executed as"
    ScriptVersion |o--o| ScriptVersion : "repaired_from"
    ScriptExecutionRecord ||--o{ FallbackEvent : "may trigger"
    FallbackEvent }o--|| ScriptVersion : "involves"
    FallbackEvent ||--o{ RepairAttempt : "drives"
    RepairAttempt }o--o| ScriptVersion : "produces repaired candidate"
    AgentJob |o--o{ ScriptExecutionRecord : "identity/permission context"

    ScriptDefinition {
        uuid tenant_id
        uuid agent_type_id "owning agent type; identity/permissions inherited"
        uuid source_plan_id "base plan lineage, optional"
        uuid source_optimized_plan_id "optimized plan lineage, optional"
        uuid source_session_id "observed LLM run lineage, optional"
        uuid current_version_id "serving version, absent while draft/unverified"
        string name "unique per tenant"
        string description
        enum lifecycle_status "draft|verified|compiled|retired"
        enum health_status "healthy|degraded|unhealthy (aggregate from fallbacks)"
        boolean fully_scripted "zero-LLM serving vs scripts-as-tools"
    }
    ScriptVersion {
        uuid script_definition_id
        uuid parent_version_id "prior version derived from, optional"
        uuid repaired_from_id "defective version repaired by this one, optional"
        string version_label "ordered identity within parent script"
        enum lifecycle_status "draft|verified|compiled|retired"
        text python_source "model-authored sandboxed Python (immutable)"
        int cpu_limit_seconds "resource cap; platform default when null"
        int memory_limit_mb
        int wall_time_limit_seconds
        enum sandbox_validation_status "pending|passed|failed"
        text sandbox_validation_reason
        json declarative_step_graph "deprecated-but-retained"
        string created_by "run or actor that produced this version"
    }
    VerificationRun {
        uuid script_version_id "candidate under test"
        uuid reference_job_id "recorded LLM run used as ground truth"
        json input_context "retained comparison evidence"
        json expected_output
        json actual_output
        enum comparison_outcome "match|match_within_tolerance|mismatch"
        enum verdict "promote_to_compiled|reject_to_draft"
        string verdict_reason
        boolean sandbox_check_passed "sandbox-compliance evidence"
    }
    ScriptExecutionRecord {
        uuid tenant_id
        uuid script_version_id "version served, optional"
        uuid session_id "FK to AgentJob — the run's identity/permission context"
        enum outcome "success|validation_failure|fell_back"
        int duration_ms
        json tools_invoked "MCP tool calls made, 0..many"
        json model_backed_steps_used "semantic-bridge/decision steps, 0..many"
        boolean identity_parity_confirmed "session identities used, no separate identity"
        int tokens_saved_estimate "historical rows only"
        int tokens_saved_actual "measured tokens avoided vs LLM baseline"
        boolean sandbox_termination "ended via resource-cap safe-kill"
        text sandbox_violation_detail "one-line human-readable reason"
    }
    FallbackEvent {
        uuid execution_record_id
        uuid script_version_id "defective version involved"
        enum trigger_reason "execution_error|tool_schema_mismatch|output_validation_failure|repair_exhaustion|sandbox_violation|resource_limit_exceeded"
        text failure_detail "context needed for repair"
        enum resulting_action "llm_completed|repair_candidate_produced"
        int repair_attempts_used "bounded retries within this episode"
    }
    RepairAttempt {
        uuid fallback_event_id
        uuid script_version_id "defective version being repaired"
        uuid repaired_version_id "successor candidate, 0..1; must re-verify"
        text defect_diagnosis
        text diff_applied
        enum retry_outcome "pending|succeeded|failed"
    }
```

**Sources**: `backend/app/db/models/script_registry.py` — ScriptDefinition, ScriptVersion, VerificationRun, FallbackEvent, RepairAttempt · `backend/app/db/models/script_execution.py` — ScriptExecutionRecord

| Entity | Description |
|--------|-------------|
| **ScriptDefinition** | The registry's primary entity — a versioned, named bridge script compiled from an agent workflow. Belongs to exactly one Agent Type whose identity/permissions it inherits (no credentials of its own). Carries lifecycle status, lineage to the base plan / optimized plan / observed session, the current serving version pointer, and aggregate health derived from recent fallback behavior. |
| **ScriptVersion** | An immutable revision of a Script Definition. Carries the model-authored sandboxed Python content with per-version resource caps, sandbox-validation outcome, parent version lineage, distinct repair lineage (`repaired_from`), and the producing actor. |
| **VerificationRun** | Evidence record of shadow-running a Script Version against a recorded LLM execution on identical inputs: retained input/expected/actual, comparison outcome within declared tolerance, and the promote/reject verdict with reason. Rejection returns the version to draft. |
| **ScriptExecutionRecord** | One execution of a compiled script (or its fallback run), bound to an Agent Job whose identity/permission context is always passed — the script never authenticates independently. Records outcome, duration, tools invoked, model-backed steps used, identity-parity evidence, and measured token savings. |
| **FallbackEvent** | Recorded whenever a script run failed and execution fell back to the LLM path. Fallback is unconditional and mode-independent. Captures trigger reason, failure detail, resulting action, and the contribution to the script's health degradation. |
| **RepairAttempt** | One bounded, agent-driven repair cycle within a fallback episode: defect diagnosis, diff applied, retry outcome, and the optional successor Script Version produced (which must re-verify before promotion). Budget exhaustion triggers unconditional fallback. |

**Business rules:**
- Script version content and resource caps are immutable per version; lifecycle progresses `draft → verified → compiled → retired`.
- A repair-produced candidate version carries `repaired_from` lineage (separate from generic parent lineage) so defect-driven repair chains are auditable, and must pass verification before promotion to compiled.
- Aggregate `health_status` on the Script Definition degrades with repeated fallback events.
- Only Control Center persists registry and execution data; Agent Runtime consumes them exclusively via Control Center REST APIs.
