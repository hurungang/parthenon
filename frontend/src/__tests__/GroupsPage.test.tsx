import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockGroups = [
  { id: '1', name: 'dev-team', description: 'Dev team group', owner_id: null, owner_display_name: null, idp_claim_value: 'dev-group', member_count: 3, role_count: 1, created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
]

vi.mock('../hooks/usePermissions', () => ({
  useGroups: () => ({ data: mockGroups, isLoading: false }),
  useCreateGroup: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateGroup: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteGroup: () => ({ mutate: vi.fn(), isPending: false }),
  useGroupMembers: () => ({ data: [], isLoading: false }),
  useGroupRoles: () => ({ data: [], isLoading: false, error: null }),
  useAssignGroupRole: () => ({ mutate: vi.fn(), isPending: false }),
  useRemoveGroupRole: () => ({ mutate: vi.fn(), isPending: false }),
  useRoles: () => ({ data: [], isLoading: false }),
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('GroupsPage', () => {
  it('renders groups table when data is loaded', async () => {
    const { GroupsPage } = await import('../pages/permissions/GroupsPage')
    render(<GroupsPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('dev-team')).toBeDefined()
    })
  })

  it('renders Add Group button', async () => {
    const { GroupsPage } = await import('../pages/permissions/GroupsPage')
    render(<GroupsPage />, { wrapper })
    expect(screen.getAllByRole('button').length).toBeGreaterThan(0)
  })
})
