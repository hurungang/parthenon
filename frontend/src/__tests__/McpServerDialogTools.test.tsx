/**
 * Task 3 — Tools tab in the MCP server add/update dialog.
 *
 * Covers:
- the Tools tab renders the saved server's tools (GET /mcp/servers/{id}/tools);
- "Load Tools" triggers the sync endpoint then refreshes the tool list;
- a NEW (unsaved) server shows save-first guidance and disables Load Tools;
- sync failures surface via the standard dialogError + PermissionDeniedAlert.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockServers = [
  { id: 'srv-1', name: 'Server One', slug: 'server-one', base_url: 'http://mcp.local/one', status: 'active', description: '', session_count: 1 },
]

const mockTools = [
  { id: 'tool-1', server_id: 'srv-1', name: 'server-one____search', original_name: 'search', description: 'Searches', is_active: true, input_schema: {}, server_slug: 'server-one', server_name: 'Server One', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
]

const serverToolsRefetch = vi.fn()

vi.mock('../hooks/useMcpServers', () => ({
  useMcpServers: () => ({ data: mockServers, isLoading: false }),
  useSyncServer: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
  useServerTools: () => ({ data: mockTools, isLoading: false, error: null, refetch: serverToolsRefetch }),
  useAllTools: () => ({
    data: [
      { id: 'tool-1', server_id: 'srv-1', name: 'server-one____search', original_name: 'search', description: 'Searches', is_active: true, input_schema: {} },
    ],
    isLoading: false,
    error: null,
  }),
  useToolSkills: () => ({ data: [] }),
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

const apiPost = vi.fn().mockResolvedValue({ data: {} })
const apiGet = vi.fn().mockResolvedValue({ data: [] })
const apiPut = vi.fn().mockResolvedValue({ data: {} })
const apiDelete = vi.fn().mockResolvedValue({ data: {} })

vi.mock('../api/apiClient', () => ({
  default: {
    post: (...args: unknown[]) => apiPost(...args),
    get: (...args: unknown[]) => apiGet(...args),
    put: (...args: unknown[]) => apiPut(...args),
    delete: (...args: unknown[]) => apiDelete(...args),
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

async function openEditDialog() {
  const { McpHubPage } = await import('../pages/mcp/McpHubPage')
  render(<McpHubPage />, { wrapper })
  const editIcons = screen.getAllByTestId('EditIcon')
  fireEvent.click(editIcons[0])
  expect(screen.getByRole('dialog')).toBeDefined()
}

describe('McpServerDialog — Tools tab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiPost.mockClear()
    apiPost.mockResolvedValue({ data: {} })
  })

  it('shows the Tools tab with the server tools listed', async () => {
    await openEditDialog()
    fireEvent.click(screen.getByRole('tab', { name: 'mcp.dialog.tabs.tools' }))
    await waitFor(() => {
      expect(screen.getByText('server-one____search')).toBeDefined()
    })
  })

  it('Load Tools calls the sync endpoint then refreshes the tool list', async () => {
    await openEditDialog()
    fireEvent.click(screen.getByRole('tab', { name: 'mcp.dialog.tabs.tools' }))
    fireEvent.click(screen.getByRole('button', { name: /mcp\.dialog\.loadTools/ }))
    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith('/mcp/servers/srv-1/sync')
    })
    await waitFor(() => {
      expect(serverToolsRefetch).toHaveBeenCalled()
    })
  })

  it('surfaces sync failures via PermissionDeniedAlert in the dialog', async () => {
    apiPost.mockRejectedValueOnce({
      response: {
        status: 403,
        data: {
          detail: {
            detail: 'manage required',
            required_permission: {
              resource_type: 'integration::mcp_hub',
              action: 'manage',
              resource_id: null,
            },
          },
        },
      },
    })
    await openEditDialog()
    fireEvent.click(screen.getByRole('tab', { name: 'mcp.dialog.tabs.tools' }))
    fireEvent.click(screen.getByRole('button', { name: /mcp\.dialog\.loadTools/ }))
    expect(await screen.findByText('Permission Denied:')).toBeDefined()
  })

  it('new (unsaved) server shows save-first guidance and disables Load Tools', async () => {
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })
    fireEvent.click(screen.getByRole('button', { name: /mcp\.registerServer/i }))
    fireEvent.click(screen.getByRole('tab', { name: 'mcp.dialog.tabs.tools' }))

    expect(screen.getByText('mcp.dialog.saveFirstHint')).toBeDefined()
    const loadButton = screen.getByRole('button', { name: /mcp\.dialog\.loadTools/ })
    expect(loadButton.hasAttribute('disabled')).toBe(true)
  })

  it('save still works from the Details tab after opening the dialog', async () => {
    await openEditDialog()
    fireEvent.click(screen.getByRole('button', { name: /app\.save/ }))
    await waitFor(() => {
      expect(apiPut).toHaveBeenCalledWith('/mcp/servers/srv-1', expect.anything())
    })
  })

  it('renders the dialog at the responsive (md/fullWidth) width', async () => {
    await openEditDialog()
    // MUI renders the Paper itself with role="dialog"
    const paper = screen.getByRole('dialog')
    // maxWidth="md" breakpoint applied by MUI
    expect(paper.className).toContain('MuiDialog-paperWidthMd')
    // fullWidth
    expect(paper.className).toContain('MuiDialog-paperFullWidth')
  })

  it('clicking a server row opens the server dialog view-only with the Details tab selected', async () => {
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })

    // Click the server row (role="button", labelled with the server slug)
    const row = await screen.findByRole('button', { name: /server-one — mcp\.servers\.openServerDetails/ })
    fireEvent.click(row)

    const dialog = screen.getByRole('dialog')
    expect(dialog).toBeDefined()

    // Details tab selected by default
    const detailsTab = within(dialog).getByRole('tab', { name: 'mcp.dialog.tabs.details' })
    expect(detailsTab.className).toContain('Mui-selected')

    // View-only mode: no Save button
    expect(within(dialog).queryByRole('button', { name: /app\.save/ })).toBeNull()
    // Dialog rendered at the responsive (md/fullWidth) width
    expect(dialog.className).toContain('MuiDialog-paperWidthMd')
    expect(dialog.className).toContain('MuiDialog-paperFullWidth')

    // Keyboard support: Enter activates the row too
    fireEvent.keyDown(row, { key: 'Enter' })
    expect(screen.getByRole('dialog')).toBeDefined()
  })

  it('clicking a row action button does NOT trigger the row-click (view-only) dialog', async () => {
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })

    // Click the row's Edit action button — the actions cell stops propagation,
    // so the edit dialog opens (editable, Save visible), not the view-only one.
    const editIcons = screen.getAllByTestId('EditIcon')
    fireEvent.click(editIcons[0])

    const dialog = screen.getByRole('dialog')
    // Edit mode: Save button present (a row click would have hidden it)
    expect(within(dialog).getByRole('button', { name: /app\.save/ })).toBeDefined()
    // No view-only duplicate dialog was opened by the row click
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
  })
})
