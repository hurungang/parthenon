import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockRoles = [
  { id: '1', name: 'admin-role', description: 'Admin role', is_active: true, policy_count: 2, user_assignment_count: 1, group_assignment_count: 0, created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
]

vi.mock('../hooks/usePermissions', () => ({
  useRoles: () => ({ data: mockRoles, isLoading: false }),
  useCreateRole: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateRole: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteRole: () => ({ mutate: vi.fn(), isPending: false }),
  useRole: () => ({ data: null, isLoading: false }),
  useCreatePolicyStatement: () => ({ mutate: vi.fn(), isPending: false }),
  useDeletePolicyStatement: () => ({ mutate: vi.fn(), isPending: false }),
  useTagDefinitions: () => ({ data: [], isLoading: false }),
}))

vi.mock('../hooks/useTagValueOptions', () => ({
  useTagValueOptions: () => [],
}))

vi.mock('../api/permissionsApi', () => ({
  listRolePolicies: vi.fn().mockResolvedValue([]),
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('RolesPage', () => {
  it('renders roles table when data is loaded', async () => {
    const { RolesPage } = await import('../pages/permissions/RolesPage')
    render(<RolesPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('admin-role')).toBeDefined()
    })
  })

  it('renders Add Role button', async () => {
    const { RolesPage } = await import('../pages/permissions/RolesPage')
    render(<RolesPage />, { wrapper })
    expect(screen.getAllByRole('button').length).toBeGreaterThan(0)
  })
})
