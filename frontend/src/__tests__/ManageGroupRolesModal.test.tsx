import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockState = {
  groupRoles: { data: [] as { id: string; name: string }[], isLoading: false, error: null as unknown },
  allRoles: [{ id: 'role-1', name: 'viewer' }, { id: 'role-2', name: 'editor' }],
  assign: {
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    isPending: false,
    isError: false,
    error: null as unknown,
  },
  remove: {
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    isPending: false,
    isError: false,
    error: null as unknown,
  },
}

vi.mock('../hooks/usePermissions', () => ({
  useGroupRoles: () => mockState.groupRoles,
  useRoles: () => ({ data: mockState.allRoles }),
  useAssignGroupRole: () => mockState.assign,
  useRemoveGroupRole: () => mockState.remove,
}))

const mockGroup = {
  id: 'group-1',
  name: 'ops-team',
  description: '',
  owner_id: undefined,
  owner_display_name: undefined,
  idp_claim_value: undefined,
  member_count: 2,
  role_count: 0,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  mockState.groupRoles = { data: [], isLoading: false, error: null }
  mockState.allRoles = [{ id: 'role-1', name: 'viewer' }, { id: 'role-2', name: 'editor' }]
  mockState.assign = {
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    isPending: false,
    isError: false,
    error: null,
  }
  mockState.remove = {
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    isPending: false,
    isError: false,
    error: null,
  }
})

describe('ManageGroupRolesModal', () => {
  it('renders the dialog when open=true', async () => {
    const { ManageGroupRolesModal } = await import('../components/permissions/ManageGroupRolesModal')
    render(<ManageGroupRolesModal open={true} onClose={vi.fn()} group={mockGroup} />, { wrapper })
    await waitFor(() => { expect(screen.getByRole('dialog')).toBeDefined() })
  })

  it('does not render visible dialog when open=false', async () => {
    const { ManageGroupRolesModal } = await import('../components/permissions/ManageGroupRolesModal')
    render(<ManageGroupRolesModal open={false} onClose={vi.fn()} group={mockGroup} />, { wrapper })
    const dialogs = screen.queryAllByRole('dialog')
    const openDialog = dialogs.find((d) => d.getAttribute('aria-hidden') !== 'true')
    expect(openDialog).toBeUndefined()
  })

  it('shows "no roles assigned" message when assigned roles list is empty', async () => {
    mockState.groupRoles = { data: [], isLoading: false, error: null }
    const { ManageGroupRolesModal } = await import('../components/permissions/ManageGroupRolesModal')
    render(<ManageGroupRolesModal open={true} onClose={vi.fn()} group={mockGroup} />, { wrapper })
    await waitFor(() => { expect(screen.getByText('permissions.groups.noRolesAssigned')).toBeDefined() })
  })

  it('renders assigned role chips when roles are present', async () => {
    mockState.groupRoles = { data: [{ id: 'role-1', name: 'viewer' }], isLoading: false, error: null }
    const { ManageGroupRolesModal } = await import('../components/permissions/ManageGroupRolesModal')
    render(<ManageGroupRolesModal open={true} onClose={vi.fn()} group={mockGroup} />, { wrapper })
    await waitFor(() => { expect(screen.getByText('viewer')).toBeDefined() })
  })

  it('shows loading placeholder when roles are loading', async () => {
    mockState.groupRoles = { data: undefined as unknown as [], isLoading: true, error: null }
    const { ManageGroupRolesModal } = await import('../components/permissions/ManageGroupRolesModal')
    render(<ManageGroupRolesModal open={true} onClose={vi.fn()} group={mockGroup} />, { wrapper })
    await waitFor(() => { expect(screen.getByRole('dialog')).toBeDefined() })
  })

  it('displays actual API error detail when role load fails', async () => {
    const apiError = {
      response: { data: { detail: 'Not authorized to view roles for this group.' } },
      message: 'Request failed with status code 403',
    }
    mockState.groupRoles = { data: undefined as unknown as [], isLoading: false, error: apiError }
    const { ManageGroupRolesModal } = await import('../components/permissions/ManageGroupRolesModal')
    render(<ManageGroupRolesModal open={true} onClose={vi.fn()} group={mockGroup} />, { wrapper })
    await waitFor(() => {
      const alerts = screen.getAllByRole('alert')
      expect(alerts.some((a) => a.textContent?.includes('Not authorized to view roles for this group.'))).toBe(true)
    })
  })

  it('displays actual API error when role assignment fails', async () => {
    const assignError = {
      response: { data: { detail: "Role 'viewer' already assigned to group 'ops-team'." } },
      message: 'Request failed with status code 409',
    }
    mockState.assign = { mutateAsync: vi.fn().mockRejectedValue(assignError), isPending: false, isError: true, error: assignError }
    const { ManageGroupRolesModal } = await import('../components/permissions/ManageGroupRolesModal')
    render(<ManageGroupRolesModal open={true} onClose={vi.fn()} group={mockGroup} />, { wrapper })
    await waitFor(() => {
      const alerts = screen.getAllByRole('alert')
      expect(alerts.some((a) => a.textContent?.includes("Role 'viewer' already assigned to group 'ops-team'."))).toBe(true)
    })
  })

  it('displays actual API error when role removal fails', async () => {
    const removeError = {
      response: { data: { detail: 'Role assignment not found.' } },
      message: 'Request failed with status code 404',
    }
    mockState.remove = { mutateAsync: vi.fn().mockRejectedValue(removeError), isPending: false, isError: true, error: removeError }
    const { ManageGroupRolesModal } = await import('../components/permissions/ManageGroupRolesModal')
    render(<ManageGroupRolesModal open={true} onClose={vi.fn()} group={mockGroup} />, { wrapper })
    await waitFor(() => {
      const alerts = screen.getAllByRole('alert')
      expect(alerts.some((a) => a.textContent?.includes('Role assignment not found.'))).toBe(true)
    })
  })

  it('close button calls onClose handler', async () => {
    const handleClose = vi.fn()
    const { ManageGroupRolesModal } = await import('../components/permissions/ManageGroupRolesModal')
    render(<ManageGroupRolesModal open={true} onClose={handleClose} group={mockGroup} />, { wrapper })
    await waitFor(() => { expect(screen.getByRole('dialog')).toBeDefined() })
    const closeBtn = screen.getByRole('button', { name: 'app.close' })
    fireEvent.click(closeBtn)
    expect(handleClose).toHaveBeenCalledOnce()
  })

  it('Add Role button is disabled when no role is selected', async () => {
    const { ManageGroupRolesModal } = await import('../components/permissions/ManageGroupRolesModal')
    render(<ManageGroupRolesModal open={true} onClose={vi.fn()} group={mockGroup} />, { wrapper })
    await waitFor(() => { expect(screen.getByRole('dialog')).toBeDefined() })
    const addBtn = screen.getByRole('button', { name: 'permissions.groups.addRole' })
    expect(addBtn).toBeDefined()
    expect((addBtn as HTMLButtonElement).disabled).toBe(true)
  })
})