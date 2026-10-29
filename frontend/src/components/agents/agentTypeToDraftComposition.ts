import type {
  AgentDraftComposition,
  AgentDraftGuardrails,
  AgentType,
} from '../../types'

/**
 * Fallback guardrails — must stay identical to the defaults used by
 * `useAgentDraftComposition` (AgentTypeForm's optional-column fallbacks).
 */
const DEFAULT_GUARDRAILS: AgentDraftGuardrails = {
  maxIterations: 10,
  maxDelegationDepth: 3,
  maxDelegatedSteps: 20,
  executionTimeoutSeconds: 300,
  tokenBudget: null,
  tokenEnforcementMode: 'observe',
  tokenFallbackMode: 'observe_and_log',
  conversationalTokenVisibilityMode: 'enabled',
  conversationalContinuationPolicy: 'allow',
}

/**
 * Thin pure adapter mapping a loaded, read-only `AgentType` into the
 * `AgentDraftComposition` shape consumed by `PanelTopologyCanvas`, mirroring
 * the draft initialization in `frontend/src/hooks/useAgentDraftComposition.ts`.
 * Used by the agent preview dialog to feed the canonical panel topology canvas
 * — glue only: no mutation, no persistence, `isDirty` is effectively false.
 */
export function agentTypeToDraftComposition(agent: AgentType): AgentDraftComposition {
  return {
    name: agent.name,
    description: agent.description ?? '',
    systemInstruction: agent.system_instruction ?? '',
    guardrails: {
      ...DEFAULT_GUARDRAILS,
      maxIterations: agent.guardrail_max_iterations ?? DEFAULT_GUARDRAILS.maxIterations,
      maxDelegationDepth:
        agent.guardrail_max_delegation_depth ?? DEFAULT_GUARDRAILS.maxDelegationDepth,
      maxDelegatedSteps: agent.guardrail_max_delegated_steps ?? DEFAULT_GUARDRAILS.maxDelegatedSteps,
      executionTimeoutSeconds:
        agent.guardrail_execution_timeout_seconds ?? DEFAULT_GUARDRAILS.executionTimeoutSeconds,
      tokenBudget: agent.guardrail_token_budget ?? null,
      tokenEnforcementMode: agent.guardrail_token_enforcement_mode ?? 'observe',
      tokenFallbackMode: agent.guardrail_token_fallback_mode ?? 'observe_and_log',
      conversationalTokenVisibilityMode:
        agent.guardrail_conversational_token_visibility_mode ?? 'enabled',
      conversationalContinuationPolicy:
        agent.guardrail_conversational_continuation_policy ?? 'allow',
    },
    identityId: agent.identity_id ?? null,
    roleId: agent.role_id ?? null,
    skillBindings: (agent.skill_bindings ?? []).map((b) => ({
      skill_id: b.skill_id,
      order: b.order,
    })),
    sopBindings: (agent.sop_bindings ?? []).map((b) => ({
      sop_id: b.sop_id,
      order: b.order,
    })),
    inputType: agent.input_type,
    inputSchema: agent.input_schema ? { ...agent.input_schema } : null,
    outputType: agent.output_type,
    outputSchema: agent.output_schema ? { ...agent.output_schema } : null,
    outputDataTypeId: agent.output_data_type_id ?? null,
    modelId: agent.model_id ?? null,
  }
}
