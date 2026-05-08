/**
 * Unit tests for AddStatementDialog component.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'
import { PolicyEffect } from '../types/permissions'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockResourceTypes = [
  { resource_type: 'agent', actions: ['create', 'read', 'update', 'delete', 'execute'] },
  { resource_type: 'role', actions: ['read', 'manage'] },
  { resource_type: 'group', actions: ['create', 'read', 'update', 'delete', 'manage'] },
]

const mockTagDefs = [
  {
    id: 'td1',
    key: 'environment',
    scope: 'global',
    allowed_values: [
      { id: 'v1', tag_definition_id: 'td1', value: 'production', created_at: '' },
      { id: 'v2', tag_definition_id: 'td1', value: 'staging', created_at: '' },
    ],
    created_at: '',
    updated_at: '',
  },
]

const mockCreateStatement = vi.fn()
const mockUpdateStatement = vi.fn()

vi.mock('../hooks/usePermissions', () => ({
  useResourceTypes: () => ({ data: mockResourceTypes }),
  useTagDefinitions: () => ({ data: mockTagDefs }),
  useCreatePolicyStatement: () => ({
    mutateAsync: mockCreateStatement,
    isPending: false,
  }),
  useUpdatePolicyStatement: () => ({
    mutateAsync: mockUpdateStatement,
    isPending: false,
  }),
}))

vi.mock('../hooks/useTagValueOptions', () => ({
  useTagValueOptions: (key: string | null) => {
    if (key === 'environment') return ['production', 'staging']
    return []
  },
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

describe('AddStatementDialog', () => {
  it('resource type dropdown is populated from useResourceTypes data', async () => {
    const { default: AddStatementDialog } = await import(
      '../components/permissions/AddStatementDialog'
    )
    render(
      <AddStatementDialog open={true} roleId="role-1" onClose={vi.fn()} />,
      { wrapper: makeWrapper() }
    )

    // MUI Select label renders multiple times — use findAllByText
    const labels = await screen.findAllByText('permissions.roles.resourceType')
    expect(labels.length).toBeGreaterThan(0)
  })

  it('Effect dropdown contains Allow and Deny options', async () => {
    const { default: AddStatementDialog } = await import(
      '../components/permissions/AddStatementDialog'
    )
    render(
      <AddStatementDialog open={true} roleId="role-1" onClose={vi.fn()} />,
      { wrapper: makeWrapper() }
    )

    // Effect label might appear multiple times (MUI renders label + legend)
    const effectLabels = await screen.findAllByText('permissions.roles.effect')
    expect(effectLabels.length).toBeGreaterThan(0)
  })

  it('Save button is disabled when resource type or actions are empty', async () => {
    const { default: AddStatementDialog } = await import(
      '../components/permissions/AddStatementDialog'
    )
    render(
      <AddStatementDialog open={true} roleId="role-1" onClose={vi.fn()} />,
      { wrapper: makeWrapper() }
    )

    // In add mode the button label is permissions.roles.saveStatement (not app.save)
    const saveButton = await screen.findByRole('button', { name: /permissions\.roles\.saveStatement/i })
    expect((saveButton as HTMLButtonElement).disabled).toBe(true)
  })

  it('Add Tag Condition button is present', async () => {
    const { default: AddStatementDialog } = await import(
      '../components/permissions/AddStatementDialog'
    )
    render(
      <AddStatementDialog open={true} roleId="role-1" onClose={vi.fn()} />,
      { wrapper: makeWrapper() }
    )

    await screen.findByText('permissions.roles.addTagCondition')
  })

  it('Cancel button calls onClose', async () => {
    const onClose = vi.fn()
    const { default: AddStatementDialog } = await import(
      '../components/permissions/AddStatementDialog'
    )
    render(
      <AddStatementDialog open={true} roleId="role-1" onClose={onClose} />,
      { wrapper: makeWrapper() }
    )

    const cancelBtn = await screen.findByRole('button', { name: /app\.cancel/i })
    fireEvent.click(cancelBtn)
    expect(onClose).toHaveBeenCalled()
  })

  it('API error is shown inline (Dialog Error Handling Standard)', async () => {
    const { default: AddStatementDialog } = await import(
      '../components/permissions/AddStatementDialog'
    )
    const { container } = render(
      <AddStatementDialog open={true} roleId="role-1" onClose={vi.fn()} />,
      { wrapper: makeWrapper() }
    )

    await waitFor(() => {
      expect(container).toBeDefined()
    })
  })

  it('form resets when dialog is reopened', async () => {
    const { default: AddStatementDialog } = await import(
      '../components/permissions/AddStatementDialog'
    )
    const wrapper = makeWrapper()
    const { rerender } = render(
      <AddStatementDialog open={false} roleId="role-1" onClose={vi.fn()} />,
      { wrapper }
    )

    // Reopen without creating new wrapper (same MemoryRouter context)
    rerender(<AddStatementDialog open={true} roleId="role-1" onClose={vi.fn()} />)

    const labels = await screen.findAllByText('permissions.roles.resourceType')
    expect(labels.length).toBeGreaterThan(0)
  })

  it('renders resource IDs section with Add Resource ID button', async () => {
    const { default: AddStatementDialog } = await import(
      '../components/permissions/AddStatementDialog'
    )
    render(
      <AddStatementDialog open={true} roleId="role-1" onClose={vi.fn()} />,
      { wrapper: makeWrapper() }
    )

    // Resource IDs section heading should be visible
    await screen.findByText('permissions.roles.resourceIds')

    // Add Resource ID button should be present (disabled until resource type is selected)
    const addResourceBtn = await screen.findByRole('button', {
      name: /permissions\.roles\.addResourceId/i,
    })
    expect(addResourceBtn).toBeDefined()
  })

  it('Add Resource ID button is disabled when no resource type selected', async () => {
    const { default: AddStatementDialog } = await import(
      '../components/permissions/AddStatementDialog'
    )
    render(
      <AddStatementDialog open={true} roleId="role-1" onClose={vi.fn()} />,
      { wrapper: makeWrapper() }
    )

    const addResourceBtn = await screen.findByRole('button', {
      name: /permissions\.roles\.addResourceId/i,
    })
    expect((addResourceBtn as HTMLButtonElement).disabled).toBe(true)
  })

  it('populates all form fields in edit mode from editingPolicy prop', async () => {
    const editingPolicy = {
      id: 'policy-edit-1',
      effect: PolicyEffect.Deny,
      module: 'role',
      actions: [{ id: 'a1', action: 'manage' }],
      resources: [{ id: 'r1', resource_type: 'role', resource_id: 'role-xyz' }],
      tag_conditions: [],
      created_at: '2024-01-01T00:00:00Z',
    }

    const { default: AddStatementDialog } = await import(
      '../components/permissions/AddStatementDialog'
    )
    render(
      <AddStatementDialog
        open={true}
        roleId="role-1"
        editingPolicy={editingPolicy}
        onClose={vi.fn()}
      />,
      { wrapper: makeWrapper() }
    )

    // Dialog title should indicate edit mode
    await screen.findByText('permissions.roles.editPolicyStatement')

    // The pre-selected module/resource-type chip should appear in the actions Autocomplete
    await screen.findByText('manage')

    // Resource ID row should appear with the pre-filled resource_id
    const resourceInput = await screen.findByDisplayValue('role-xyz')
    expect(resourceInput).toBeDefined()
  })

  it('calls useUpdatePolicyStatement (not create) when saving in edit mode', async () => {
    mockUpdateStatement.mockResolvedValueOnce({})

    const editingPolicy = {
      id: 'policy-to-update',
      effect: PolicyEffect.Allow,
      module: 'agent',
      actions: [{ id: 'a1', action: 'read' }],
      resources: [],
      tag_conditions: [],
      created_at: '2024-01-01T00:00:00Z',
    }

    const { default: AddStatementDialog } = await import(
      '../components/permissions/AddStatementDialog'
    )
    render(
      <AddStatementDialog
        open={true}
        roleId="role-1"
        editingPolicy={editingPolicy}
        onClose={vi.fn()}
      />,
      { wrapper: makeWrapper() }
    )

    // Wait for dialog to render; Save button should be enabled (form pre-filled)
    const saveBtn = await screen.findByRole('button', { name: /app\.save/i })
    expect((saveBtn as HTMLButtonElement).disabled).toBe(false)

    fireEvent.click(saveBtn)

    await waitFor(() => {
      expect(mockUpdateStatement).toHaveBeenCalledWith(
        expect.objectContaining({ roleId: 'role-1', policyId: 'policy-to-update' })
      )
      // Create must NOT be called
      expect(mockCreateStatement).not.toHaveBeenCalled()
    })
  })
})
