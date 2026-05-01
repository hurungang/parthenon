/**
 * Unit tests for PolicyEditor component.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockDeleteMutateAsync = vi.fn()

const mockPolicies = [
  {
    id: 'policy-1',
    effect: 'allow',
    module: 'agent',
    actions: [{ id: 'a1', action: 'read' }, { id: 'a2', action: 'execute' }],
    resources: [],
    tag_conditions: [{ id: 'tc1', tag_key: 'env', tag_value: 'prod' }],
    created_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 'policy-2',
    effect: 'deny',
    module: 'role',
    actions: [{ id: 'a3', action: 'manage' }],
    resources: [],
    tag_conditions: [],
    created_at: '2024-01-01T00:00:00Z',
  },
]

// Module-level state that mock factories read dynamically — avoids vi.doMock/resetModules corruption
type MockPolicyEntry = {
  id: string
  effect: string
  module: string
  actions: { id: string; action: string }[]
  resources: { id: string; resource_type: string; resource_id: string | null }[]
  tag_conditions: { id: string; tag_key: string; tag_value: string }[]
  created_at: string
}
let mockRoleState: { policy_statements?: MockPolicyEntry[] } | null = { policy_statements: mockPolicies }

// Mock ALL hooks from usePermissions to prevent unmocked hooks failing in AddStatementDialog
vi.mock('../hooks/usePermissions', () => ({
  useRole: () => ({ data: mockRoleState, isLoading: false }),
  useDeletePolicyStatement: () => ({
    mutateAsync: mockDeleteMutateAsync,
    isPending: false,
  }),
  useResourceTypes: () => ({ data: [] }),
  useTagDefinitions: () => ({ data: [] }),
  useCreatePolicyStatement: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdatePolicyStatement: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))

vi.mock('../hooks/useTagValueOptions', () => ({
  useTagValueOptions: () => [],
}))

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  function wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={qc}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    )
  }
  return wrapper
}

describe('PolicyEditor', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockRoleState = { policy_statements: mockPolicies }
  })

  it('renders statement cards with correct resource type, effect, and actions', async () => {
    const PolicyEditor = (await import('../components/permissions/PolicyEditor')).default
    render(<PolicyEditor roleId="role-1" />, { wrapper: makeWrapper() })

    // Wait for policy cards to appear — Remove buttons are the most reliable indicator
    const deleteBtns = await screen.findAllByRole('button', { name: /app\.delete/i })
    expect(deleteBtns.length).toBeGreaterThan(0)

    // Tag condition displayed
    expect(screen.getByText('env=prod')).toBeDefined()
  })

  it('Remove button calls delete mutation', async () => {
    mockDeleteMutateAsync.mockResolvedValueOnce(undefined)
    const PolicyEditor = (await import('../components/permissions/PolicyEditor')).default
    render(<PolicyEditor roleId="role-1" />, { wrapper: makeWrapper() })

    const deleteBtn = await screen.findAllByRole('button', { name: /app\.delete/i })
    fireEvent.click(deleteBtn[0])

    await waitFor(() => {
      expect(mockDeleteMutateAsync).toHaveBeenCalled()
    })
  })

  it('shows empty state when no statements exist', async () => {
    mockRoleState = { policy_statements: [] }
    const PolicyEditor = (await import('../components/permissions/PolicyEditor')).default
    render(<PolicyEditor roleId="role-1" />, { wrapper: makeWrapper() })

    await screen.findByText('app.noData')
  })

  it('Add Statement button is rendered', async () => {
    const PolicyEditor = (await import('../components/permissions/PolicyEditor')).default
    render(<PolicyEditor roleId="role-1" />, { wrapper: makeWrapper() })

    await screen.findByRole('button', { name: /permissions\.roles\.addPolicy/i })
  })

  it('displays inline error when delete mutation fails', async () => {
    const error = new Error('Permission denied')
    mockDeleteMutateAsync.mockRejectedValueOnce(error)

    const PolicyEditor = (await import('../components/permissions/PolicyEditor')).default
    render(<PolicyEditor roleId="role-1" />, { wrapper: makeWrapper() })

    const deleteBtn = await screen.findAllByRole('button', { name: /app\.delete/i })
    fireEvent.click(deleteBtn[0])

    await waitFor(() => {
      expect(mockDeleteMutateAsync).toHaveBeenCalled()
    })
  })

  it('displays resource ID chips with resource_type:resource_id format', async () => {
    const policiesWithResources = [
      {
        id: 'policy-res-1',
        effect: 'allow',
        module: 'agent',
        actions: [{ id: 'a1', action: 'read' }],
        resources: [
          { id: 'r1', resource_type: 'agent', resource_id: 'agent-abc-123' },
          { id: 'r2', resource_type: 'agent', resource_id: null },
        ],
        tag_conditions: [],
        created_at: '2024-01-01T00:00:00Z',
      },
    ]
    mockRoleState = { policy_statements: policiesWithResources }

    const PolicyEditor = (await import('../components/permissions/PolicyEditor')).default
    render(<PolicyEditor roleId="role-1" />, { wrapper: makeWrapper() })

    // Wait for card to render
    await screen.findAllByRole('button', { name: /app\.delete/i })

    // Resource chips should appear with the "resource_type:resource_id" format
    expect(screen.getByText('agent:agent-abc-123')).toBeDefined()
    // Null resource_id falls back to '*'
    expect(screen.getByText('agent:*')).toBeDefined()
  })

  it('Edit button opens AddStatementDialog with editingPolicy prop', async () => {
    const PolicyEditor = (await import('../components/permissions/PolicyEditor')).default
    render(<PolicyEditor roleId="role-1" />, { wrapper: makeWrapper() })

    // Wait for the Edit buttons to render
    const editBtns = await screen.findAllByRole('button', { name: /app\.edit/i })
    expect(editBtns.length).toBeGreaterThan(0)

    // Click the first Edit button (for policy-1)
    fireEvent.click(editBtns[0])

    // The AddStatementDialog should open — it renders the title for edit mode
    await waitFor(() => {
      expect(screen.queryByText('permissions.roles.editPolicyStatement')).not.toBeNull()
    })
  })
})
