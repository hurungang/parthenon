/**
 * Validation and error-state tests for RolePolicyDialog.
 *
 * Covers:
 * - Save from JSON view validates inline (no separate Validate button)
 * - JSON validation errors on save: malformed, missing array, missing module, flat type, missing actions
 * - Successful JSON save after validation passes
 * - Unsaved changes guard: Cancel show confirmation when changes exist
 * - Batch save error handling: 422, 500 errors shown in dialog
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
let confirmCloseRequested = false
const closeCallbacks: (() => void)[] = []

function resetDialogState() {
  mockHasUnsavedChanges = false
  confirmCloseRequested = false
  closeCallbacks.length = 0
}

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
    const [showConfirm, setShowConfirm] = React.useState(false)

    const markUnsaved = React.useCallback(() => setHasUnsavedChanges(true), [])
    const markSaved = React.useCallback(() => setHasUnsavedChanges(false), [])

    const handleClose = React.useCallback(
      (closeFn: () => void) => {
        if (hasUnsavedChanges) {
          closeCallbacks.push(closeFn)
          setShowConfirm(true)
          confirmCloseRequested = true
        } else {
          closeFn()
        }
      },
      [hasUnsavedChanges],
    )

    const handleDiscard = React.useCallback(() => {
      setShowConfirm(false)
      const cb = closeCallbacks.pop()
      if (cb) cb()
    }, [])

    const handleKeepEditing = React.useCallback(() => {
      setShowConfirm(false)
      closeCallbacks.pop()
    }, [])

    function ConfirmationDialog() {
      if (!showConfirm) return null
      return React.createElement(
        'div',
        { 'data-testid': 'discard-confirm-dialog' },
        React.createElement('span', null, 'Discard unsaved changes?'),
        React.createElement(
          'button',
          { 'data-testid': 'discard-btn', onClick: handleDiscard },
          'permissions.roles.discard',
        ),
        React.createElement(
          'button',
          { 'data-testid': 'keep-editing-btn', onClick: handleKeepEditing },
          'permissions.roles.keepEditing',
        ),
      )
    }

    return {
      hasUnsavedChanges, markUnsaved, markSaved, handleClose, ConfirmationDialog,
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
  }: {
    value: string
    onChange: (val: string) => void
  }) =>
    React.createElement('input', {
      'data-testid': 'resource-type-select',
      value,
      onChange: (e: React.ChangeEvent<HTMLInputElement>) => onChange(e.target.value),
    }),
}))

vi.mock('../components/permissions/FreeSoloActionSelect', () => ({
  default: ({
    value,
  }: {
    value: string[]
  }) =>
    React.createElement('div', {
      'data-testid': 'action-select',
      'data-value': JSON.stringify(value),
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

function makeMockRole(policyStatements: unknown[] = []) {
  return {
    id: 'role-test-1',
    name: 'Test Role',
    description: '',
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

describe('RolePolicyDialog — Validation on Save', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockRoleData = null
    mockRoleLoading = false
    mockBatchSaveMutateAsync.mockReset()
    resetDialogState()
  })

  it('shows error when saving malformed JSON', async () => {
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
      fireEvent.click(screen.getByRole('button', { name: 'permissions.roles.jsonView' }))
    })

    await waitFor(() => {
      const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
      fireEvent.change(textarea, { target: { value: '{broken json!!!!' } })
    })

    // Save should validate inline and show error
    fireEvent.click(screen.getByRole('button', { name: /permissions\.roles\.saveBatch/i }))

    await waitFor(() => {
      expect(screen.queryByText(/permissions\.roles\.invalidJson/)).toBeTruthy()
    })
  })

  it('shows error when saving JSON without policies array', async () => {
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
      fireEvent.click(screen.getByRole('button', { name: 'permissions.roles.jsonView' }))
    })

    await waitFor(() => {
      const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
      fireEvent.change(textarea, { target: { value: '{"other": "stuff"}' } })
    })

    fireEvent.click(screen.getByRole('button', { name: /permissions\.roles\.saveBatch/i }))

    await waitFor(() => {
      expect(screen.queryByText(/permissions\.roles\.invalidJson/)).toBeTruthy()
    })
  })

  it('shows error when saving JSON with empty module', async () => {
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
      fireEvent.click(screen.getByRole('button', { name: 'permissions.roles.jsonView' }))
    })

    await waitFor(() => {
      const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
      const badJson = JSON.stringify({
        policies: [
          { module: '', effect: 'allow', actions: [{ action: 'read' }], resources: [], tag_conditions: [] },
        ],
      })
      fireEvent.change(textarea, { target: { value: badJson } })
    })

    fireEvent.click(screen.getByRole('button', { name: /permissions\.roles\.saveBatch/i }))

    await waitFor(() => {
      expect(screen.queryByText(/permissions\.roles\.invalidJson/)).toBeTruthy()
    })
  })

  it('shows error when saving JSON with flat resource type', async () => {
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
      fireEvent.click(screen.getByRole('button', { name: 'permissions.roles.jsonView' }))
    })

    await waitFor(() => {
      const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
      const badJson = JSON.stringify({
        policies: [
          { module: 'agent', effect: 'allow', actions: [{ action: 'read' }], resources: [], tag_conditions: [] },
        ],
      })
      fireEvent.change(textarea, { target: { value: badJson } })
    })

    fireEvent.click(screen.getByRole('button', { name: /permissions\.roles\.saveBatch/i }))

    await waitFor(() => {
      expect(screen.queryByText(/permissions\.roles\.invalidJson/)).toBeTruthy()
    })
  })

  it('shows error when saving JSON with empty actions', async () => {
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
      fireEvent.click(screen.getByRole('button', { name: 'permissions.roles.jsonView' }))
    })

    await waitFor(() => {
      const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
      const badJson = JSON.stringify({
        policies: [
          { module: 'agent::roles', effect: 'allow', actions: [], resources: [], tag_conditions: [] },
        ],
      })
      fireEvent.change(textarea, { target: { value: badJson } })
    })

    fireEvent.click(screen.getByRole('button', { name: /permissions\.roles\.saveBatch/i }))

    await waitFor(() => {
      expect(screen.queryByText(/permissions\.roles\.invalidJson/)).toBeTruthy()
    })
  })

  it('saves successfully from JSON view with valid data', async () => {
    mockBatchSaveMutateAsync.mockResolvedValueOnce([])
    mockRoleData = makeMockRole([])
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
      fireEvent.click(screen.getByRole('button', { name: 'permissions.roles.jsonView' }))
    })

    await waitFor(() => {
      const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
      const validJson = JSON.stringify({
        policies: [
          {
            module: 'agent::roles',
            effect: 'allow',
            actions: [{ action: 'read' }],
            resources: [],
            tag_conditions: [],
          },
        ],
      })
      fireEvent.change(textarea, { target: { value: validJson } })
    })

    fireEvent.click(screen.getByRole('button', { name: /permissions\.roles\.saveBatch/i }))

    await waitFor(() => {
      expect(mockBatchSaveMutateAsync).toHaveBeenCalled()
    })
    expect(onSaved).toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  it('Save button is always enabled (no separate validation step)', async () => {
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
      fireEvent.click(screen.getByRole('button', { name: 'permissions.roles.jsonView' }))
    })

    await waitFor(() => {
      const saveBtn = screen.getByRole('button', { name: /permissions\.roles\.saveBatch/i })
      expect((saveBtn as HTMLButtonElement).disabled).toBe(false)
    })
  })

  it('shows unsaved changes confirmation when Cancel is clicked with changes', async () => {
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

    await waitFor(() => {
      expect(screen.queryAllByTestId('resource-type-select').length).toBe(1)
    })

    await waitFor(() => {
      fireEvent.click(screen.getByRole('button', { name: /app\.done/i }))
    })

    fireEvent.click(screen.getByRole('button', { name: /app\.cancel/i }))
    expect(confirmCloseRequested).toBe(true)
  })

  it('closes without confirmation when no changes were made', async () => {
    mockRoleData = makeMockRole([])
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
      expect(screen.getByText('permissions.roles.noPolicies')).toBeDefined()
    })

    fireEvent.click(screen.getByRole('button', { name: /app\.cancel/i }))
    expect(confirmCloseRequested).toBe(false)
  })

  it('displays batch save 422 validation error in dialog', async () => {
    const validationError = new Error("Policy at index 0: unknown module 'agent::nonexistent'")
    mockBatchSaveMutateAsync.mockRejectedValueOnce(validationError)
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

    fireEvent.click(screen.getByRole('button', { name: /permissions\.roles\.saveBatch/i }))

    await waitFor(() => {
      const alert = screen.queryByTestId('permission-denied-alert')
      expect(alert).not.toBeNull()
    })
  })

  it('displays batch save 500 error in dialog', async () => {
    const serverError = new Error('Internal server error')
    mockBatchSaveMutateAsync.mockRejectedValueOnce(serverError)
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

    fireEvent.click(screen.getByRole('button', { name: /permissions\.roles\.saveBatch/i }))

    await waitFor(() => {
      const alert = screen.queryByTestId('permission-denied-alert')
      expect(alert).not.toBeNull()
    })
  })

  it('discard confirmation: "Keep Editing" keeps dialog open', async () => {
    mockRoleData = makeMockRole([])
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
      expect(screen.getByText('permissions.roles.noPolicies')).toBeDefined()
    })

    fireEvent.click(screen.getByRole('button', { name: /permissions\.roles\.addPolicyRow/i }))

    await waitFor(() => {
      expect(screen.queryAllByTestId('resource-type-select').length).toBe(1)
    })

    await waitFor(() => {
      fireEvent.click(screen.getByRole('button', { name: /app\.done/i }))
    })

    fireEvent.click(screen.getByRole('button', { name: /app\.cancel/i }))

    await waitFor(() => {
      expect(screen.queryByTestId('discard-confirm-dialog')).not.toBeNull()
    })

    fireEvent.click(screen.getByTestId('keep-editing-btn'))
    expect(onClose).not.toHaveBeenCalled()
  })

  it('discard confirmation: "Discard" closes the dialog', async () => {
    mockRoleData = makeMockRole([])
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
      expect(screen.getByText('permissions.roles.noPolicies')).toBeDefined()
    })

    fireEvent.click(screen.getByRole('button', { name: /permissions\.roles\.addPolicyRow/i }))

    await waitFor(() => {
      expect(screen.queryAllByTestId('resource-type-select').length).toBe(1)
    })

    await waitFor(() => {
      fireEvent.click(screen.getByRole('button', { name: /app\.done/i }))
    })

    fireEvent.click(screen.getByRole('button', { name: /app\.cancel/i }))

    await waitFor(() => {
      expect(screen.queryByTestId('discard-confirm-dialog')).not.toBeNull()
    })

    fireEvent.click(screen.getByTestId('discard-btn'))

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled()
    })
  })
})
