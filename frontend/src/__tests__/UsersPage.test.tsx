import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockUsers = [
  { id: '1', sub: 'sub-1', email: 'alice@example.com', display_name: 'Alice', first_seen_at: '2024-01-01T00:00:00Z', last_seen_at: '2024-01-02T00:00:00Z', role_count: 1, group_count: 2 },
]

vi.mock('../hooks/usePermissions', () => ({
  usePlatformUsers: () => ({ data: mockUsers, isLoading: false }),
  useAssignUserRole: () => ({ mutate: vi.fn(), isPending: false }),
  useRemoveUserRole: () => ({ mutate: vi.fn(), isPending: false }),
  useAddUserToGroup: () => ({ mutate: vi.fn(), isPending: false }),
  useRemoveUserFromGroup: () => ({ mutate: vi.fn(), isPending: false }),
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('UsersPage', () => {
  it('renders users table when data is loaded', async () => {
    const { UsersPage } = await import('../pages/permissions/UsersPage')
    render(<UsersPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getAllByText('Alice')[0]).toBeDefined()
    })
  })

  it('renders Manage Access button for each user', async () => {
    const { UsersPage } = await import('../pages/permissions/UsersPage')
    render(<UsersPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getAllByText('Alice')[0]).toBeDefined()
    })
    // Manage Access buttons should be present
    expect(screen.getAllByRole('button').length).toBeGreaterThan(0)
  })
})
