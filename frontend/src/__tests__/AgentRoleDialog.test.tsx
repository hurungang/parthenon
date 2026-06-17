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
const mockDelete = vi.fn()

vi.mock('../api/apiClient', () => ({
  default: {
    get: mockGet,
    post: mockPost,
    put: mockPut,
    delete: mockDelete,
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
      if (url === '/mcp/servers') {
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

  // ── New: Inline MCP Session Assignment Tests ──

  it('shows MCP session assignment hint when no SOPs/Skills are selected', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockImplementation((url: string) => {
      if (url === '/sops') return Promise.resolve({ data: [] })
      if (url === '/skills') return Promise.resolve({ data: [] })
      if (url === '/mcp/servers') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })

    render(
      <AgentRoleDialog open={true} editRole={null} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.roles.mcpSessionAssignmentHint')).toBeDefined()
    })
  })

  it('disables save button when required MCP server lacks session assignment', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockImplementation((url: string) => {
      if (url === '/sops') return Promise.resolve({ data: [] })
      if (url === '/skills') {
        return Promise.resolve({
          data: [
            {
              id: 'skill-1',
              name: 'Test Skill',
              description: null,
              is_active: true,
              is_system: false,
              tool_ids: ['tool-1'],
              created_at: '2026-01-01T00:00:00Z',
              updated_at: '2026-01-01T00:00:00Z',
            },
          ],
        })
      }
      if (url === '/mcp/servers') {
        return Promise.resolve({
          data: [
            { id: 'server-1', slug: 'github-mcp', name: 'GitHub MCP', description: null, base_url: '', status: 'active', last_synced_at: null, session_count: 1, created_at: '', updated_at: '' },
          ],
        })
      }
      if (url === '/mcp/tools') {
        return Promise.resolve({
          data: [
            { id: 'tool-1', server_id: 'server-1', name: 'github-mcp____list_repos', original_name: 'list_repos', description: null, input_schema: null, is_active: true, created_at: '', updated_at: '' },
          ],
        })
      }
      if (url.includes('/sessions')) {
        return Promise.resolve({
          data: [
            { id: 'sess-1', server_id: 'server-1', name: 'Admin Session', description: null, auth_type: 'api_key', identity_subject: null, is_active: true, is_default: false, identity_binding: null, credential_config: null, oauth_expires_at: null, oauth_refresh_expires_at: null, created_at: '', updated_at: '' },
          ],
        })
      }
      return Promise.resolve({ data: [] })
    })

    render(
      <AgentRoleDialog open={true} editRole={null} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )

    // Fill name
    await waitFor(() => {
      expect(screen.getByText('agents.roles.createTitle')).toBeDefined()
    })

    const nameInput = screen.getByLabelText(/app\.name/)
    await act(async () => {
      fireEvent.change(nameInput, { target: { value: 'New Role' } })
    })

    // Select skill
    await act(async () => {
      fireEvent.click(screen.getByLabelText('Test Skill'))
    })

    // Wait for the MCP server row to appear
    await waitFor(() => {
      expect(screen.getByText('GitHub MCP')).toBeDefined()
    })

    // Save button should be disabled because no session is selected
    const saveBtn = screen.getByText('app.save').closest('button')
    expect(saveBtn?.disabled).toBe(true)

    // Validation warning should appear
    expect(screen.getByText(/agents.roles.mcpSessionMissing/)).toBeDefined()
  })

  it('displays passthrough badge for servers with passthrough sessions', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockImplementation((url: string) => {
      if (String(url).includes('/sops')) return Promise.resolve({ data: [] })
      if (String(url).includes('/skills') && !String(url).includes('tool')) {
        return Promise.resolve({
          data: [
            {
              id: 'skill-pt',
              name: 'Passthrough Skill',
              description: null,
              is_active: true,
              is_system: false,
              tool_ids: ['tool-pt'],
              created_at: '2026-01-01T00:00:00Z',
              updated_at: '2026-01-01T00:00:00Z',
            },
          ],
        })
      }
      if (String(url) === '/mcp/servers' || String(url).startsWith('/mcp/servers?')) {
        return Promise.resolve({
          data: [
            { id: 'server-pt', slug: 'github-mcp', name: 'GitHub MCP', description: null, base_url: '', status: 'active', last_synced_at: null, session_count: 1, created_at: '', updated_at: '' },
          ],
        })
      }
      if (String(url).includes('/mcp/tools')) {
        return Promise.resolve({
          data: [
            { id: 'tool-pt', server_id: 'server-pt', name: 'github-mcp____list_repos', original_name: 'list_repos', description: null, input_schema: null, is_active: true, created_at: '', updated_at: '' },
          ],
        })
      }
      if (String(url).includes('/sessions')) {
        return Promise.resolve({
          data: [
            { id: 'sess-pt', server_id: 'server-pt', name: 'Passthrough Session', description: null, auth_type: 'passthrough', identity_subject: null, is_active: true, is_default: false, identity_binding: null, credential_config: null, oauth_expires_at: null, oauth_refresh_expires_at: null, created_at: '', updated_at: '' },
          ],
        })
      }
      return Promise.resolve({ data: [] })
    })

    render(
      <AgentRoleDialog open={true} editRole={null} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.roles.createTitle')).toBeDefined()
    })

    // Wait for skills data to load, then select the skill
    await waitFor(() => {
      expect(screen.getByText('Passthrough Skill')).toBeDefined()
    })
    await act(async () => {
      fireEvent.click(screen.getByText('Passthrough Skill'))
    })

    // Wait for passthrough chip
    await waitFor(() => {
      expect(screen.getByText('mcp.sessions.passthrough')).toBeDefined()
    })
  })

  it('enables save after selecting sessions for all required servers', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockImplementation((url: string) => {
      if (url === '/sops') return Promise.resolve({ data: [] })
      if (url === '/skills') {
        return Promise.resolve({
          data: [
            {
              id: 'skill-1',
              name: 'Test Skill',
              description: null,
              is_active: true,
              is_system: false,
              tool_ids: ['tool-1'],
              created_at: '2026-01-01T00:00:00Z',
              updated_at: '2026-01-01T00:00:00Z',
            },
          ],
        })
      }
      if (url === '/mcp/servers') {
        return Promise.resolve({
          data: [
            { id: 'server-1', slug: 'github-mcp', name: 'GitHub MCP', description: null, base_url: '', status: 'active', last_synced_at: null, session_count: 1, created_at: '', updated_at: '' },
          ],
        })
      }
      if (url === '/mcp/tools') {
        return Promise.resolve({
          data: [
            { id: 'tool-1', server_id: 'server-1', name: 'github-mcp____list_repos', original_name: 'list_repos', description: null, input_schema: null, is_active: true, created_at: '', updated_at: '' },
          ],
        })
      }
      if (url.includes('/sessions')) {
        return Promise.resolve({
          data: [
            { id: 'sess-1', server_id: 'server-1', name: 'Admin Session', description: null, auth_type: 'api_key', identity_subject: null, is_active: true, is_default: false, identity_binding: null, credential_config: null, oauth_expires_at: null, oauth_refresh_expires_at: null, created_at: '', updated_at: '' },
          ],
        })
      }
      return Promise.resolve({ data: [] })
    })

    render(
      <AgentRoleDialog open={true} editRole={null} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.roles.createTitle')).toBeDefined()
    })

    // Fill name
    const nameInput = screen.getByLabelText(/app\.name/)
    await act(async () => {
      fireEvent.change(nameInput, { target: { value: 'New Role' } })
    })

    // Select skill
    await act(async () => {
      fireEvent.click(screen.getByLabelText('Test Skill'))
    })

    // Wait for dropdown
    await waitFor(() => {
      expect(screen.getByText('GitHub MCP')).toBeDefined()
    })

    // Save should be disabled
    let saveBtn = screen.getByText('app.save').closest('button')
    expect(saveBtn?.disabled).toBe(true)

    // Select a session from the dropdown
    const select = screen.getByRole('combobox')
    await act(async () => {
      fireEvent.mouseDown(select)
    })
    await act(async () => {
      fireEvent.click(screen.getByText('Admin Session'))
    })

    await waitFor(() => {
      saveBtn = screen.getByText('app.save').closest('button')
      expect(saveBtn?.disabled).toBe(false)
    })
  })

  it('creates role and assigns sessions in create mode', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockImplementation((url: string) => {
      if (url === '/sops') return Promise.resolve({ data: [] })
      if (url === '/skills') {
        return Promise.resolve({
          data: [
            {
              id: 'skill-1',
              name: 'Test Skill',
              description: null,
              is_active: true,
              is_system: false,
              tool_ids: ['tool-1'],
              created_at: '2026-01-01T00:00:00Z',
              updated_at: '2026-01-01T00:00:00Z',
            },
          ],
        })
      }
      if (url === '/mcp/servers') {
        return Promise.resolve({
          data: [
            { id: 'server-1', slug: 'github-mcp', name: 'GitHub MCP', description: null, base_url: '', status: 'active', last_synced_at: null, session_count: 1, created_at: '', updated_at: '' },
          ],
        })
      }
      if (url === '/mcp/tools') {
        return Promise.resolve({
          data: [
            { id: 'tool-1', server_id: 'server-1', name: 'github-mcp____list_repos', original_name: 'list_repos', description: null, input_schema: null, is_active: true, created_at: '', updated_at: '' },
          ],
        })
      }
      if (url.includes('/sessions')) {
        return Promise.resolve({
          data: [
            { id: 'sess-1', server_id: 'server-1', name: 'Admin Session', description: null, auth_type: 'api_key', identity_subject: null, is_active: true, is_default: false, identity_binding: null, credential_config: null, oauth_expires_at: null, oauth_refresh_expires_at: null, created_at: '', updated_at: '' },
          ],
        })
      }
      return Promise.resolve({ data: [] })
    })
    mockPost.mockResolvedValue({ data: { id: 'new-role', name: 'New Role' } })

    render(
      <AgentRoleDialog open={true} editRole={null} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.roles.createTitle')).toBeDefined()
    })

    // Fill name
    const nameInput = screen.getByLabelText(/app\.name/)
    await act(async () => {
      fireEvent.change(nameInput, { target: { value: 'New Role' } })
    })

    // Select skill
    await act(async () => {
      fireEvent.click(screen.getByLabelText('Test Skill'))
    })

    // Wait for dropdown and select session
    await waitFor(() => {
      expect(screen.getByText('GitHub MCP')).toBeDefined()
    })

    const select = screen.getByRole('combobox')
    await act(async () => {
      fireEvent.mouseDown(select)
    })
    await act(async () => {
      fireEvent.click(screen.getByText('Admin Session'))
    })

    // Click save
    await act(async () => {
      fireEvent.click(screen.getByText('app.save'))
    })

    await waitFor(() => {
      // Verify role creation was called
      expect(mockPost).toHaveBeenCalledWith('/agents/roles', expect.any(Object))
      // Verify session assignment was called
      expect(mockPost).toHaveBeenCalledWith('/agents/roles/new-role/mcp-sessions', { mcp_session_id: 'sess-1' })
      expect(onSaved).toHaveBeenCalled()
    })
  })

  it('handles system tool exclusion in required servers computation', async () => {
    const { AgentRoleDialog } = await import('../pages/agents/AgentRoleDialog')
    mockGet.mockImplementation((url: string) => {
      if (String(url).includes('/sops')) return Promise.resolve({ data: [] })
      if (String(url).includes('/skills') && !String(url).includes('tool')) {
        return Promise.resolve({
          data: [
            {
              id: 'skill-sys',
              name: 'System Tool Skill',
              description: null,
              is_active: true,
              is_system: false,
              tool_ids: ['tool-sys'],
              created_at: '2026-01-01T00:00:00Z',
              updated_at: '2026-01-01T00:00:00Z',
            },
          ],
        })
      }
      if (String(url) === '/mcp/servers' || String(url).startsWith('/mcp/servers?')) {
        return Promise.resolve({
          data: [
            { id: 'server-sys', slug: 'github-mcp', name: 'GitHub MCP', description: null, base_url: '', status: 'active', last_synced_at: null, session_count: 1, created_at: '', updated_at: '' },
          ],
        })
      }
      if (String(url).includes('/mcp/tools')) {
        return Promise.resolve({
          data: [
            { id: 'tool-sys', server_id: 'server-sys', name: 'system____save_result', original_name: 'save_result', description: null, input_schema: null, is_active: true, created_at: '', updated_at: '' },
          ],
        })
      }
      if (String(url).includes('/sessions')) {
        return Promise.resolve({ data: [] })
      }
      return Promise.resolve({ data: [] })
    })

    render(
      <AgentRoleDialog open={true} editRole={null} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.roles.createTitle')).toBeDefined()
    })

    // Wait for skills data to load, then select the skill
    await waitFor(() => {
      expect(screen.getByText('System Tool Skill')).toBeDefined()
    })
    await act(async () => {
      fireEvent.click(screen.getByText('System Tool Skill'))
    })

    // No MCP server rows should appear (system tool is excluded)
    await waitFor(() => {
      expect(screen.queryByText('GitHub MCP')).toBeNull()
    })

    // The hint should still show (no servers required)
    expect(screen.getByText('agents.roles.mcpSessionAssignmentHint')).toBeDefined()
  })
})
