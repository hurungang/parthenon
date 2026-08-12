# Deployment Guide: Add Agent Execution Guardrails

Feature: add-agent-execution-guardrails  
Date: 2026-05-22  
Status: Ready for deployment planning

## Deployment Intent
Deploy bounded execution controls for agent sessions with four guardrail families:
- Per-agent maximum cumulative iterations (including delegated chain activity)
- Per-agent wall-clock timeout
- Mode-aware token controls: conversational current-session token visibility with continuation, and token-budget enforcement for non-conversational or automated runs with explicit fallback when hard enforcement is unsupported
- Recursive delegation cycle detection with pre-execution block

The rollout must preserve service segregation:
- Agent Runtime enforces guardrails during execution
- Communication Hub forwards requests/outcomes without policy ownership
- Control Center remains policy source-of-truth and persistence owner

## Environment Variables

### Agent Runtime
| Variable | Required | Purpose |
| --- | --- | --- |
| AGENT_GUARDRAIL_MAX_ITERATIONS | Yes | Default cumulative iteration ceiling applied when agent-type policy does not override. Counts local and delegated chain activity. |
| AGENT_GUARDRAIL_EXEC_TIMEOUT_SECONDS | Yes | Default wall-clock timeout per session execution. |
| AGENT_GUARDRAIL_MAX_DELEGATION_DEPTH | Yes | Maximum allowed delegation depth for execution chain traversal. |
| AGENT_GUARDRAIL_MAX_DELEGATED_STEPS | Yes | Maximum delegated-step budget across the execution chain. |
| AGENT_GUARDRAIL_TOKEN_BUDGET_ENABLED | Yes | Enables token-budget guardrail evaluation path for non-conversational and automated execution modes. |
| AGENT_GUARDRAIL_TOKEN_BUDGET_DEFAULT | No | Optional default token cap when agent-type policy does not provide one. |
| AGENT_GUARDRAIL_TOKEN_FALLBACK_MODE | Yes | Behavior when hard token enforcement is unsupported for non-conversational or automated runs (for example observe_and_log or stop_on_next_hard_guardrail). |
| AGENT_GUARDRAIL_CONVERSATIONAL_TOKEN_VISIBILITY_ENABLED | Yes | Enables continuous current-session token-usage visibility in conversational sessions. |
| AGENT_GUARDRAIL_CONVERSATIONAL_TOKEN_CONTINUE_ENABLED | Yes | Allows conversational sessions to continue when token threshold is reached, provided other guardrails are not exceeded. |
| AGENT_GUARDRAIL_CYCLE_DETECTION_ENABLED | Yes | Enables pre-execution recursive delegation cycle detection and hard block. |

### Control Center
| Variable | Required | Purpose |
| --- | --- | --- |
| AGENT_GUARDRAIL_POLICY_ENFORCEMENT | Yes | Enables policy resolution and validation for guardrail fields in context payloads. |
| AGENT_GUARDRAIL_STOP_REASON_PERSISTENCE | Yes | Enables persistence of structured guardrail stop reasons in session state. |
| AGENT_GUARDRAIL_CONVERSATIONAL_TOKEN_TELEMETRY_PERSISTENCE | Yes | Enables persistence of conversational current-session token usage and continuation-path metadata in status/log payloads. |
| AGENT_GUARDRAIL_POLICY_VERSION | No | Version marker for policy rollout tracking and rollback coordination. |

### Communication Hub
| Variable | Required | Purpose |
| --- | --- | --- |
| AGENT_GUARDRAIL_STOP_REASON_FORWARDING | Yes | Preserves guardrail stop metadata in forwarded responses and A2A paths. |
| AGENT_GUARDRAIL_POLICY_PAYLOAD_PASSTHROUGH | Yes | Preserves policy snapshot payload fields without remapping. |
| AGENT_GUARDRAIL_TOKEN_TELEMETRY_FORWARDING | Yes | Preserves conversational token-usage visibility and continuation metadata in forwarded responses and A2A paths. |

Implementation note:
- Exact variable names can be adjusted to match existing naming standards, but semantics above must remain unchanged.

## Infrastructure Changes
- Ensure all three services are deployed at versions that support guardrail stop-reason metadata and policy snapshot fields.
- Verify Agent Runtime has no direct database connectivity and continues using Control Center internal data APIs for policy and status updates.
- Verify Communication Hub forwards stop metadata unchanged for both direct execution and A2A delegated flows.
- Verify Communication Hub forwards conversational token-usage visibility metadata unchanged for both direct execution and A2A delegated flows.
- Ensure observability pipelines can ingest guardrail decision events and terminal stop reasons.
- Ensure observability pipelines can ingest conversational token-usage visibility events and continuation-path metadata.
- Confirm environment/secret distribution includes all required guardrail variables before cutover.

## Migration Steps (Ordered)
1. Pre-deployment validation
- Confirm target releases for Control Center, Agent Runtime, and Communication Hub include guardrail contract compatibility.
- Confirm default guardrail thresholds are approved by platform operations and governance owners.

2. Configure Control Center policy readiness
- Enable guardrail policy enforcement and stop-reason persistence in Control Center.
- Publish policy version marker for traceability.

3. Configure Agent Runtime defaults
- Set iteration, timeout, delegation depth/steps, token fallback defaults, and conversational token visibility and continuation flags.
- Enable cycle detection.

4. Configure Communication Hub forwarding
- Enable stop-reason forwarding and policy payload passthrough flags.
- Validate no field remapping drops guardrail metadata.

5. Deploy Control Center first
- Roll out Control Center with policy and persistence changes.
- Validate context payload contains effective guardrail policy snapshot.

6. Deploy Communication Hub second
- Roll out Communication Hub forwarding updates.
- Validate guardrail terminal metadata is preserved through routing paths.

7. Deploy Agent Runtime third
- Roll out runtime guardrail enforcement.
- Validate pre-execution cycle block behavior and runtime limit enforcement in controlled smoke runs.

8. Post-deploy verification
- Execute representative direct and delegated sessions.
- Confirm guardrail stops are clearly classified (cycle, iteration, timeout, depth/steps, token/fallback) and persisted.
- Confirm conversational sessions continuously show current-session token usage and continue when token thresholds are reached unless another guardrail triggers stop.
- Confirm non-conversational and automated runs still enforce token-budget stop behavior when supported.

## Rollback Procedure

### Rollback Triggers
- Unexpected guardrail stops on known-good workloads after rollout.
- Conversational sessions hard-stop solely due to token budget threshold.
- Missing or corrupted guardrail stop metadata in session status/log pathways.
- Missing or corrupted conversational token-usage visibility or continuation metadata in status/log pathways.
- Service compatibility mismatch causing execution failures after deployment.

### Immediate Rollback Steps
1. Disable new guardrail enforcement flags in Agent Runtime while keeping baseline execution active.
2. Revert Communication Hub forwarding flags to last known-good behavior that preserves session outcomes.
3. Revert Control Center guardrail policy/persistence toggle to previous stable mode.
4. Redeploy last known-good versions in reverse order: Agent Runtime, Communication Hub, Control Center.
5. Re-run smoke validation for direct and delegated execution paths.
6. Validate conversational sessions no longer experience token-budget-only hard stop behavior after rollback stabilization.

### Rollback Guardrails
- Do not introduce direct database access from Agent Runtime or Communication Hub.
- Do not remove audit visibility for stop outcomes during rollback.
- Keep stop-reason field compatibility stable to avoid downstream parsing regressions.

## Master Deployment Update Instructions
Update the following master deployment docs after this change is implemented:
- docs/master/deployment/environment-variables.md
  - Add guardrail environment variables by service (runtime, control center, communication hub), including defaults and required flags.
- docs/master/deployment/services.md
  - Document rollout order and service responsibility boundaries for guardrail policy, enforcement, forwarding, and persistence.
- docs/master/deployment/operational-runbooks.md
  - Add deployment validation checklist for cycle detection, cumulative iteration accounting, timeout, conversational token visibility and continuation behavior, and token fallback behavior.
- docs/master/deployment/rollback.md
  - Add rollback triggers and ordered rollback sequence for guardrail rollout.
- docs/master/deployment/README.md
  - Add a section referencing guardrail rollout prerequisites, deployment order, and verification expectations.
