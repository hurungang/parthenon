import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

import { AgentTypeForm, defaultAgentTypeFormValues } from '../../pages/agents/AgentTypeForm'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const { mockApiGet, mockSyncState } = vi.hoisted(() => ({
  mockApiGet: vi.fn(),
  mockSyncState: {
    mutate: vi.fn(),
    isPending: false,
    variables: undefined as string | undefined,
  },
}))

vi.mock('../../api/apiClient', () => ({
  default: {
    get: mockApiGet,
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

vi.mock('../../hooks/useMcpServers', () => ({
  useMcpServers: () => ({
    data: [],
    isLoading: false,
    error: null,
  }),
  useSyncServer: () => mockSyncState,
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('Slug Validation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockApiGet.mockResolvedValue({ data: [] })
    mockSyncState.mutate = vi.fn()
    mockSyncState.isPending = false
    mockSyncState.variables = undefined
  })

  it('agent type name rejects uppercase characters', () => {
    render(
      <AgentTypeForm
        values={{ ...defaultAgentTypeFormValues, name: 'Invalid-Agent' }}
        onChange={vi.fn()}
      />,
      { wrapper },
    )

    const nameInput = screen.getByLabelText(/app\.name/i)
    expect(nameInput).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByText('agents.types.slugNameHelper')).toBeDefined()
  })

  it('agent type name rejects spaces', () => {
    render(
      <AgentTypeForm
        values={{ ...defaultAgentTypeFormValues, name: 'invalid agent' }}
        onChange={vi.fn()}
      />,
      { wrapper },
    )

    const nameInput = screen.getByLabelText(/app\.name/i)
    expect(nameInput).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByText('agents.types.slugNameHelper')).toBeDefined()
  })

  it('agent type name accepts lowercase alphanumeric hyphen values', () => {
    render(
      <AgentTypeForm
        values={{ ...defaultAgentTypeFormValues, name: 'research-agent-01' }}
        onChange={vi.fn()}
      />,
      { wrapper },
    )

    const nameInput = screen.getByLabelText(/app\.name/i)
    expect(nameInput).toHaveAttribute('aria-invalid', 'false')
    expect(screen.getByText('agents.types.slugNameHint')).toBeDefined()
  })

  it('agent type slug validation matches the backend pattern', () => {
    render(
      <AgentTypeForm
        values={{ ...defaultAgentTypeFormValues, name: 'agent_name' }}
        onChange={vi.fn()}
      />,
      { wrapper },
    )

    const nameInput = screen.getByLabelText(/app\.name/i)
    expect(nameInput).toHaveAttribute('aria-invalid', 'true')

    render(
      <AgentTypeForm
        values={{ ...defaultAgentTypeFormValues, name: 'agent-name-2' }}
        onChange={vi.fn()}
      />,
      { wrapper },
    )

    expect(screen.getAllByLabelText(/app\.name/i)[1]).toHaveAttribute('aria-invalid', 'false')
  })

  it('mcp server name validates the slug pattern', async () => {
    const { McpHubPage } = await import('../../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })

    fireEvent.click(screen.getByRole('button', { name: /mcp\.registerServer/i }))
    fireEvent.change(screen.getByLabelText(/app\.name/i), { target: { value: 'Invalid Server' } })

    expect(screen.getAllByText('Lowercase letters, numbers, hyphens only').length).toBeGreaterThan(0)
  })

  it('mcp server slug blocks save until the value is slug-safe', async () => {
    const { McpHubPage } = await import('../../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })

    fireEvent.click(screen.getByRole('button', { name: /mcp\.registerServer/i }))

    fireEvent.change(screen.getByLabelText(/app\.name/i), { target: { value: 'valid-server' } })
    fireEvent.change(screen.getByLabelText(/mcp\.slug/i), { target: { value: 'bad slug' } })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /app\.save/i })).toBeDisabled()
    })

    fireEvent.change(screen.getByLabelText(/mcp\.slug/i), { target: { value: 'good-slug' } })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /app\.save/i })).not.toBeDisabled()
    })
  })
})