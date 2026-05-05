import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => vi.fn() }
})

// Mutable sync state — lets individual tests control isPending / variables
const mockSyncState: { mutate: ReturnType<typeof vi.fn>; isPending: boolean; variables: string | undefined } = {
  mutate: vi.fn(),
  isPending: false,
  variables: undefined,
}

// Mock the hooks used by McpHubPage
vi.mock('../hooks/useMcpServers', () => ({
  useMcpServers: () => ({
    data: [
      { id: 'srv-1', name: 'Server One', slug: 'server-one', base_url: 'http://mcp.local/one', status: 'active', description: '' },
      { id: 'srv-2', name: 'Server Two', slug: 'server-two', base_url: 'http://mcp.local/two', status: 'active', description: '' },
    ],
    isLoading: false,
  }),
  useSyncServer: () => mockSyncState,
}))

vi.mock('../api/apiClient', () => ({
  default: {
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
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

describe('McpHubPage', () => {
  beforeEach(() => {
    // Reset sync state to idle before each test
    mockSyncState.isPending = false
    mockSyncState.variables = undefined
    mockSyncState.mutate = vi.fn()
  })

  it('renders the page heading', async () => {
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })
    expect(screen.getByText('mcp.title')).toBeDefined()
  })

  it('renders the servers from mock data', async () => {
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })
    expect(screen.getAllByText('Server One')[0]).toBeDefined()
    expect(screen.getAllByText('Server Two')[0]).toBeDefined()
  })

  it('renders server slugs', async () => {
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })
    expect(screen.getByText('server-one')).toBeDefined()
    expect(screen.getByText('server-two')).toBeDefined()
  })

  it('renders Register Server button', async () => {
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })
    expect(screen.getByRole('button', { name: /mcp\.registerServer/i })).toBeDefined()
  })

  it('opens dialog when Register Server is clicked', async () => {
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })
    fireEvent.click(screen.getByRole('button', { name: /mcp\.registerServer/i }))
    expect(screen.getByRole('dialog')).toBeDefined()
  })
})

/**
 * FAILING TESTS — Issue 2: All Servers Gray When One Is Syncing
 *
 * Root cause:
 *   useSyncServer() returns a SINGLE mutation instance shared across all rows.
 *   The sync button uses:  disabled={syncServer.isPending}
 *   When any sync is in-flight, isPending=true for the ENTIRE mutation,
 *   disabling ALL servers' sync buttons — not just the one being synced.
 *
 * Expected fix:
 *   Check  disabled={syncServer.isPending && syncServer.variables === server.id}
 *   so only the actively-syncing server's button is disabled.
 */
describe('McpHubPage — sync button state (Issue 2 reproduction)', () => {
  beforeEach(() => {
    mockSyncState.mutate = vi.fn()
  })

  it('FAILING: when srv-1 is syncing, only srv-1 sync button should be disabled (not srv-2)', async () => {
    // Simulate: srv-1 sync is in-flight
    mockSyncState.isPending = true
    mockSyncState.variables = 'srv-1'

    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })

    // MUI icons render with data-testid="SyncIcon" in tests
    // This lets us find ONLY the sync buttons, not edit/delete/sessions buttons
    const syncIcons = document.querySelectorAll('[data-testid="SyncIcon"]')
    const syncButtons = Array.from(syncIcons)
      .map((icon) => icon.closest('button'))
      .filter((btn): btn is HTMLButtonElement => btn !== null)

    // With 2 servers there should be exactly 2 sync buttons
    expect(syncButtons.length).toBe(2)

    const disabledSyncButtons = syncButtons.filter(
      (btn) => btn.hasAttribute('disabled') || btn.getAttribute('aria-disabled') === 'true'
    )

    // BUG: current code has disabled={syncServer.isPending}
    //      → both buttons disabled when isPending=true → disabledSyncButtons.length === 2
    // EXPECTED: after fix, disabled={syncServer.isPending && syncServer.variables === server.id}
    //           → only srv-1 disabled → disabledSyncButtons.length === 1
    //
    // This assertion FAILS with the current (buggy) implementation
    expect(disabledSyncButtons.length).toBe(1)
  })

  it('FAILING: when srv-2 is syncing, only srv-2 sync button should be disabled (not srv-1)', async () => {
    // Simulate: srv-2 sync is in-flight
    mockSyncState.isPending = true
    mockSyncState.variables = 'srv-2'

    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })

    const syncIcons = document.querySelectorAll('[data-testid="SyncIcon"]')
    const syncButtons = Array.from(syncIcons)
      .map((icon) => icon.closest('button'))
      .filter((btn): btn is HTMLButtonElement => btn !== null)

    expect(syncButtons.length).toBe(2)

    const disabledSyncButtons = syncButtons.filter(
      (btn) => btn.hasAttribute('disabled') || btn.getAttribute('aria-disabled') === 'true'
    )

    // Same bug: both sync buttons disabled when isPending=true
    // After fix: only srv-2's button is disabled
    expect(disabledSyncButtons.length).toBe(1)
  })

  it('when no sync is in-flight, all sync buttons should be enabled', async () => {
    mockSyncState.isPending = false
    mockSyncState.variables = undefined

    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })

    const syncIcons = document.querySelectorAll('[data-testid="SyncIcon"]')
    const syncButtons = Array.from(syncIcons)
      .map((icon) => icon.closest('button'))
      .filter((btn): btn is HTMLButtonElement => btn !== null)

    expect(syncButtons.length).toBe(2)

    const disabledSyncButtons = syncButtons.filter((btn) => btn.hasAttribute('disabled'))
    expect(disabledSyncButtons.length).toBe(0)
  })
})
