import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import type { AgentType, AgentJob, AgentPlan } from '../types'

// ── Hoisted mock refs ─────────────────────────────────────────────────────────

const { mockNavigate } = vi.hoisted(() => ({ mockNavigate: vi.fn() }))

// ── Module mocks ──────────────────────────────────────────────────────────────

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

vi.mock('../components/agents/TopologyDiagramRenderer', () => ({
  default: () => <div data-testid="topology-diagram" />,
}))

vi.mock('../components/agents/AgentPlanContent', () => ({
  default: ({
    plan,
    noPlanMessage,
  }: {
    plan: AgentPlan | null | undefined
    noPlanMessage?: string
  }) =>
    plan ? (
      <div data-testid="plan-content">plan-loaded</div>
    ) : (
      <div data-testid="no-plan">{noPlanMessage ?? 'no-plan'}</div>
    ),
}))

vi.mock('../pages/agents/AgentJobLaunchDialog', () => ({
  AgentJobLaunchDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="launch-dialog">launch</div> : null,
}))

vi.mock('../components/permissions/PermissionDeniedAlert', () => ({
  default: ({ fallbackMessage }: { error: unknown; fallbackMessage?: string }) => (
    <div data-testid="permission-denied-alert">{fallbackMessage ?? 'error'}</div>
  ),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: [] }),
  },
}))

vi.mock('../components/agents/AgentRoleViewDialog', () => ({
  AgentRoleViewDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="role-view-dialog">role-view</div> : null,
}))

vi.mock('../components/agents/AgentIdentityViewDialog', () => ({
  AgentIdentityViewDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="identity-view-dialog">identity-view</div> : null,
}))

// ── Mutable useAgentType state ────────────────────────────────────────────────

let mockAgentTypeData: AgentType | undefined = undefined
let mockAgentTypeLoading = false
let mockAgentTypeError: Error | null = null

vi.mock('../hooks/useAgentTypes', () => ({
  useAgentType: (_id: string) => ({
    data: mockAgentTypeData,
    isLoading: mockAgentTypeLoading,
    error: mockAgentTypeError,
  }),
  useAgentTypes: () => ({ data: [], isLoading: false, error: null }),
}))

// ── Test fixtures ──────────────────────────────────────────────────────────────

const MOCK_AGENT_TYPE: AgentType = {
  id: 'at-1',
  name: 'Research Agent',
  description: 'Performs research tasks',
  identity_id: 'identity-1',
  role_id: 'role-1',
  model_id: 'gpt-4o',
  system_instruction: 'You are a research assistant.',
  input_type: 'typed',
  input_schema: null,
  output_type: 'markdown',
  output_schema: null,
  primary_sop_id: null,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  plan: null,
}

const MOCK_PLAN: AgentPlan = {
  id: 'plan-1',
  agent_type_id: 'at-1',
  plan_steps: [
    { order: 1, type: 'tool_call', name: 'Search Web', description: 'Search the web' },
  ],
  topology_nodes: [{ id: 'role:r1', type: 'role', label: 'Research Role' }],
  topology_edges: [],
  generation_status: 'success',
  generation_error: null,
  agent_config_hash: 'abc123',
  generated_at: '2026-01-01T00:00:00Z',
}

const MOCK_SESSIONS: AgentJob[] = [
  {
    id: 'session-uuid-1234',
    agent_type_id: 'at-1',
    triggered_by_user_id: 'user-1',
    input_data: null,
    status: 'completed',
    started_at: '2026-01-01T10:00:00Z',
    completed_at: '2026-01-01T10:05:00Z',
    output_data: null,
    error_message: null,
    conversation_history: null,
    created_at: '2026-01-01T10:00:00Z',
  },
]

// ── Wrapper ────────────────────────────────────────────────────────────────────

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('AgentTypeDetailsDialog', () => {
  beforeEach(() => {
    mockAgentTypeData = undefined
    mockAgentTypeLoading = false
    mockAgentTypeError = null
    vi.resetAllMocks()
  })

  it('shows loading spinner when data is loading', async () => {
    mockAgentTypeLoading = true
    mockAgentTypeData = undefined

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    expect(screen.getByRole('progressbar')).toBeDefined()
  })

  it('shows dialog title key when agent type is not loaded yet', async () => {
    mockAgentTypeLoading = true
    mockAgentTypeData = undefined

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    // Title falls back to i18n key when no agentType loaded
    expect(screen.getByText('agents.types.dialogTitle')).toBeDefined()
  })

  it('renders agent type name in dialog title after loading', async () => {
    mockAgentTypeData = MOCK_AGENT_TYPE

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    // 'Research Agent' appears in both the dialog title and the Details tab name field
    expect(screen.getAllByText('Research Agent').length).toBeGreaterThan(0)
  })

  it('renders Details tab with correct field values', async () => {
    mockAgentTypeData = MOCK_AGENT_TYPE

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    // Model ID
    expect(screen.getByText('gpt-4o')).toBeDefined()
    // Status chip (is_active = true)
    expect(screen.getByText('app.active')).toBeDefined()
    // Input/output type chips
    expect(screen.getByText('typed')).toBeDefined()
    expect(screen.getByText('markdown')).toBeDefined()
    // System instruction
    expect(screen.getByText('You are a research assistant.')).toBeDefined()
  })

  it('renders three tabs', async () => {
    mockAgentTypeData = MOCK_AGENT_TYPE

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    const tabs = screen.getAllByRole('tab')
    expect(tabs.length).toBe(3)
    expect(tabs[0].textContent).toBe('agents.types.detailsTab')
    expect(tabs[1].textContent).toBe('agents.types.planPreviewTab')
    expect(tabs[2].textContent).toBe('agents.types.executionLogsTab')
  })

  it('shows no-plan placeholder on Plan Preview tab when plan is null', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, plan: null }

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    const tabs = screen.getAllByRole('tab')
    await act(async () => {
      fireEvent.click(tabs[1])
    })

    expect(screen.getByTestId('no-plan')).toBeDefined()
  })

  it('shows plan content on Plan Preview tab when plan is populated', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, plan: MOCK_PLAN }

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    const tabs = screen.getAllByRole('tab')
    await act(async () => {
      fireEvent.click(tabs[1])
    })

    expect(screen.getByTestId('plan-content')).toBeDefined()
  })

  it('shows session list on Execution Logs tab', async () => {
    mockAgentTypeData = MOCK_AGENT_TYPE

    const apiMock = await import('../api/apiClient')
    vi.mocked(apiMock.default.get).mockResolvedValue({ data: MOCK_SESSIONS })

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    const tabs = screen.getAllByRole('tab')
    await act(async () => {
      fireEvent.click(tabs[2])
    })

    // Session ID 'session-uuid-1234'.slice(0, 8) = 'session-', displayed with ellipsis
    await waitFor(() => {
      const sessionIdText = screen.getByText(/^session-/)
      expect(sessionIdText).toBeDefined()
    })
  })

  it('shows empty state on Execution Logs tab when no sessions', async () => {
    mockAgentTypeData = MOCK_AGENT_TYPE

    const apiMock = await import('../api/apiClient')
    vi.mocked(apiMock.default.get).mockResolvedValue({ data: [] })

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    const tabs = screen.getAllByRole('tab')
    await act(async () => {
      fireEvent.click(tabs[2])
    })

    await waitFor(() => {
      expect(screen.getByText('agents.sessions.dashboardEmpty')).toBeDefined()
    })
  })

  it('identity field shows dash when identity_id is null', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, identity_id: null }

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    // identity name link should not be rendered; identity-view-dialog should not appear
    expect(screen.queryByTestId('identity-view-dialog')).toBeNull()
    // no clickable link for identity
    const identityLink = screen.queryByRole('button', { name: 'agents.types.viewIdentity' })
    expect(identityLink).toBeNull()
  })

  it('clicking identity name opens AgentIdentityViewDialog', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, identity_id: 'identity-1' }

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    // The identity name (or fallback id) renders as a clickable link/button
    await waitFor(() => {
      const identityLink = screen.getByRole('button', { name: /identity-1/ })
      expect(identityLink).toBeDefined()
    })

    const identityLink = screen.getByRole('button', { name: /identity-1/ })
    await act(async () => {
      fireEvent.click(identityLink)
    })

    expect(screen.getByTestId('identity-view-dialog')).toBeDefined()
  })

  it('role field shows dash when role_id is null', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, role_id: null }

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    // role view dialog should not appear
    expect(screen.queryByTestId('role-view-dialog')).toBeNull()
    // no button labelled viewRole
    const roleBtn = screen.queryByRole('button', { name: 'agents.types.viewRole' })
    expect(roleBtn).toBeNull()
  })

  it('clicking role name opens AgentRoleViewDialog', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, role_id: 'role-1' }

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    // The role name (or fallback id) renders as a clickable link/button
    await waitFor(() => {
      const roleLink = screen.getByRole('button', { name: /role-1/ })
      expect(roleLink).toBeDefined()
    })

    const roleLink = screen.getByRole('button', { name: /role-1/ })
    await act(async () => {
      fireEvent.click(roleLink)
    })

    expect(screen.getByTestId('role-view-dialog')).toBeDefined()
  })

  it('clicking role name opens AgentRoleViewDialog (duplicate guard)', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, role_id: 'role-1' }

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /role-1/ })).toBeDefined()
    })

    // Clicking the link opens the view dialog (not navigate away)
    const roleLink = screen.getByRole('button', { name: /role-1/ })
    await act(async () => {
      fireEvent.click(roleLink)
    })

    expect(screen.getByTestId('role-view-dialog')).toBeDefined()
  })

  it('shows PermissionDeniedAlert when agent type fetch fails', async () => {
    mockAgentTypeError = new Error('Forbidden')

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('permission-denied-alert')).toBeDefined()
    })
  })

  it('calls onClose when the close button is clicked', async () => {
    mockAgentTypeData = MOCK_AGENT_TYPE
    const onClose = vi.fn()

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={onClose} />, { wrapper })

    const closeBtn = screen.getByRole('button', { name: 'app.close' })
    await act(async () => {
      fireEvent.click(closeBtn)
    })

    expect(onClose).toHaveBeenCalledOnce()
  })

  it('resets to Details tab when dialog re-opens', async () => {
    mockAgentTypeData = MOCK_AGENT_TYPE

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    // rerender from render() applies wrapper automatically — do not pass wrapper elements directly
    const { rerender } = render(
      <AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />,
      { wrapper },
    )

    // Switch to Plan Preview tab
    const tabs = screen.getAllByRole('tab')
    await act(async () => {
      fireEvent.click(tabs[1])
    })

    // Close the dialog
    rerender(<AgentTypeDetailsDialog open={false} agentTypeId={null} onClose={vi.fn()} />)
    // Re-open with same agentTypeId
    rerender(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />)

    // Details tab (index 0) should be selected again
    const updatedTabs = screen.getAllByRole('tab')
    expect(updatedTabs[0]).toHaveAttribute('aria-selected', 'true')
  })
})
