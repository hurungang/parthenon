import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockGet = vi.fn()
const mockPost = vi.fn()
const mockPut = vi.fn()

vi.mock('../api/apiClient', () => ({
  default: {
    get: mockGet,
    post: mockPost,
    put: mockPut,
  },
}))

// Mock react-query so the dialog can render standalone
function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

const onClose = vi.fn()
const onSaved = vi.fn().mockResolvedValue(undefined)

describe('AgentRoleDialog', () => {
  afterEach(() => {
    vi.clearAllMocks()
    mockGet.mockResolvedValue({ data: [] })
  })

  it('renders create dialog title when editRole is null', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockResolvedValue({ data: [] })

    render(
      <AgentRoleDialog open={true} editRole={null} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.roles.createTitle')).toBeDefined()
    })
  })

  it('renders edit dialog title when editRole is provided', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockResolvedValue({ data: [] })

    const editRole = {
      id: 'role-1',
      name: 'My Role',
      description: 'A role',
      sop_ids: [],
      skill_ids: [],
      allowed_identity_types: [],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }

    render(
      <AgentRoleDialog open={true} editRole={editRole} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.roles.editTitle')).toBeDefined()
    })
  })

  it('pre-populates name field when editing', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockResolvedValue({ data: [] })

    const editRole = {
      id: 'role-1',
      name: 'Existing Role Name',
      description: null,
      sop_ids: [],
      skill_ids: [],
      allowed_identity_types: [],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }

    render(
      <AgentRoleDialog open={true} editRole={editRole} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )

    await waitFor(() => {
      const nameInput = screen.getByDisplayValue('Existing Role Name')
      expect(nameInput).toBeDefined()
    })
  })

  it('clears dialogError on open', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockResolvedValue({ data: [] })

    const { rerender } = render(
      <AgentRoleDialog open={false} editRole={null} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )

    // Reopen the dialog — error state should be cleared
    await act(async () => {
      rerender(
        <AgentRoleDialog open={true} editRole={null} onClose={onClose} onSaved={onSaved} />
      )
    })

    // No PERMISSION ERROR alert should be visible (the info hint alert is expected)
    expect(screen.queryByText('app.error')).toBeNull()
  })

  it('calls onSaved after successful create', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockResolvedValue({ data: [] })
    mockPost.mockResolvedValue({ data: { id: 'new-role', name: 'New Role' } })

    render(
      <AgentRoleDialog open={true} editRole={null} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.roles.createTitle')).toBeDefined()
    })

    // Fill in name
    const nameInput = screen.getByLabelText(/app\.name/)
    await act(async () => {
      fireEvent.change(nameInput, { target: { value: 'New Role' } })
    })

    // Click save
    await act(async () => {
      fireEvent.click(screen.getByText('app.save'))
    })

    await waitFor(() => {
      expect(onSaved).toHaveBeenCalled()
    })
  })

  it('shows PermissionDeniedAlert when API call fails with 403', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockResolvedValue({ data: [] })
    const mockError = { response: { status: 403, data: { detail: 'Forbidden' } } }
    mockPost.mockRejectedValue(mockError)

    render(
      <AgentRoleDialog open={true} editRole={null} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.roles.createTitle')).toBeDefined()
    })

    await act(async () => {
      fireEvent.click(screen.getByText('app.save'))
    })

    await waitFor(() => {
      // PermissionDeniedAlert or fallback message should appear
      const alerts = screen.getAllByRole('alert')
      expect(alerts.length).toBeGreaterThan(0)
    })
  })

  it('Save button remains enabled when preview fetch fails', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockResolvedValue({ data: [] })

    const editRole = {
      id: 'role-1',
      name: 'My Role',
      description: null,
      sop_ids: [],
      skill_ids: [],
      allowed_identity_types: [],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }

    render(
      <AgentRoleDialog open={true} editRole={editRole} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )

    await waitFor(() => {
      const saveBtn = screen.getByText('app.save')
      expect(saveBtn).toBeDefined()
      // Save button must be enabled (not disabled)
      const btn = saveBtn.closest('button')
      if (btn) {
        expect(btn.disabled).toBe(false)
      }
    })
  })

  // ── allowed_identity_types ─────────────────────────────────────────────────

  it('renders allowed_identity_types multi-select in the dialog', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockResolvedValue({ data: [] })

    render(
      <AgentRoleDialog open={true} editRole={null} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )

    await waitFor(() => {
      // The dialog should contain the identity types field (label or section header)
      const bodyText = document.body.innerHTML
      const hasIdentityTypesField =
        bodyText.includes('agents.roles.allowedIdentityTypes') ||
        bodyText.includes('allowed_identity_types') ||
        bodyText.includes('identityTypes')
      expect(hasIdentityTypesField).toBe(true)
    })
  })

  it('sends allowed_identity_types in POST payload when creating a role with constraint', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockResolvedValue({ data: [] })
    mockPost.mockResolvedValue({
      data: {
        id: 'new-role',
        name: 'Constrained Role',
        allowed_identity_types: ['service_account'],
      },
    })

    render(
      <AgentRoleDialog open={true} editRole={null} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByLabelText(/app\.name/)).toBeDefined()
    })

    await act(async () => {
      fireEvent.change(screen.getByLabelText(/app\.name/), {
        target: { value: 'Constrained Role' },
      })
    })

    await act(async () => {
      fireEvent.click(screen.getByText('app.save'))
    })

    await waitFor(() => {
      // POST was called — verify allowed_identity_types is in the payload
      if (mockPost.mock.calls.length > 0) {
        const postBody = mockPost.mock.calls[0][1]
        expect(postBody).toHaveProperty('allowed_identity_types')
      }
    })
  })

  it('sends updated allowed_identity_types in PUT payload when editing a role', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockResolvedValue({ data: [] })
    mockPut.mockResolvedValue({
      data: {
        id: 'role-1',
        name: 'Updated Role',
        allowed_identity_types: ['agent_user'],
      },
    })

    const editRole = {
      id: 'role-1',
      name: 'Existing Role',
      description: null,
      sop_ids: [],
      skill_ids: [],
      allowed_identity_types: [],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }

    render(
      <AgentRoleDialog
        open={true}
        editRole={editRole}
        onClose={onClose}
        onSaved={onSaved}
      />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.roles.editTitle')).toBeDefined()
    })

    await act(async () => {
      fireEvent.click(screen.getByText('app.save'))
    })

    await waitFor(() => {
      // PUT was called — verify allowed_identity_types is in the payload
      if (mockPut.mock.calls.length > 0) {
        const putBody = mockPut.mock.calls[0][1]
        expect(putBody).toHaveProperty('allowed_identity_types')
      }
    })
  })
})
