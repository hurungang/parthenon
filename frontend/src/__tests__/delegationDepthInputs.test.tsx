import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import React from 'react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { UseAgentDraftCompositionResult } from '../hooks/useAgentDraftComposition'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn().mockImplementation((url: string) =>
      String(url).includes('data-types')
        ? Promise.resolve({ data: { items: [] } })
        : Promise.resolve({ data: [] }),
    ),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

/** Minimal draft API stub for AgentPropertiesSection (no hook/state needed). */
function makeDraftApi(
  guardrails: Partial<UseAgentDraftCompositionResult['draft']['guardrails']> = {},
): UseAgentDraftCompositionResult {
  const draft: UseAgentDraftCompositionResult['draft'] = {
    name: 'delegating-agent',
    description: '',
    systemInstruction: '',
    guardrails: {
      maxIterations: 10,
      maxDelegationDepth: 3,
      maxDelegatedSteps: 20,
      executionTimeoutSeconds: 300,
      tokenBudget: null,
      tokenEnforcementMode: 'observe',
      tokenFallbackMode: 'observe_and_log',
      conversationalTokenVisibilityMode: 'enabled',
      conversationalContinuationPolicy: 'allow',
      ...guardrails,
    },
    identityId: null,
    roleId: null,
    skillBindings: [],
    sopBindings: [],
    inputType: 'none',
    inputSchema: null,
    outputType: 'auto',
    outputSchema: null,
    outputDataTypeId: null,
    modelId: null,
  }

  return {
    agentId: 'agent-1',
    draft,
    isDirty: false,
    changedSlotIds: [],
    propertiesChanged: false,
    isNameInvalid: false,
    setName: vi.fn(),
    setDescription: vi.fn(),
    setSystemInstruction: vi.fn(),
    setGuardrails: vi.fn(),
    setIdentity: vi.fn(),
    setRole: vi.fn(),
    assignSkill: vi.fn(),
    unassignSkill: vi.fn(),
    moveSkill: vi.fn(),
    assignSop: vi.fn(),
    unassignSop: vi.fn(),
    moveSop: vi.fn(),
    setInputType: vi.fn(),
    setInputSchema: vi.fn(),
    setOutputType: vi.fn(),
    setOutputDataType: vi.fn(),
    setModel: vi.fn(),
    discard: vi.fn(),
    save: vi.fn().mockResolvedValue(null),
  }
}

describe('Max Delegation Depth configuration inputs', () => {
  it('Agent Type form accepts a depth above the former 32 ceiling', async () => {
    const { AgentTypeForm, defaultAgentTypeFormValues } = await import(
      '../pages/agents/AgentTypeForm'
    )
    const onChange = vi.fn()
    render(
      <AgentTypeForm values={defaultAgentTypeFormValues} onChange={onChange} />,
      { wrapper },
    )

    fireEvent.click(screen.getByRole('button', { name: /agents\.types\.guardrails\.title/ }))

    const input = screen.getByRole('spinbutton', {
      name: 'agents.types.guardrails.maxDelegationDepth',
    }) as HTMLInputElement

    // No hard-coded upper bound survives; the non-negative floor does.
    expect(input.getAttribute('max')).toBeNull()
    expect(input.getAttribute('min')).toBe('0')

    fireEvent.change(input, { target: { value: '40' } })

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ guardrail_max_delegation_depth: 40 }),
    )
  })

  it('Agent Type form keeps the non-negative minimum', async () => {
    const { AgentTypeForm, defaultAgentTypeFormValues } = await import(
      '../pages/agents/AgentTypeForm'
    )
    render(
      <AgentTypeForm values={defaultAgentTypeFormValues} onChange={vi.fn()} />,
      { wrapper },
    )
    fireEvent.click(screen.getByRole('button', { name: /agents\.types\.guardrails\.title/ }))

    const input = screen.getByRole('spinbutton', {
      name: 'agents.types.guardrails.maxDelegationDepth',
    }) as HTMLInputElement

    expect(input.min).toBe('0')
    expect(input.max).toBe('')
  })

  it('Agent Type form leaves other guardrail constraints unchanged', async () => {
    const { AgentTypeForm, defaultAgentTypeFormValues } = await import(
      '../pages/agents/AgentTypeForm'
    )
    render(
      <AgentTypeForm values={defaultAgentTypeFormValues} onChange={vi.fn()} />,
      { wrapper },
    )
    fireEvent.click(screen.getByRole('button', { name: /agents\.types\.guardrails\.title/ }))

    const iterations = screen.getByRole('spinbutton', {
      name: 'agents.types.guardrails.maxIterations',
    }) as HTMLInputElement
    const delegatedSteps = screen.getByRole('spinbutton', {
      name: 'agents.types.guardrails.maxDelegatedSteps',
    }) as HTMLInputElement

    expect(iterations.getAttribute('min')).toBe('1')
    expect(iterations.getAttribute('max')).toBe('1000')
    expect(delegatedSteps.getAttribute('min')).toBe('0')
    expect(delegatedSteps.getAttribute('max')).toBe('5000')
  })

  it('Agent Properties panel accepts a depth above the former 32 ceiling', async () => {
    const { AgentPropertiesSection } = await import(
      '../components/agents/panel/AgentPropertiesSection'
    )
    const draftApi = makeDraftApi()
    render(<AgentPropertiesSection draftApi={draftApi} />)

    fireEvent.click(screen.getByRole('button', { name: /agents\.types\.guardrails\.title/ }))

    const input = await waitFor(() =>
      screen.getByRole('spinbutton', {
        name: 'agents.types.guardrails.maxDelegationDepth',
      }) as HTMLInputElement,
    )

    expect(input.getAttribute('max')).toBeNull()
    expect(input.getAttribute('min')).toBe('0')

    fireEvent.change(input, { target: { value: '40' } })

    expect(draftApi.setGuardrails).toHaveBeenCalledWith({ maxDelegationDepth: 40 })
  })

  it('Agent Properties panel keeps the non-negative minimum', async () => {
    const { AgentPropertiesSection } = await import(
      '../components/agents/panel/AgentPropertiesSection'
    )
    render(<AgentPropertiesSection draftApi={makeDraftApi()} />)

    fireEvent.click(screen.getByRole('button', { name: /agents\.types\.guardrails\.title/ }))

    const input = (await waitFor(() =>
      screen.getByRole('spinbutton', {
        name: 'agents.types.guardrails.maxDelegationDepth',
      }),
    )) as HTMLInputElement

    expect(input.min).toBe('0')
    expect(input.max).toBe('')
  })
})
