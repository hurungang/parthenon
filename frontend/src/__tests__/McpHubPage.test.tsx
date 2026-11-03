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

// Default mock servers — mutable so tests can override (subset of McpServer
// plus the FIX-20261101-090438 optional is_system_managed flag)
type MockServer = Partial<import('../types').McpServer> & { slug: string }
let mockServers: MockServer[] = [
  {
    id: '00000000-0000-0000-0000-000000000001',
    name: 'System',
    slug: 'system',
    base_url: 'http://mcp.system.local',
    status: 'active',
    description: '',
    session_count: 0,
  },
  {
    id: 'srv-1',
    name: 'Server One',
    slug: 'server-one',
    base_url: 'http://mcp.local/one',
    status: 'active',
    description: '',
    session_count: 1,
  },
  {
    id: 'srv-2',
    name: 'Server Two',
    slug: 'server-two',
    base_url: 'http://mcp.local/two',
    status: 'active',
    description: '',
    session_count: 2,
  },
]

// Mutable sync state — lets individual tests control isPending / variables
const mockSyncState: { mutate: ReturnType<typeof vi.fn>; isPending: boolean; variables: string | undefined } = {
  mutate: vi.fn(),
  isPending: false,
  variables: undefined,
}

// Mock the hooks used by McpHubPage
vi.mock('../hooks/useMcpServers', () => ({
  useMcpServers: () => ({
    data: mockServers,
    isLoading: false,
  }),
  useSyncServer: () => mockSyncState,
}))

vi.mock('../hooks/usePagination', () => ({
  usePagination: () => ({
    page: 0,
    rowsPerPage: 25,
    offset: 0,
    limit: 25,
    onPageChange: vi.fn(),
    onRowsPerPageChange: vi.fn(),
    resetPage: vi.fn(),
    rowsPerPageOptions: [10, 25, 50, 100],
  }),
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
    // Reset mock servers to default with session counts
    mockServers.length = 0
    mockServers.push(
      {
        id: '00000000-0000-0000-0000-000000000001',
        name: 'System',
        slug: 'system',
        base_url: 'http://mcp.system.local',
        status: 'active',
        description: '',
        session_count: 0,
      },
      {
        id: 'srv-1',
        name: 'Server One',
        slug: 'server-one',
        base_url: 'http://mcp.local/one',
        status: 'active',
        description: '',
        session_count: 1,
      },
      {
        id: 'srv-2',
        name: 'Server Two',
        slug: 'server-two',
        base_url: 'http://mcp.local/two',
        status: 'active',
        description: '',
        session_count: 2,
      }
    )
  })

  it('renders the page heading', async () => {
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })
    expect(screen.getByText('mcp.title')).toBeDefined()
  })

  it('renders the servers from mock data', async () => {
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })
    expect(screen.getAllByText('server-one')[0]).toBeDefined()
    expect(screen.getAllByText('server-two')[0]).toBeDefined()
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
describe('McpHubPage — System Entry', () => {
  beforeEach(() => {
    mockSyncState.isPending = false
    mockSyncState.mutate = vi.fn()
    // Setup mock servers with the virtual System entry + real server
    mockServers.length = 0
    mockServers.push(
      {
        id: '00000000-0000-0000-0000-000000000001',
        name: 'System',
        slug: 'system',
        base_url: '',
        status: 'active',
        description: 'Built-in system tools available to all agents',
        session_count: 0,
      },
      {
        id: 'srv-1',
        name: 'Server One',
        slug: 'server-one',
        base_url: 'http://mcp.local/one',
        status: 'active',
        description: '',
        session_count: 1,
      }
    )
  })

  it('renders System entry with Built-in chip', async () => {
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })

    // The System entry should be present with "Built-in" label
    const builtInChips = screen.queryAllByText('mcp.system.builtIn')
    expect(builtInChips.length).toBeGreaterThanOrEqual(1)

    // System entry is the first row in the table — slug shown as "system"
    expect(screen.getByText('system')).toBeDefined()
  })

  it('System entry shows disabled actions and system-managed text', async () => {
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })

    // System entry should show the "system managed" text (disabled actions)
    const systemManagedTexts = screen.queryAllByText('mcp.system.systemManaged')
    expect(systemManagedTexts.length).toBeGreaterThanOrEqual(1)
  })

  it('System entry shows system slug and has no sync action enabled', async () => {
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })

    // System slug shows as 'system'
    const systemSlug = screen.queryByText('system')
    expect(systemSlug).not.toBeNull()
  })

  it('Decision entry renders as built-in — Built-in chip, no edit/delete/sync', async () => {
    // The virtual Decision server (user-defined decision tools) must be
    // treated like the System entry: built-in, not editable or deletable.
    mockServers.push({
      id: 'decision-virtual-id',
      name: 'decision',
      slug: 'decision',
      base_url: '',
      status: 'active',
      description: "User-defined decision tools of this workspace",
      session_count: 0,
    })
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })

    // Built-in chips cover both System and Decision entries
    expect(screen.getAllByText('mcp.system.builtIn').length).toBe(2)
    // Decision row shows the decision-managed caption instead of edit/delete icons
    expect(screen.getAllByText('mcp.system.systemManaged').length).toBe(2)
    // No edit/delete targets the decision server row; sync is disabled
    const row = screen.getByText('decision').closest('tr')
    expect(row?.querySelectorAll('button').length).toBe(1) // disabled sync only
    expect(row?.querySelectorAll('button[disabled]').length).toBe(1)
  })
})

describe('McpHubPage — Sync button visibility based on session_count', () => {
  beforeEach(() => {
    mockSyncState.isPending = false
    mockSyncState.mutate = vi.fn()
  })

  it('sync button is disabled with tooltip when session_count === 0', async () => {
    // Server with zero sessions
    mockServers.length = 0
    mockServers.push({
      id: 'srv-zero',
      name: 'Zero Session Server',
      slug: 'zero-sessions',
      base_url: 'http://mcp.local/zero',
      status: 'active',
      description: '',
      session_count: 0,
    })

    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    const { container } = render(<McpHubPage />, { wrapper })

    // Find sync icon for this server row — it should be disabled
    const syncIcons = container.querySelectorAll('[data-testid="SyncIcon"]')
    // The System entry + our server: there should be sync icons
    // System entry has a disabled sync icon; our server should also have disabled
    const syncButtons = Array.from(syncIcons)
      .map((icon) => icon.closest('button'))
      .filter((btn): btn is HTMLButtonElement => btn !== null)

    // All sync buttons on this page should be disabled (System + zero-session server)
    const disabledButtons = syncButtons.filter(
      (btn) => btn.hasAttribute('disabled') || btn.getAttribute('aria-disabled') === 'true'
    )
    expect(disabledButtons.length).toBe(syncButtons.length)
  })

  it('sync button is enabled when session_count > 0', async () => {
    // Server with sessions
    mockServers.length = 0
    // Add System server (always disabled)
    mockServers.push({
      id: '00000000-0000-0000-0000-000000000001',
      name: 'System',
      slug: 'system',
      base_url: 'http://mcp.system.local',
      status: 'active',
      description: '',
      session_count: 0,
    })
    // Add server with sessions (should be enabled)
    mockServers.push({
      id: 'srv-one',
      name: 'Has Sessions Server',
      slug: 'has-sessions',
      base_url: 'http://mcp.local/one',
      status: 'active',
      description: '',
      session_count: 2,
    })

    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    const { container } = render(<McpHubPage />, { wrapper })

    const syncIcons = container.querySelectorAll('[data-testid="SyncIcon"]')
    const syncButtons = Array.from(syncIcons)
      .map((icon) => icon.closest('button'))
      .filter((btn): btn is HTMLButtonElement => btn !== null)

    // System entry sync should be disabled; our server's sync should be enabled
    const enabledButtons = syncButtons.filter(
      (btn) => !btn.hasAttribute('disabled') && btn.getAttribute('aria-disabled') !== 'true'
    )
    expect(enabledButtons.length).toBe(1)

    const disabledButtons = syncButtons.filter(
      (btn) => btn.hasAttribute('disabled') || btn.getAttribute('aria-disabled') === 'true'
    )
    // System entry sync is disabled = 1
    expect(disabledButtons.length).toBe(1)
  })
})

describe('McpHubPage — sync button state (Issue 2 reproduction)', () => {
  beforeEach(() => {
    mockSyncState.mutate = vi.fn()
    mockServers.length = 0
    mockServers.push(
      {
        id: '00000000-0000-0000-0000-000000000001',
        name: 'System',
        slug: 'system',
        base_url: 'http://mcp.system.local',
        status: 'active',
        description: '',
        session_count: 0,
      },
      {
        id: 'srv-1',
        name: 'Server One',
        slug: 'server-one',
        base_url: 'http://mcp.local/one',
        status: 'active',
        description: '',
        session_count: 1,
      },
      {
        id: 'srv-2',
        name: 'Server Two',
        slug: 'server-two',
        base_url: 'http://mcp.local/two',
        status: 'active',
        description: '',
        session_count: 2,
      }
    )
  })

  it('FAILING: when srv-1 is syncing, only srv-1 sync button should be disabled (not srv-2)', async () => {
    // Simulate: srv-1 sync is in-flight
    mockSyncState.isPending = true
    mockSyncState.variables = 'srv-1'

    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    const { container } = render(<McpHubPage />, { wrapper })

    // Find sync icons — there are 3 rows: System (disabled), srv-1, srv-2
    const syncIcons = container.querySelectorAll('[data-testid="SyncIcon"]')
    const syncButtons = Array.from(syncIcons)
      .map((icon) => icon.closest('button'))
      .filter((btn): btn is HTMLButtonElement => btn !== null)

    // System entry + 2 servers = 3 sync icons
    expect(syncButtons.length).toBe(3)

    const disabledSyncButtons = syncButtons.filter(
      (btn) => btn.hasAttribute('disabled') || btn.getAttribute('aria-disabled') === 'true'
    )

    // System entry sync is always disabled + srv-1 should be disabled (isPending+vars match) = 2
    // BUG: current code has disabled={syncServer.isPending}
    //      → all 3 buttons disabled when isPending=true
    // EXPECTED: after fix, disabled={syncServer.isPending && syncServer.variables === server.id}
    //           → System (always disabled) + srv-1 = 2 disabled
    expect(disabledSyncButtons.length).toBe(2)
  })

  it('FAILING: when srv-2 is syncing, only srv-2 sync button should be disabled (not srv-1)', async () => {
    // Simulate: srv-2 sync is in-flight
    mockSyncState.isPending = true
    mockSyncState.variables = 'srv-2'

    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    const { container } = render(<McpHubPage />, { wrapper })

    const syncIcons = container.querySelectorAll('[data-testid="SyncIcon"]')
    const syncButtons = Array.from(syncIcons)
      .map((icon) => icon.closest('button'))
      .filter((btn): btn is HTMLButtonElement => btn !== null)

    expect(syncButtons.length).toBe(3)

    const disabledSyncButtons = syncButtons.filter(
      (btn) => btn.hasAttribute('disabled') || btn.getAttribute('aria-disabled') === 'true'
    )

    // System (always disabled) + srv-2 = 2 disabled
    expect(disabledSyncButtons.length).toBe(2)
  })

  it('when no sync is in-flight, only System entry sync is disabled', async () => {
    mockSyncState.isPending = false
    mockSyncState.variables = undefined

    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    const { container } = render(<McpHubPage />, { wrapper })

    const syncIcons = container.querySelectorAll('[data-testid="SyncIcon"]')
    const syncButtons = Array.from(syncIcons)
      .map((icon) => icon.closest('button'))
      .filter((btn): btn is HTMLButtonElement => btn !== null)

    expect(syncButtons.length).toBe(3)

    const disabledSyncButtons = syncButtons.filter((btn) => btn.hasAttribute('disabled'))
    // Only System entry should be disabled
    expect(disabledSyncButtons.length).toBe(1)
  })
})

/**
 * FIX-20261101-014511 — Control Center (cc) entity gating.
 *
 * The per-tenant Control Center MCP entity is a protected integration:
 * the backend only returns it in the list for callers granted
 * `integration::control_center:read`, and mutations without `manage`
 * yield structured 403s. The page must render the cc row (with a
 * "protected" chip) when present, and surface mutation 403s via the
 * standard PermissionDeniedAlert — never a silent failure or raw crash.
 */
describe('McpHubPage — Control Center entity gating', () => {
  beforeEach(() => {
    mockSyncState.isPending = false
    mockSyncState.mutate = vi.fn()
    mockServers.length = 0
    mockServers.push(
      {
        id: 'cc-server-id',
        name: 'Control Center',
        slug: 'cc',
        base_url: '',
        status: 'active',
        description: 'Control Center management capabilities',
        session_count: 0,
      },
      {
        id: 'srv-1',
        name: 'Server One',
        slug: 'server-one',
        base_url: 'http://mcp.local/one',
        status: 'active',
        description: '',
        session_count: 1,
      }
    )
  })

  it('renders the cc entity with the protected-integration chip when returned', async () => {
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })
    expect(screen.getByText('cc')).toBeDefined()
    expect(screen.getByText('mcp.controlCenter.chip')).toBeDefined()
  })

  it('renders no cc row when the (permission-filtered) list omits it', async () => {
    mockServers.length = 0
    mockServers.push({
      id: 'srv-1',
      name: 'Server One',
      slug: 'server-one',
      base_url: 'http://mcp.local/one',
      status: 'active',
      description: '',
      session_count: 1,
    })
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })
    expect(screen.queryByText('mcp.controlCenter.chip')).toBeNull()
    expect(screen.getByText('server-one')).toBeDefined()
  })

  it('cc entity shows System-managed chip with edit/delete/sync/sessions hidden (slug fallback)', async () => {
    // Mock data has no is_system_managed flag — the slug fallback must lock the row.
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    const { container } = render(<McpHubPage />, { wrapper })

    expect(screen.getByText('mcp.controlCenter.systemManaged')).toBeDefined()

    const row = screen.getByText('cc').closest('tr') as HTMLTableRowElement
    // No sessions (Storage), edit (Edit), or delete (Delete) actions on the cc row
    expect(row.querySelector('[data-testid="StorageIcon"]')).toBeNull()
    expect(row.querySelector('[data-testid="EditIcon"]')).toBeNull()
    expect(row.querySelector('[data-testid="DeleteIcon"]')).toBeNull()
    // Sync is present but disabled
    const syncBtn = row.querySelector('[data-testid="SyncIcon"]')?.closest('button')
    expect(syncBtn).not.toBeNull()
    expect(syncBtn?.hasAttribute('disabled')).toBe(true)
    // Session count column shows the em dash
    expect(row.textContent).toContain('—')
    expect(container).toBeDefined()
  })

  it('cc entity honours the API is_system_managed flag', async () => {
    mockServers.length = 0
    mockServers.push({
      id: 'cc-flagged',
      name: 'Control Center',
      slug: 'cc',
      base_url: '',
      status: 'active',
      description: 'Control Center management capabilities',
      session_count: 0,
      is_system_managed: true,
    })
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })
    expect(screen.getByText('mcp.controlCenter.systemManaged')).toBeDefined()
    const row = screen.getByText('cc').closest('tr') as HTMLTableRowElement
    expect(row.querySelector('[data-testid="DeleteIcon"]')).toBeNull()
    expect(row.querySelector('[data-testid="StorageIcon"]')).toBeNull()
  })

  it('surfaces a structured 403 from a server deletion via PermissionDeniedAlert', async () => {
    window.confirm = vi.fn(() => true)
    const apiClient = (await import('../api/apiClient')).default as unknown as { delete: ReturnType<typeof vi.fn> }
    apiClient.delete.mockRejectedValueOnce({
      response: {
        status: 403,
        data: {
          detail: {
            detail: 'manage required',
            required_permission: {
              resource_type: 'integration::control_center',
              action: 'manage',
              resource_id: null,
            },
          },
        },
      },
    })
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })
    // The cc row has NO delete action — the 403 path is exercised via the
    // regular server row (PermissionDeniedAlert surfacing is row-agnostic).
    const deleteButtons = screen.getAllByTestId('DeleteIcon')
    expect(deleteButtons.length).toBe(1)
    fireEvent.click(deleteButtons[0])
    expect(await screen.findByText('Permission Denied:')).toBeDefined()
  })
})
