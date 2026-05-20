/**
 * Unit tests for AssignMcpSessionsToRoleDialog — passthrough badge (Task 10.3)
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import React from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockApiClient = {
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
}
vi.mock('../api/apiClient', () => ({ default: mockApiClient }))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

const mockRole = {
  id: 'role-1',
  name: 'Test Role',
  description: '',
  sops: [],
  skills: [],
}

describe('AssignMcpSessionsToRoleDialog — passthrough badge (Task 10.3)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows Passthrough chip next to passthrough session names', async () => {
    const availableSessions = [
      {
        id: 'sess-pt',
        name: 'Passthrough Session',
        server_id: 'server-1',
        server_name: 'MCP Demo',
        server_slug: 'mcp-demo',
        auth_type: 'passthrough',
      },
    ]
    const assignedSessions: unknown[] = []

    mockApiClient.get.mockImplementation((url: string) => {
      if (url.includes('available-mcp-sessions')) return Promise.resolve({ data: availableSessions })
      if (url.includes('mcp-sessions')) return Promise.resolve({ data: assignedSessions })
      return Promise.resolve({ data: [] })
    })

    const { AssignMcpSessionsToRoleDialog } = await import(
      '../pages/agents/AssignMcpSessionsToRoleDialog'
    )
    render(
      <AssignMcpSessionsToRoleDialog
        open={true}
        role={mockRole as any}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.queryByText('Passthrough Session')).not.toBeNull()
      // The Passthrough chip should be visible
      expect(screen.queryByText('Passthrough')).not.toBeNull()
    }, { timeout: 3000 })
  })

  it('shows regular session without Passthrough chip', async () => {
    const availableSessions = [
      {
        id: 'sess-1',
        name: 'API Key Session',
        server_id: 'server-1',
        server_name: 'MCP Demo',
        server_slug: 'mcp-demo',
        auth_type: 'api_key',
      },
    ]

    mockApiClient.get.mockImplementation((url: string) => {
      if (url.includes('available-mcp-sessions')) return Promise.resolve({ data: availableSessions })
      if (url.includes('mcp-sessions')) return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })

    const { AssignMcpSessionsToRoleDialog } = await import(
      '../pages/agents/AssignMcpSessionsToRoleDialog'
    )
    render(
      <AssignMcpSessionsToRoleDialog
        open={true}
        role={mockRole as any}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.queryByText('API Key Session')).not.toBeNull()
      // No Passthrough chip for regular sessions
      expect(screen.queryByText('Passthrough')).toBeNull()
    }, { timeout: 3000 })
  })
})
