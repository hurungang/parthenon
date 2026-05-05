import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { defaultAgentTypeFormValues } from '../pages/agents/AgentTypeForm'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: [] }),
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

describe('AgentTypeForm', () => {
  it('renders name field', async () => {
    const { AgentTypeForm } = await import('../pages/agents/AgentTypeForm')
    render(
      <AgentTypeForm values={defaultAgentTypeFormValues} onChange={vi.fn()} />,
      { wrapper },
    )
    expect(screen.getByLabelText(/app\.name/)).toBeDefined()
  })

  it('renders system_instruction field', async () => {
    const { AgentTypeForm } = await import('../pages/agents/AgentTypeForm')
    render(
      <AgentTypeForm values={defaultAgentTypeFormValues} onChange={vi.fn()} />,
      { wrapper },
    )
    await waitFor(() => {
      expect(screen.getByText('agents.types.systemInstruction', { selector: 'label' })).toBeDefined()
    })
  })

  it('renders identity_id dropdown', async () => {
    const { AgentTypeForm } = await import('../pages/agents/AgentTypeForm')
    render(
      <AgentTypeForm values={defaultAgentTypeFormValues} onChange={vi.fn()} />,
      { wrapper },
    )
    await waitFor(() => {
      expect(screen.getByText('agents.types.identity', { selector: 'label' })).toBeDefined()
    })
  })

  it('renders role_id dropdown', async () => {
    const { AgentTypeForm } = await import('../pages/agents/AgentTypeForm')
    render(
      <AgentTypeForm values={defaultAgentTypeFormValues} onChange={vi.fn()} />,
      { wrapper },
    )
    await waitFor(() => {
      expect(screen.getByText('agents.types.role', { selector: 'label' })).toBeDefined()
    })
  })

  it('renders input_type dropdown with all three options', async () => {
    const { AgentTypeForm } = await import('../pages/agents/AgentTypeForm')
    render(
      <AgentTypeForm values={defaultAgentTypeFormValues} onChange={vi.fn()} />,
      { wrapper },
    )
    await waitFor(() => {
      expect(screen.getByText('agents.types.inputType', { selector: 'label' })).toBeDefined()
    })
  })

  it('renders output_type dropdown', async () => {
    const { AgentTypeForm } = await import('../pages/agents/AgentTypeForm')
    render(
      <AgentTypeForm values={defaultAgentTypeFormValues} onChange={vi.fn()} />,
      { wrapper },
    )
    await waitFor(() => {
      expect(screen.getByText('agents.types.outputType', { selector: 'label' })).toBeDefined()
    })
  })

  it('does NOT render old mode field', async () => {
    const { AgentTypeForm } = await import('../pages/agents/AgentTypeForm')
    render(
      <AgentTypeForm values={defaultAgentTypeFormValues} onChange={vi.fn()} />,
      { wrapper },
    )
    expect(screen.queryByText('agents.mode')).toBeNull()
    expect(screen.queryByText('agents.operatingMode')).toBeNull()
  })

  it('does NOT render max_instances field', async () => {
    const { AgentTypeForm } = await import('../pages/agents/AgentTypeForm')
    render(
      <AgentTypeForm values={defaultAgentTypeFormValues} onChange={vi.fn()} />,
      { wrapper },
    )
    expect(screen.queryByText('agents.maxInstances')).toBeNull()
    expect(screen.queryByText('max_instances')).toBeNull()
  })

  it('does NOT render sop_id field', async () => {
    const { AgentTypeForm } = await import('../pages/agents/AgentTypeForm')
    render(
      <AgentTypeForm values={defaultAgentTypeFormValues} onChange={vi.fn()} />,
      { wrapper },
    )
    expect(screen.queryByText('agents.sop')).toBeNull()
    expect(screen.queryByText('sop_id')).toBeNull()
  })

  it('shows input schema field when input_type is typed', async () => {
    const { AgentTypeForm } = await import('../pages/agents/AgentTypeForm')
    const values = { ...defaultAgentTypeFormValues, input_type: 'typed' as const }
    render(
      <AgentTypeForm values={values} onChange={vi.fn()} />,
      { wrapper },
    )
    await waitFor(() => {
      expect(screen.getByText('agents.types.inputSchema')).toBeDefined()
    })
  })

  it('does NOT show input schema field for input_type=none', async () => {
    const { AgentTypeForm } = await import('../pages/agents/AgentTypeForm')
    const values = { ...defaultAgentTypeFormValues, input_type: 'none' as const }
    render(
      <AgentTypeForm values={values} onChange={vi.fn()} />,
      { wrapper },
    )
    expect(screen.queryByText('agents.types.inputSchema')).toBeNull()
  })
})
