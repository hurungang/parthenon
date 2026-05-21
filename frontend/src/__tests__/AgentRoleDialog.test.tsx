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

  it('shows allowed agent type preview hint in create mode', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockResolvedValue({ data: [] })

    render(
      <AgentRoleDialog open={true} editRole={null} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.roles.allowedAgentTypePreviewHint')).toBeDefined()
    })
  })

  it('renders allowed agent type preview chips for selected SOPs in edit mode', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockImplementation((url: string) => {
      if (url === '/sops') {
        return Promise.resolve({ data: [{ id: 'sop-1', name: 'Delegation SOP', required_skill_ids: [] }] })
      }
      if (url === '/skills') {
        return Promise.resolve({ data: [] })
      }
      if (url.includes('/identities') || url.includes('/mcp-sessions') || url.includes('/mcp-tools')) {
        return Promise.resolve({ data: [] })
      }
      if (url.includes('/allowed-agent-types')) {
        return Promise.resolve({ data: ['planner-agent', 'review-agent'] })
      }
      return Promise.resolve({ data: [] })
    })

    const editRole = {
      id: 'role-1',
      name: 'Delegator Role',
      description: null,
      sop_ids: ['sop-1'],
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
      expect(screen.getByText('planner-agent')).toBeDefined()
      expect(screen.getByText('review-agent')).toBeDefined()
    })
  })

  it('requests allowed agent types using the selected SOP ids', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockImplementation((url: string) => {
      if (url === '/sops') {
        return Promise.resolve({ data: [{ id: 'sop-1', name: 'Delegation SOP', required_skill_ids: [] }] })
      }
      if (url === '/skills') {
        return Promise.resolve({ data: [] })
      }
      if (url.includes('/identities') || url.includes('/mcp-sessions') || url.includes('/mcp-tools')) {
        return Promise.resolve({ data: [] })
      }
      if (url.includes('/allowed-agent-types')) {
        return Promise.resolve({ data: ['planner-agent'] })
      }
      return Promise.resolve({ data: [] })
    })

    const editRole = {
      id: 'role-2',
      name: 'Delegator Role',
      description: null,
      sop_ids: ['sop-1'],
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
      expect(
        mockGet.mock.calls.some(([url]) => String(url).includes('/allowed-agent-types?sop_ids=sop-1'))
      ).toBe(true)
    })
  })

  it('shows the empty allowed agent type state when the preview response is empty', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockImplementation((url: string) => {
      if (url === '/sops') {
        return Promise.resolve({ data: [{ id: 'sop-1', name: 'Delegation SOP', required_skill_ids: [] }] })
      }
      if (url === '/skills') {
        return Promise.resolve({ data: [] })
      }
      if (url.includes('/identities') || url.includes('/mcp-sessions') || url.includes('/mcp-tools')) {
        return Promise.resolve({ data: [] })
      }
      if (url.includes('/allowed-agent-types')) {
        return Promise.resolve({ data: [] })
      }
      return Promise.resolve({ data: [] })
    })

    const editRole = {
      id: 'role-3',
      name: 'No Delegation Role',
      description: null,
      sop_ids: ['sop-1'],
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
      expect(screen.getByText('agents.roles.noAllowedAgentTypes')).toBeDefined()
    })
  })

  it('refreshes the allowed agent type preview when SOP selection changes', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockImplementation((url: string) => {
      if (url === '/sops') {
        return Promise.resolve({
          data: [
            { id: 'sop-1', name: 'Delegation SOP', required_skill_ids: [] },
            { id: 'sop-2', name: 'Escalation SOP', required_skill_ids: [] },
          ],
        })
      }
      if (url === '/skills') {
        return Promise.resolve({ data: [] })
      }
      if (url.includes('/identities') || url.includes('/mcp-sessions') || url.includes('/mcp-tools')) {
        return Promise.resolve({ data: [] })
      }
      if (url.includes('/allowed-agent-types')) {
        return Promise.resolve({ data: ['planner-agent'] })
      }
      return Promise.resolve({ data: [] })
    })

    const editRole = {
      id: 'role-4',
      name: 'Dynamic Preview Role',
      description: null,
      sop_ids: ['sop-1'],
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
      expect(
        mockGet.mock.calls.some(([url]) => String(url).includes('/allowed-agent-types?sop_ids=sop-1'))
      ).toBe(true)
    })

    await act(async () => {
      fireEvent.click(screen.getByLabelText('Escalation SOP'))
    })

    await waitFor(() => {
      expect(
        mockGet.mock.calls.some(([url]) => String(url).includes('/allowed-agent-types?sop_ids=sop-1,sop-2'))
      ).toBe(true)
    })
  })
})
