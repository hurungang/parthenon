import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { useAgentDraftComposition, emptyDraft } from '../hooks/useAgentDraftComposition'
import type { AgentType, SkillBinding, SopBinding } from '../types'

// ── Module mocks ──────────────────────────────────────────────────────────────

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const { mockApiPut } = vi.hoisted(() => ({ mockApiPut: vi.fn() }))

vi.mock('../api/apiClient', () => ({
  default: {
    put: mockApiPut,
  },
}))

// ── Fixtures ──────────────────────────────────────────────────────────────────

const SKILL_BINDINGS: SkillBinding[] = [
  { id: 'sb-1', skill_id: 'skill-1', skill_name: 'Skill One', order: 1, created_at: '2026-01-01T00:00:00Z' },
  { id: 'sb-2', skill_id: 'skill-2', skill_name: 'Skill Two', order: 2, created_at: '2026-01-01T00:00:00Z' },
]

const SOP_BINDINGS: SopBinding[] = [
  { id: 'sob-1', sop_id: 'sop-1', sop_name: 'SOP One', order: 1, created_at: '2026-01-01T00:00:00Z' },
]

const AGENT: AgentType = {
  id: 'at-1',
  name: 'research-agent',
  description: 'desc',
  identity_id: 'identity-1',
  role_id: 'role-1',
  model_id: 'gpt-4o',
  system_instruction: 'inst',
  input_type: 'typed',
  input_schema: { type: 'object', properties: {} },
  output_type: 'typed',
  output_schema: null,
  output_data_type_id: 'dt-1',
  output_data_type_name: null,
  sop_bindings: SOP_BINDINGS,
  skill_bindings: SKILL_BINDINGS,
  guardrail_max_iterations: 10,
  guardrail_token_budget: 8000,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  plan: null,
}

const SAVED_AGENT: AgentType = {
  ...AGENT,
  role_id: 'role-2',
  updated_at: '2026-01-02T00:00:00Z',
}// ── Wrapper ────────────────────────────────────────────────────────────────────

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('useAgentDraftComposition', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('initializes the draft from the fetched AgentType', () => {
    const { result } = renderHook(() => useAgentDraftComposition(AGENT), { wrapper })

    expect(result.current.agentId).toBe('at-1')
    expect(result.current.isDirty).toBe(false)
    expect(result.current.propertiesChanged).toBe(false)
    expect(result.current.isNameInvalid).toBe(false)
    expect(result.current.draft).toEqual({
      name: 'research-agent',
      description: 'desc',
      systemInstruction: 'inst',
      guardrails: {
        maxIterations: 10,
        maxDelegationDepth: 3,
        maxDelegatedSteps: 20,
        executionTimeoutSeconds: 300,
        tokenBudget: 8000,
        tokenEnforcementMode: 'observe',
        tokenFallbackMode: 'observe_and_log',
        conversationalTokenVisibilityMode: 'enabled',
        conversationalContinuationPolicy: 'allow',
      },
      identityId: 'identity-1',
      roleId: 'role-1',
      skillBindings: [
        { skill_id: 'skill-1', order: 1 },
        { skill_id: 'skill-2', order: 2 },
      ],
      sopBindings: [{ sop_id: 'sop-1', order: 1 }],
      inputType: 'typed',
      inputSchema: { type: 'object', properties: {} },
      outputType: 'typed',
      outputSchema: null,
      outputDataTypeId: 'dt-1',
      modelId: 'gpt-4o',
    })
  })

  it('starts with an empty pristine draft when no agent is selected', () => {
    const { result } = renderHook(() => useAgentDraftComposition(null), { wrapper })

    expect(result.current.agentId).toBeNull()
    expect(result.current.draft).toEqual(emptyDraft())
    expect(result.current.isDirty).toBe(false)
  })

  it('marks the draft dirty on every equipment mutation without any API call', () => {
    const { result } = renderHook(() => useAgentDraftComposition(AGENT), { wrapper })

    act(() => result.current.setRole('role-2'))
    expect(result.current.isDirty).toBe(true)
    expect(result.current.draft.roleId).toBe('role-2')
    expect(mockApiPut).not.toHaveBeenCalled()

    act(() => result.current.setIdentity('identity-2'))
    expect(result.current.isDirty).toBe(true)

    act(() => result.current.setModel('gpt-4o-mini'))
    expect(result.current.draft.modelId).toBe('gpt-4o-mini')
    expect(mockApiPut).not.toHaveBeenCalled()
  })

  it('reports changed slot ids per mutated slot', () => {
    const { result } = renderHook(() => useAgentDraftComposition(AGENT), { wrapper })

    act(() => {
      result.current.setRole('role-2')
      result.current.setModel('gpt-4o-mini')
    })

    expect(result.current.changedSlotIds).toContain('role')
    expect(result.current.changedSlotIds).toContain('model')
    expect(result.current.changedSlotIds).not.toContain('identity')
  })

  it('mutates base properties in the draft and flags propertiesChanged', () => {
    const { result } = renderHook(() => useAgentDraftComposition(AGENT), { wrapper })

    act(() => {
      result.current.setName('renamed-agent')
      result.current.setDescription('new desc')
      result.current.setSystemInstruction('new instruction')
    })

    expect(result.current.isDirty).toBe(true)
    expect(result.current.propertiesChanged).toBe(true)
    expect(result.current.draft.name).toBe('renamed-agent')
    expect(result.current.draft.description).toBe('new desc')
    expect(result.current.draft.systemInstruction).toBe('new instruction')
    expect(mockApiPut).not.toHaveBeenCalled()
  })

  it('merges partial guardrail patches and flags propertiesChanged', () => {
    const { result } = renderHook(() => useAgentDraftComposition(AGENT), { wrapper })

    act(() => result.current.setGuardrails({ maxIterations: 25, tokenBudget: 120000 }))

    expect(result.current.isDirty).toBe(true)
    expect(result.current.propertiesChanged).toBe(true)
    expect(result.current.draft.guardrails.maxIterations).toBe(25)
    expect(result.current.draft.guardrails.tokenBudget).toBe(120000)
    // Untouched guardrail values survive the merge.
    expect(result.current.draft.guardrails.maxDelegationDepth).toBe(3)
    expect(result.current.draft.guardrails.tokenEnforcementMode).toBe('observe')
  })

  it('flags an empty or non-slug draft name as invalid', () => {
    const { result } = renderHook(() => useAgentDraftComposition(AGENT), { wrapper })
    expect(result.current.isNameInvalid).toBe(false)

    act(() => result.current.setName('Invalid Name!'))
    expect(result.current.isNameInvalid).toBe(true)

    act(() => result.current.setName(''))
    expect(result.current.isNameInvalid).toBe(true)

    act(() => result.current.setName('valid-name'))
    expect(result.current.isNameInvalid).toBe(false)
  })

  it('assigns a skill with the next binding order and rejects duplicates', () => {
    const { result } = renderHook(() => useAgentDraftComposition(AGENT), { wrapper })

    act(() => result.current.assignSkill('skill-3'))
    expect(result.current.draft.skillBindings).toEqual([
      { skill_id: 'skill-1', order: 1 },
      { skill_id: 'skill-2', order: 2 },
      { skill_id: 'skill-3', order: 3 },
    ])

    act(() => result.current.assignSkill('skill-3'))
    expect(result.current.draft.skillBindings).toHaveLength(3)
  })

  it('unassigns a skill and renumbers the remaining bindings', () => {
    const { result } = renderHook(() => useAgentDraftComposition(AGENT), { wrapper })

    act(() => result.current.unassignSkill('skill-1'))
    expect(result.current.draft.skillBindings).toEqual([{ skill_id: 'skill-2', order: 1 }])
  })

  it('moves a skill binding up and down', () => {
    const { result } = renderHook(() => useAgentDraftComposition(AGENT), { wrapper })

    act(() => result.current.moveSkill('skill-2', 'up'))
    expect(result.current.draft.skillBindings).toEqual([
      { skill_id: 'skill-2', order: 1 },
      { skill_id: 'skill-1', order: 2 },
    ])

    act(() => result.current.moveSkill('skill-2', 'down'))
    expect(result.current.draft.skillBindings).toEqual([
      { skill_id: 'skill-1', order: 1 },
      { skill_id: 'skill-2', order: 2 },
    ])
  })

  it('moves moving the first binding up and the last down to a no-op', () => {
    const { result } = renderHook(() => useAgentDraftComposition(AGENT), { wrapper })
    const before = result.current.draft.skillBindings

    act(() => result.current.moveSkill('skill-1', 'up'))
    act(() => result.current.moveSkill('skill-2', 'down'))
    expect(result.current.draft.skillBindings).toEqual(before)
  })

  it('assigns, unassigns and reorders SOP bindings symmetrically', () => {
    const { result } = renderHook(() => useAgentDraftComposition(AGENT), { wrapper })

    act(() => result.current.assignSop('sop-2'))
    expect(result.current.draft.sopBindings).toEqual([
      { sop_id: 'sop-1', order: 1 },
      { sop_id: 'sop-2', order: 2 },
    ])

    act(() => result.current.moveSop('sop-2', 'up'))
    expect(result.current.draft.sopBindings).toEqual([
      { sop_id: 'sop-2', order: 1 },
      { sop_id: 'sop-1', order: 2 },
    ])

    act(() => result.current.unassignSop('sop-2'))
    expect(result.current.draft.sopBindings).toEqual([{ sop_id: 'sop-1', order: 1 }])
  })

  it('locks the output data type for conversational agents (typed-output rule)', () => {
    const { result } = renderHook(() => useAgentDraftComposition(AGENT), { wrapper })

    // Switching to conversation clears the typed input schema and output data type.
    act(() => result.current.setInputType('conversation'))
    expect(result.current.draft.inputType).toBe('conversation')
    expect(result.current.draft.inputSchema).toBeNull()
    expect(result.current.draft.outputDataTypeId).toBeNull()

    // Assigning an output data type while conversational is a no-op.
    act(() => result.current.setOutputDataType('dt-9'))
    expect(result.current.draft.outputDataTypeId).toBeNull()
  })

  it('clears the output data type when the output type is not typed', () => {
    const { result } = renderHook(() => useAgentDraftComposition(AGENT), { wrapper })

    act(() => result.current.setOutputType('markdown'))
    expect(result.current.draft.outputDataTypeId).toBeNull()
  })

  it('discard reverts the draft to the last saved snapshot and clears dirty', () => {
    const { result } = renderHook(() => useAgentDraftComposition(AGENT), { wrapper })

    act(() => {
      result.current.setRole('role-2')
      result.current.assignSkill('skill-9')
      result.current.setName('renamed-agent')
      result.current.setSystemInstruction('changed instruction')
      result.current.setGuardrails({ maxIterations: 99 })
    })
    expect(result.current.isDirty).toBe(true)

    act(() => result.current.discard())
    expect(result.current.isDirty).toBe(false)
    expect(result.current.propertiesChanged).toBe(false)
    expect(result.current.draft.roleId).toBe('role-1')
    expect(result.current.draft.name).toBe('research-agent')
    expect(result.current.draft.systemInstruction).toBe('inst')
    expect(result.current.draft.guardrails.maxIterations).toBe(10)
    // Bindings are projected to {skill_id, order} pairs from the full fixtures.
    expect(result.current.draft.skillBindings).toEqual([
      { skill_id: 'skill-1', order: 1 },
      { skill_id: 'skill-2', order: 2 },
    ])
  })

  it('save issues exactly one PUT with the draft mapped onto the update payload', async () => {
    mockApiPut.mockResolvedValue({ data: SAVED_AGENT })
    const { result } = renderHook(() => useAgentDraftComposition(AGENT), { wrapper })

    act(() => {
      result.current.setRole('role-2')
      result.current.setName('renamed-agent')
      result.current.setSystemInstruction('new instruction')
      result.current.setGuardrails({ maxIterations: 25, tokenBudget: 120000 })
    })

    let saved: AgentType | null = null
    await act(async () => {
      saved = await result.current.save()
    })

    expect(mockApiPut).toHaveBeenCalledTimes(1)
    expect(mockApiPut).toHaveBeenCalledWith('/agents/types/at-1', expect.any(Object))
    const body = mockApiPut.mock.calls[0][1] as Record<string, unknown>
    // Edited equipment + base properties are sent from the draft.
    expect(body.role_id).toBe('role-2')
    expect(body.name).toBe('renamed-agent')
    expect(body.system_instruction).toBe('new instruction')
    expect(body.guardrail_max_iterations).toBe(25)
    expect(body.guardrail_token_budget).toBe(120000)
    // Unedited fields keep their draft (= saved) values.
    expect(body.description).toBe('desc')
    expect(body.skill_bindings).toEqual([
      { skill_id: 'skill-1', order: 1 },
      { skill_id: 'skill-2', order: 2 },
    ])

    // Draft is reset from the server response; dirty flag cleared.
    expect(saved).not.toBeNull()
    expect(result.current.isDirty).toBe(false)
    expect(result.current.draft.roleId).toBe('role-2')
    expect(result.current.draft.name).toBe('research-agent') // from SAVED_AGENT
    expect(result.current.changedSlotIds).toEqual([])
    expect(result.current.propertiesChanged).toBe(false)
  })

  it('save rejects an invalid slug name before any API call', async () => {
    const { result } = renderHook(() => useAgentDraftComposition(AGENT), { wrapper })

    act(() => result.current.setName('Invalid Name!'))

    await act(async () => {
      await expect(result.current.save()).rejects.toThrow()
    })
    expect(mockApiPut).not.toHaveBeenCalled()
    // Draft stays dirty so the tray keeps showing the pending change.
    expect(result.current.isDirty).toBe(true)
  })

  it('save throws on API failure (caller surfaces the error)', async () => {
    mockApiPut.mockRejectedValue(new Error('403 Forbidden'))
    const { result } = renderHook(() => useAgentDraftComposition(AGENT), { wrapper })

    act(() => result.current.setRole('role-2'))

    await act(async () => {
      await expect(result.current.save()).rejects.toThrow('403 Forbidden')
    })
    // Draft stays dirty so the tray keeps showing the pending change.
    expect(result.current.isDirty).toBe(true)
    expect(result.current.draft.roleId).toBe('role-2')
  })

  it('save returns null when no agent is selected', async () => {
    const { result } = renderHook(() => useAgentDraftComposition(null), { wrapper })

    let saved: AgentType | null = 'sentinel' as unknown as AgentType | null
    await act(async () => {
      saved = await result.current.save()
    })
    expect(saved).toBeNull()
    expect(mockApiPut).not.toHaveBeenCalled()
  })

  it('re-initializes the draft when a different agent is selected', () => {
    const { result, rerender } = renderHook(
      ({ agent }: { agent: AgentType | null }) => useAgentDraftComposition(agent),
      { initialProps: { agent: AGENT as AgentType | null }, wrapper },
    )

    act(() => result.current.setRole('role-2'))
    expect(result.current.isDirty).toBe(true)

    const otherAgent: AgentType = { ...AGENT, id: 'at-2', role_id: null, name: 'other' }
    rerender({ agent: otherAgent })

    expect(result.current.agentId).toBe('at-2')
    expect(result.current.draft.roleId).toBeNull()
    expect(result.current.isDirty).toBe(false)
  })

  it('does not wipe in-progress edits when the same agent object refreshes', () => {
    const { result, rerender } = renderHook(
      ({ agent }: { agent: AgentType | null }) => useAgentDraftComposition(agent),
      { initialProps: { agent: AGENT as AgentType | null }, wrapper },
    )

    act(() => result.current.setRole('role-2'))

    // Simulate a refetch returning a new object identity for the same version.
    rerender({ agent: { ...AGENT } })
    expect(result.current.isDirty).toBe(true)
    expect(result.current.draft.roleId).toBe('role-2')
  })

  it('resets to the empty draft when the selection is cleared', () => {
    const { result, rerender } = renderHook(
      ({ agent }: { agent: AgentType | null }) => useAgentDraftComposition(agent),
      { initialProps: { agent: AGENT as AgentType | null }, wrapper },
    )

    rerender({ agent: null })
    expect(result.current.agentId).toBeNull()
    expect(result.current.draft).toEqual(emptyDraft())
    expect(result.current.isDirty).toBe(false)
  })
})
