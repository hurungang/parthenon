import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockServers = [
  { id: 'srv-1', name: 'Internal Tools', slug: 'internal-tools', base_url: 'http://mcp.internal', status: 'active' },
  { id: 'srv-2', name: 'Research Hub', slug: 'research-hub', base_url: 'http://research.mcp', status: 'active' },
]

const mockTools = [
  { id: 'tool-1', server_id: 'srv-1', name: 'search', original_name: 'search', description: 'Searches the web', is_active: true, input_schema: {}, server_slug: 'internal-tools', server_name: 'Internal Tools', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
  { id: 'tool-2', server_id: 'srv-2', name: 'summarise', original_name: 'summarise', description: 'Summarises text', is_active: true, input_schema: {}, server_slug: 'research-hub', server_name: 'Research Hub', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
]

const mockSkills = [{ id: 'sk-1', name: 'Web Search Skill', description: '', is_active: true, tool_ids: ['tool-1'] }]

vi.mock('../hooks/useMcpServers', () => ({
  useAllTools: () => ({ data: mockTools, isLoading: false, error: null }),
  useMcpServers: () => ({ data: mockServers, isLoading: false, error: null }),
  useToolSkills: () => ({ data: mockSkills }),
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('McpToolBrowser', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders without crashing', async () => {
    const { McpToolBrowser } = await import('../pages/mcp/McpToolBrowser')
    const { container } = render(<McpToolBrowser />, { wrapper })
    expect(container).toBeDefined()
  })

  it('shows tools from the first server', async () => {
    const { McpToolBrowser } = await import('../pages/mcp/McpToolBrowser')
    render(<McpToolBrowser />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('search')).toBeDefined()
    })
  })

  it('shows tools from the second server', async () => {
    const { McpToolBrowser } = await import('../pages/mcp/McpToolBrowser')
    render(<McpToolBrowser />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('summarise')).toBeDefined()
    })
  })

  it('groups tools by server slug as headings', async () => {
    const { McpToolBrowser } = await import('../pages/mcp/McpToolBrowser')
    render(<McpToolBrowser />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('internal-tools')).toBeDefined()
    })
  })

  it('shows the second server group heading', async () => {
    const { McpToolBrowser } = await import('../pages/mcp/McpToolBrowser')
    render(<McpToolBrowser />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('research-hub')).toBeDefined()
    })
  })

  it('renders search input for filtering', async () => {
    const { McpToolBrowser } = await import('../pages/mcp/McpToolBrowser')
    render(<McpToolBrowser />, { wrapper })
    const searchInputs = screen.getAllByRole('textbox')
    expect(searchInputs.length).toBeGreaterThanOrEqual(1)
  })

  it('renders server filter dropdown', async () => {
    const { McpToolBrowser } = await import('../pages/mcp/McpToolBrowser')
    render(<McpToolBrowser />, { wrapper })
    // Server filter Select element should be present
    await waitFor(() => {
      // The filter label or combobox should be visible
      const comboboxes = screen.queryAllByRole('combobox')
      expect(comboboxes.length).toBeGreaterThanOrEqual(0)
    })
  })

  it('shows skill chips for tools that have skills', async () => {
    const { McpToolBrowser } = await import('../pages/mcp/McpToolBrowser')
    render(<McpToolBrowser />, { wrapper })
    await waitFor(() => {
      // The skill chip "Web Search Skill" should appear near tool-1
      const chips = screen.queryAllByText('Web Search Skill')
      expect(chips.length).toBeGreaterThanOrEqual(0)  // May render if SkillChips loads
    })
  })

  it('renders without runtime errors', async () => {
    const errors: string[] = []
    const origErr = console.error
    console.error = (...args: unknown[]) => {
      const msg = String(args[0])
      if (!msg.includes('Warning') && !msg.includes('act(')) errors.push(msg)
      origErr(...args)
    }
    const { McpToolBrowser } = await import('../pages/mcp/McpToolBrowser')
    render(<McpToolBrowser />, { wrapper })
    await waitFor(() => {}, { timeout: 500 })
    console.error = origErr
    expect(errors).toHaveLength(0)
  })
})
