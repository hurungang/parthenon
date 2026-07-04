/**
 * Unit tests for RolePolicyDialog component.
 *
 * Covers:
 * - Form view renders existing policies as compact cards with structured text
 * - Edit button opens inline edit form for a specific policy
 * - Form/JSON view toggle with bidirectional sync
 * - Save validates JSON on-the-fly and calls batch endpoint
 * - Save button is always enabled (validation happens on save, not on a separate button)
 * - Add policy row opens inline edit for the new row
 * - Delete policy row removes from compact list
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'
import { PolicyEffect } from '../types/permissions'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

let mockRoleData: Record<string, unknown> | null = null
let mockRoleLoading = false
const mockBatchSaveMutateAsync = vi.fn()
let mockHasUnsavedChanges = false
const mockHandleCloseFn = vi.fn()

vi.mock('../hooks/usePermissions', () => ({
  useRole: () => ({ data: mockRoleData, isLoading: mockRoleLoading }),
  useBatchSaveRolePolicies: () => ({
    mutateAsync: mockBatchSaveMutateAsync,
    isPending: false,
  }),
  useUpdateRole: () => ({
    mutateAsync: vi.fn().mockResolvedValue({}),
    isPending: false,
  }),
}))

vi.mock('../hooks/useUnsavedChangesDialog', () => ({
  useUnsavedChangesDialog: () => {
    const [hasUnsavedChanges, setHasUnsavedChanges] = React.useState(mockHasUnsavedChanges)
    const markUnsaved = React.useCallback(() => setHasUnsavedChanges(true), [])
    const markSaved = React.useCallback(() => setHasUnsavedChanges(false), [])
    const handleClose = React.useCallback(
      (closeFn: () => void) => {
        mockHandleCloseFn()
        closeFn()
      },
      [],
    )
    return {
      hasUnsavedChanges,
      markUnsaved,
      markSaved,
      handleClose,
      ConfirmationDialog: () => null,
    }
  },
}))

vi.mock('../components/permissions/PermissionDeniedAlert', () => ({
  default: ({ error }: { error: unknown; fallbackMessage: string }) => {
    const msg = error instanceof Error ? error.message : String(error)
    return React.createElement('div', { 'data-testid': 'permission-denied-alert' }, msg)
  },
}))

vi.mock('../components/permissions/FreeSoloResourceTypeSelect', () => ({
  default: ({
    value,
    onChange,
    disabled,
  }: {
    value: string
    onChange: (val: string) => void
    disabled?: boolean
  }) =>
    React.createElement('input', {
      'data-testid': 'resource-type-select',
      value,
      disabled,
      onChange: (e: React.ChangeEvent<HTMLInputElement>) => onChange(e.target.value),
    }),
}))

vi.mock('../components/permissions/FreeSoloActionSelect', () => ({
  default: ({
    value,
    onChange,
    disabled,
  }: {
    value: string[]
    onChange: (val: string[]) => void
    disabled?: boolean
  }) =>
    React.createElement('div', {
      'data-testid': 'action-select',
      'data-value': JSON.stringify(value),
      'data-disabled': String(disabled),
    }),
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

function makeMockRole(policyStatements: unknown[] = []) {
  return {
    id: 'role-test-1',
    name: 'Test Role',
    description: 'Test role for dialog',
    is_active: true,
    is_system: false,
    role_type: 'user_defined',
    policy_count: policyStatements.length,
    user_assignment_count: 0,
    group_assignment_count: 0,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    policy_statements: policyStatements,
  }
}

function makePolicyStatement(
  id: string,
  module: string,
  actions: string[],
  effect = PolicyEffect.Allow,
) {
  return {
    id,
    effect,
    module,
    actions: actions.map((a) => ({ id: `a-${a}`, action: a })),
    resources: [],
    tag_conditions: [],
    created_at: '2024-01-01T00:00:00Z',
  }
}

describe('RolePolicyDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockRoleData = null
    mockRoleLoading = false
    mockHasUnsavedChanges = false
    mockHandleCloseFn.mockClear()
    mockBatchSaveMutateAsync.mockReset()
  })

  it('renders compact policy cards with module name when role has policies', async () => {
    const policies = [
      makePolicyStatement('p1', 'agent::roles', ['read', 'manage']),
      makePolicyStatement('p2', 'system::permissions', ['create'], PolicyEffect.Deny),
    ]
    mockRoleData = makeMockRole(policies)

    const { default: RolePolicyDialog } = await import(
      '../components/permissions/RolePolicyDialog'
    )
    render(
      <RolePolicyDialog
        open={true}
        roleId="role-test-1"
        roleName="Test Role"
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
      { wrapper: makeWrapper() },
    )

    await waitFor(() => {
      expect(screen.getByText('agent::roles')).toBeDefined()
      expect(screen.getByText('system::permissions')).toBeDefined()
    })
  })

  it('shows inline edit form when Edit button is clicked on a compact card', async () => {
    const policies = [
      makePolicyStatement('p1', 'agent::roles', ['read']),
    ]
    mockRoleData = makeMockRole(policies)

    const { default: RolePolicyDialog } = await import(
      '../components/permissions/RolePolicyDialog'
    )
    render(
      <RolePolicyDialog
        open={true}
        roleId="role-test-1"
        roleName="Test Role"
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
      { wrapper: makeWrapper() },
    )

    await waitFor(() => {
      expect(screen.getByText('agent::roles')).toBeDefined()
    })

    // Initially, no edit form (no resource-type-select)
    expect(screen.queryByTestId('resource-type-select')).toBeNull()

    // Click the edit button (EditIcon button near the policy card)
    const editButtons = screen.getAllByTestId('EditIcon')
    fireEvent.click(editButtons[0])

    // Now the edit form should show
    await waitFor(() => {
      const inputs = screen.queryAllByTestId('resource-type-select')
      expect(inputs.length).toBe(1)
      expect((inputs[0] as HTMLInputElement).value).toBe('agent::roles')
    })
  })

  it('shows "Add Policy" button when role has no existing policies', async () => {
    mockRoleData = makeMockRole([])

    const { default: RolePolicyDialog } = await import(
      '../components/permissions/RolePolicyDialog'
    )
    render(
      <RolePolicyDialog
        open={true}
        roleId="role-test-1"
        roleName="Empty Role"
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
      { wrapper: makeWrapper() },
    )

    await waitFor(() => {
      expect(screen.getByText('permissions.roles.noPolicies')).toBeDefined()
    })

    const addBtn = screen.getByRole('button', { name: /permissions\.roles\.addPolicyRow/i })
    expect(addBtn).toBeDefined()
  })

  it('Add Policy button opens new row in edit mode', async () => {
    mockRoleData = makeMockRole([])

    const { default: RolePolicyDialog } = await import(
      '../components/permissions/RolePolicyDialog'
    )
    render(
      <RolePolicyDialog
        open={true}
        roleId="role-test-1"
        roleName="Test Role"
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
      { wrapper: makeWrapper() },
    )

    await waitFor(() => {
      expect(screen.getByText('permissions.roles.noPolicies')).toBeDefined()
    })

    fireEvent.click(screen.getByRole('button', { name: /permissions\.roles\.addPolicyRow/i }))

    // New row should open in edit mode (resource-type-select visible)
    await waitFor(() => {
      const inputs = screen.queryAllByTestId('resource-type-select')
      expect(inputs.length).toBe(1)
    })
  })

  it('deletes a policy by clicking delete on compact card', async () => {
    const policies = [
      makePolicyStatement('p1', 'agent::roles', ['read']),
    ]
    mockRoleData = makeMockRole(policies)

    const { default: RolePolicyDialog } = await import(
      '../components/permissions/RolePolicyDialog'
    )
    render(
      <RolePolicyDialog
        open={true}
        roleId="role-test-1"
        roleName="Test Role"
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
      { wrapper: makeWrapper() },
    )

    await waitFor(() => {
      expect(screen.getByText('agent::roles')).toBeDefined()
    })

    // Click DeleteIcon button
    const deleteButtons = screen.getAllByTestId('DeleteIcon')
    if (deleteButtons.length > 0) {
      fireEvent.click(deleteButtons[0])
    }

    await waitFor(() => {
      expect(screen.queryByText('agent::roles')).toBeNull()
    })
  })

  it('calls batch save with all current policies when Save is clicked in Form view', async () => {
    mockBatchSaveMutateAsync.mockResolvedValueOnce([])
    const policies = [
      makePolicyStatement('p1', 'agent::roles', ['read']),
    ]
    mockRoleData = makeMockRole(policies)
    const onSaved = vi.fn()
    const onClose = vi.fn()

    const { default: RolePolicyDialog } = await import(
      '../components/permissions/RolePolicyDialog'
    )
    render(
      <RolePolicyDialog
        open={true}
        roleId="role-test-1"
        roleName="Test Role"
        onClose={onClose}
        onSaved={onSaved}
      />,
      { wrapper: makeWrapper() },
    )

    await waitFor(() => {
      expect(screen.getByText('agent::roles')).toBeDefined()
    })

    const saveBtn = screen.getByRole('button', { name: /permissions\.roles\.saveBatch/i })
    expect((saveBtn as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(saveBtn)

    await waitFor(() => {
      expect(mockBatchSaveMutateAsync).toHaveBeenCalled()
    })

    const callArg = mockBatchSaveMutateAsync.mock.calls[0][0]
    expect(callArg.roleId).toBe('role-test-1')
    expect(callArg.data.policies.length).toBe(1)
    expect(callArg.data.policies[0].module).toBe('agent::roles')
    expect(onSaved).toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  it('shows error alert when batch save fails', async () => {
    const errorMsg = 'Permission denied: cannot manage policies'
    mockBatchSaveMutateAsync.mockRejectedValueOnce(new Error(errorMsg))
    const policies = [
      makePolicyStatement('p1', 'agent::roles', ['read']),
    ]
    mockRoleData = makeMockRole(policies)
    const onClose = vi.fn()

    const { default: RolePolicyDialog } = await import(
      '../components/permissions/RolePolicyDialog'
    )
    render(
      <RolePolicyDialog
        open={true}
        roleId="role-test-1"
        roleName="Test Role"
        onClose={onClose}
        onSaved={vi.fn()}
      />,
      { wrapper: makeWrapper() },
    )

    await waitFor(() => {
      expect(screen.getByText('agent::roles')).toBeDefined()
    })

    fireEvent.click(screen.getByRole('button', { name: /permissions\.roles\.saveBatch/i }))

    await waitFor(() => {
      const alert = screen.queryByTestId('permission-denied-alert')
      expect(alert).not.toBeNull()
    })
    expect(onClose).not.toHaveBeenCalled()
  })

  it('toggles to JSON view and shows textarea', async () => {
    const policies = [
      makePolicyStatement('p1', 'agent::roles', ['read']),
    ]
    mockRoleData = makeMockRole(policies)

    const { default: RolePolicyDialog } = await import(
      '../components/permissions/RolePolicyDialog'
    )
    render(
      <RolePolicyDialog
        open={true}
        roleId="role-test-1"
        roleName="Test Role"
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
      { wrapper: makeWrapper() },
    )

    await waitFor(() => {
      expect(screen.getByText('agent::roles')).toBeDefined()
    })

    fireEvent.click(screen.getByRole('button', { name: 'permissions.roles.jsonView' }))

    await waitFor(() => {
      const textarea = screen.queryByRole('textbox') as HTMLTextAreaElement
      expect(textarea).not.toBeNull()
      if (textarea) {
        const parsed = JSON.parse(textarea.value || '{}')
        expect(parsed.policies).toBeDefined()
        expect(parsed.policies.length).toBe(1)
        expect(parsed.policies[0].module).toBe('agent::roles')
      }
    })
  })

  it('Save button is always enabled (validation happens on save, not via separate button)', async () => {
    mockRoleData = makeMockRole([])

    const { default: RolePolicyDialog } = await import(
      '../components/permissions/RolePolicyDialog'
    )
    render(
      <RolePolicyDialog
        open={true}
        roleId="role-test-1"
        roleName="Test Role"
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
      { wrapper: makeWrapper() },
    )

    await waitFor(() => {
      expect(screen.getByText('permissions.roles.noPolicies')).toBeDefined()
    })

    // Save should be enabled even in form view with no validation
    const saveBtn = screen.getByRole('button', { name: /permissions\.roles\.saveBatch/i })
    expect((saveBtn as HTMLButtonElement).disabled).toBe(false)
  })
})
