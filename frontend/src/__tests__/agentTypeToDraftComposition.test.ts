import { describe, it, expect } from 'vitest'
import { agentTypeToDraftComposition } from '../components/agents/agentTypeToDraftComposition'
import type { AgentType } from '../types'

const BASE_AGENT: AgentType = {
  id: 'at-1',
  name: 'research-agent',
  description: 'does research',
  identity_id: 'identity-1',
  role_id: 'role-1',
  model_id: 'gpt-4o',
  system_instruction: 'be helpful',
  input_type: 'typed',
  input_schema: { type: 'object', properties: {} },
  output_type: 'typed',
  output_schema: { type: 'object' },
  output_data_type_id: 'dt-1',
  output_data_type_name: 'report',
  sop_bindings: [
    { id: 'sb-1', sop_id: 'sop-2', sop_name: 'sop two', order: 2, created_at: '2026-01-01T00:00:00Z' },
    { id: 'sb-2', sop_id: 'sop-1', sop_name: 'sop one', order: 1, created_at: '2026-01-01T00:00:00Z' },
  ],
  skill_bindings: [
    { id: 'kb-1', skill_id: 'skill-1', skill_name: 'search', order: 1, created_at: '2026-01-01T00:00:00Z' },
  ],
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  plan: null,
}

describe('agentTypeToDraftComposition', () => {
  it('maps a fully configured typed agent into the draft composition', () => {
    const draft = agentTypeToDraftComposition(BASE_AGENT)

    expect(draft.name).toBe('research-agent')
    expect(draft.description).toBe('does research')
    expect(draft.systemInstruction).toBe('be helpful')
    expect(draft.identityId).toBe('identity-1')
    expect(draft.roleId).toBe('role-1')
    expect(draft.modelId).toBe('gpt-4o')
    expect(draft.inputType).toBe('typed')
    expect(draft.inputSchema).toEqual({ type: 'object', properties: {} })
    expect(draft.outputType).toBe('typed')
    expect(draft.outputSchema).toEqual({ type: 'object' })
    expect(draft.outputDataTypeId).toBe('dt-1')
    // Bindings are reduced to (id, order) inputs, order preserved.
    expect(draft.sopBindings).toEqual([
      { sop_id: 'sop-2', order: 2 },
      { sop_id: 'sop-1', order: 1 },
    ])
    expect(draft.skillBindings).toEqual([{ skill_id: 'skill-1', order: 1 }])
  })

  it('maps a conversational agent without guardrail columns (defaults applied)', () => {
    const draft = agentTypeToDraftComposition({
      ...BASE_AGENT,
      input_type: 'conversation',
      input_schema: null,
      output_data_type_id: null,
      guardrail_max_iterations: 25,
    })

    expect(draft.inputType).toBe('conversation')
    expect(draft.inputSchema).toBeNull()
    expect(draft.guardrails.maxIterations).toBe(25)
    // Untouched optional guardrails fall back to the hook's defaults.
    expect(draft.guardrails.maxDelegationDepth).toBe(3)
    expect(draft.guardrails.maxDelegatedSteps).toBe(20)
    expect(draft.guardrails.executionTimeoutSeconds).toBe(300)
    expect(draft.guardrails.tokenBudget).toBeNull()
    expect(draft.guardrails.tokenEnforcementMode).toBe('observe')
    expect(draft.guardrails.tokenFallbackMode).toBe('observe_and_log')
    expect(draft.guardrails.conversationalTokenVisibilityMode).toBe('enabled')
    expect(draft.guardrails.conversationalContinuationPolicy).toBe('allow')
  })

  it('maps a minimal agent type (no bindings, no optional fields) without error', () => {
    const draft = agentTypeToDraftComposition({
      id: 'at-2',
      name: 'bare-agent',
      description: null,
      identity_id: null,
      role_id: null,
      model_id: null,
      system_instruction: null,
      input_type: 'none',
      input_schema: null,
      output_type: 'auto',
      output_schema: null,
      output_data_type_id: null,
      output_data_type_name: null,
      is_active: false,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    })

    expect(draft).toMatchObject({
      name: 'bare-agent',
      description: '',
      systemInstruction: '',
      identityId: null,
      roleId: null,
      modelId: null,
      skillBindings: [],
      sopBindings: [],
      inputSchema: null,
      outputDataTypeId: null,
    })
  })

  it('is pure — the input agent object is never mutated', () => {
    const clone = structuredClone(BASE_AGENT)
    agentTypeToDraftComposition(BASE_AGENT)
    expect(BASE_AGENT).toEqual(clone)
  })
})
