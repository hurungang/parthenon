import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import type { AgentRole } from '../types'

// ── Module mocks ──────────────────────────────────────────────────────────────

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => vi.fn() }
})

// Mock AgentRoleDialog so opening edit mode doesn't require complex setup
vi.mock('../pages/agents/AgentRoleDialog', () => ({
  AgentRoleDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="role-edit-dialog">edit-role-form</div> : null,
}))

vi.mock('../components/permissions/PermissionDeniedAlert', () => ({
  default: ({ fallbackMessage }: { error: unknown; fallbackMessage?: string }) => (
    <div data-testid="permission-denied-alert">{fallbackMessage ?? 'error'}</div>
  ),
}))

// ── Mutable API mock state ────────────────────────────────────────────────────

let mockGetResult: { data: AgentRole | null } = { data: null }
let mockGetError: Error | null = null

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn(() =>
      mockGetError
        ? Promise.reject(mockGetError)
        : Promise.resolve(mockGetResult),
    ),
  },
}))

// ── Test fixtures ──────────────────────────────────────────────────────────────

const MOCK_ROLE: AgentRole = {
  id: 'role-1',
  name: 'Research Role',
  description: 'Role for research tasks',
  sop_ids: ['sop-1'],
  skill_ids: ['skill-1', 'skill-2'],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

// ── Wrapper ────────────────────────────────────────────────────────────────────

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('AgentRoleViewDialog', () => {
  beforeEach(() => {
    mockGetResult = { data: null }
    mockGetError = null
    vi.resetAllMocks()
  })

  it('shows loading spinner while role is fetching', async () => {
    // Delay resolution so loading state is visible
    const apiMock = await import('../api/apiClient')
    vi.mocked(apiMock.default.get).mockReturnValue(new Promise(() => {}))

    const { AgentRoleViewDialog } = await import('../components/agents/AgentRoleViewDialog')
    render(<AgentRoleViewDialog open roleId="role-1" onClose={vi.fn()} />, { wrapper })

    expect(screen.getByRole('progressbar')).toBeDefined()
  })

  it('renders role name and description when loaded', async () => {
    const apiMock = await import('../api/apiClient')
    vi.mocked(apiMock.default.get).mockResolvedValue({ data: MOCK_ROLE })

    const { AgentRoleViewDialog } = await import('../components/agents/AgentRoleViewDialog')
    render(<AgentRoleViewDialog open roleId="role-1" onClose={vi.fn()} />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('Research Role')).toBeDefined()
    })
    expect(screen.getByText('Role for research tasks')).toBeDefined()
  })

  it('renders SOP count chip when sop_ids are populated', async () => {
    const apiMock = await import('../api/apiClient')
    vi.mocked(apiMock.default.get).mockResolvedValue({ data: MOCK_ROLE })

    const { AgentRoleViewDialog } = await import('../components/agents/AgentRoleViewDialog')
    render(<AgentRoleViewDialog open roleId="role-1" onClose={vi.fn()} />, { wrapper })

    await waitFor(() => {
      // sopCount chip: 'agents.roles.sopCount' key rendered with count
      expect(screen.getByText(/agents\.roles\.sopCount/)).toBeDefined()
    })
  })

  it('renders Edit button enabled when role is loaded', async () => {
    const apiMock = await import('../api/apiClient')
    vi.mocked(apiMock.default.get).mockResolvedValue({ data: MOCK_ROLE })

    const { AgentRoleViewDialog } = await import('../components/agents/AgentRoleViewDialog')
    render(<AgentRoleViewDialog open roleId="role-1" onClose={vi.fn()} />, { wrapper })

    await waitFor(() => {
      const editBtn = screen.getByRole('button', { name: 'app.edit' })
      expect(editBtn).toBeDefined()
      expect((editBtn as HTMLButtonElement).disabled).toBe(false)
    })
  })

  it('Edit button is disabled before role data loads', async () => {
    const apiMock = await import('../api/apiClient')
    vi.mocked(apiMock.default.get).mockReturnValue(new Promise(() => {}))

    const { AgentRoleViewDialog } = await import('../components/agents/AgentRoleViewDialog')
    render(<AgentRoleViewDialog open roleId="role-1" onClose={vi.fn()} />, { wrapper })

    const editBtn = screen.getByRole('button', { name: 'app.edit' })
    expect((editBtn as HTMLButtonElement).disabled).toBe(true)
  })

  it('clicking Edit opens AgentRoleDialog in edit mode', async () => {
    const apiMock = await import('../api/apiClient')
    vi.mocked(apiMock.default.get).mockResolvedValue({ data: MOCK_ROLE })

    const { AgentRoleViewDialog } = await import('../components/agents/AgentRoleViewDialog')
    render(<AgentRoleViewDialog open roleId="role-1" onClose={vi.fn()} />, { wrapper })

    // Wait for role to load and Edit button to be enabled
    await waitFor(() => {
      const btn = screen.getByRole('button', { name: 'app.edit' })
      expect((btn as HTMLButtonElement).disabled).toBe(false)
    })

    const editBtn = screen.getByRole('button', { name: 'app.edit' })
    await act(async () => {
      fireEvent.click(editBtn)
    })

    await waitFor(() => {
      expect(screen.getByTestId('role-edit-dialog')).toBeDefined()
    })
  })

  it('Close button calls onClose', async () => {
    const apiMock = await import('../api/apiClient')
    vi.mocked(apiMock.default.get).mockResolvedValue({ data: MOCK_ROLE })
    const onClose = vi.fn()

    const { AgentRoleViewDialog } = await import('../components/agents/AgentRoleViewDialog')
    render(<AgentRoleViewDialog open roleId="role-1" onClose={onClose} />, { wrapper })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'app.close' })).toBeDefined()
    })

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'app.close' }))
    })

    expect(onClose).toHaveBeenCalledOnce()
  })

  it('shows PermissionDeniedAlert when role fetch fails', async () => {
    const apiMock = await import('../api/apiClient')
    vi.mocked(apiMock.default.get).mockRejectedValue(new Error('Forbidden'))

    const { AgentRoleViewDialog } = await import('../components/agents/AgentRoleViewDialog')
    render(<AgentRoleViewDialog open roleId="role-1" onClose={vi.fn()} />, { wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('permission-denied-alert')).toBeDefined()
    })
  })

  it('does not fetch when roleId is null', async () => {
    const apiMock = await import('../api/apiClient')
    const getSpy = vi.mocked(apiMock.default.get)

    const { AgentRoleViewDialog } = await import('../components/agents/AgentRoleViewDialog')
    render(<AgentRoleViewDialog open roleId={null} onClose={vi.fn()} />, { wrapper })

    // get should not be called when roleId is null (query disabled)
    expect(getSpy).not.toHaveBeenCalled()
  })
})
