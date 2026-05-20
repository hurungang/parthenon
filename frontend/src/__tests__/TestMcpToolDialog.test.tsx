/**
 * Unit tests for TestMcpToolDialog — passthrough branch (Task 9.6)
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import React from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../components/DynamicSchemaForm', () => ({
  DynamicSchemaForm: () => <div data-testid="dynamic-schema-form" />,
}))

const mockApiClient = {
  get: vi.fn(),
  post: vi.fn(),
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

const baseTool = {
  id: 'tool-1',
  name: 'mcp-demo/greet',
  original_name: 'greet',
  description: 'Greet tool',
  input_schema: { type: 'object', properties: { name: { type: 'string' } } },
  server_id: 'server-1',
}

describe('TestMcpToolDialog — passthrough branch (Task 9.6)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows agent identity picker instead of session picker for passthrough servers', async () => {
    const passthroughSessions = [
      {
        id: 'sess-pt',
        name: 'Passthrough Session',
        server_id: 'server-1',
        auth_type: 'passthrough',
      },
    ]
    const agentIdentities = [
      { id: 'ident-1', name: 'My Agent', realm_username: 'agent@realm' },
    ]

    mockApiClient.get.mockImplementation((url: string) => {
      if (url.includes('/sessions')) return Promise.resolve({ data: passthroughSessions })
      if (url.includes('/agents/identities')) return Promise.resolve({ data: agentIdentities })
      return Promise.resolve({ data: [] })
    })

    const { TestMcpToolDialog } = await import('../pages/mcp/TestMcpToolDialog')
    render(<TestMcpToolDialog open={true} tool={baseTool} onClose={vi.fn()} />, { wrapper })

    // Wait for sessions to load
    await waitFor(() => {
      // Passthrough info alert should be displayed
      expect(screen.queryAllByText('mcp.sessions.passthroughInfo').length).toBeGreaterThan(0)
    }, { timeout: 3000 })

    // Session picker label ("MCP Session") should NOT appear
    expect(screen.queryAllByText('MCP Session').length).toBe(0)
    // Identity picker label should appear (may appear multiple times due to MUI)
    expect(screen.queryAllByText('Execute as agent identity').length).toBeGreaterThan(0)
  })

  it('shows regular session picker for non-passthrough servers', async () => {
    const normalSessions = [
      {
        id: 'sess-1',
        name: 'API Key Session',
        server_id: 'server-1',
        auth_type: 'api_key',
      },
    ]

    mockApiClient.get.mockImplementation((url: string) => {
      if (url.includes('/sessions')) return Promise.resolve({ data: normalSessions })
      return Promise.resolve({ data: [] })
    })

    const { TestMcpToolDialog } = await import('../pages/mcp/TestMcpToolDialog')
    render(<TestMcpToolDialog open={true} tool={baseTool} onClose={vi.fn()} />, { wrapper })

    await waitFor(() => {
      // Regular session picker should appear (MUI renders label in multiple places)
      expect(screen.queryAllByText('MCP Session').length).toBeGreaterThan(0)
    }, { timeout: 3000 })

    // Passthrough alert should NOT appear
    expect(screen.queryAllByText('mcp.sessions.passthroughInfo').length).toBe(0)
  })
})
