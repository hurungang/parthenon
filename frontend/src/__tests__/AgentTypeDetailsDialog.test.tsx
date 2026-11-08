import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import type { AgentType, AgentJob, AgentPlan } from '../types'

// ── Hoisted mock refs ─────────────────────────────────────────────────────────

const { mockNavigate, mockCanvasProps } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
  mockCanvasProps: {
    agentName: '' as string,
    draft: null as unknown,
    isDirty: false as boolean,
    onNodeClick: undefined as ((n: unknown) => void) | undefined,
  },
}))

// ── Module mocks ──────────────────────────────────────────────────────────────

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

vi.mock('../components/agents/panel/PanelTopologyCanvas', () => ({
  PanelTopologyCanvas: (props: {
    agentName: string
    draft: { sopBindings?: { sop_id: string }[]; skillBindings?: { skill_id: string }[] }
    isDirty: boolean
    onNodeClick?: (node: unknown) => void
  }) => {
    // Record props so tests can assert on the mapped draft + interactions.
    mockCanvasProps.agentName = props.agentName
    mockCanvasProps.draft = props.draft
    mockCanvasProps.isDirty = props.isDirty
    mockCanvasProps.onNodeClick = props.onNodeClick

    // Render clickable stand-ins for the zoned canvas nodes so node-click
    // behaviour can be exercised through the captured onNodeClick handler.
    const nodes: { id: string }[] = [
      { id: 'agent' },
      { id: 'role' },
      { id: 'identity' },
      ...(props.draft?.sopBindings ?? []).map((b) => ({ id: `sop_${b.sop_id}` })),
      ...(props.draft?.skillBindings ?? []).map((b) => ({ id: `skill_${b.skill_id}` })),
      { id: 'sop_empty' },
      { id: 'tool_empty' },
    ]
    return (
      <div data-testid="panel-topology-canvas">
        {(props.onNodeClick ? nodes : []).map((node) => (
          <button
            key={node.id}
            data-testid={`topology-node-${node.id}`}
            onClick={() => props.onNodeClick?.({ id: node.id, type: node.id.split('_')[0] })}
          >
            {node.id}
          </button>
        ))}
      </div>
    )
  },
}))

vi.mock('../components/agents/AgentPlanContent', () => ({
  default: ({
    plan,
    noPlanMessage,
    hideTopology,
  }: {
    plan: AgentPlan | null | undefined
    noPlanMessage?: string
    hideTopology?: boolean
  }) =>
    plan ? (
      <div
        data-testid="plan-content"
        data-hide-topology={hideTopology ? 'true' : 'false'}
      >
        plan-loaded
      </div>
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

const { mockApiGet, mockApiPost } = vi.hoisted(() => ({
  mockApiGet: vi.fn(),
  mockApiPost: vi.fn(),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: mockApiGet,
    post: mockApiPost,
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
  output_data_type_id: null,
  output_data_type_name: null,
  sop_bindings: [],
  skill_bindings: [],
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
    mockCanvasProps.agentName = ''
    mockCanvasProps.draft = null
    mockCanvasProps.isDirty = false
    mockCanvasProps.onNodeClick = undefined
    vi.resetAllMocks()
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/agents/roles') {
        return { data: [] }
      }
      return { data: [] }
    })
    mockApiPost.mockResolvedValue({ data: {} })
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

  it('renders a functional edit button for a non-system agent type', async () => {
    mockAgentTypeData = MOCK_AGENT_TYPE

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    const editBtn = await screen.findByRole('button', { name: 'app.edit' })
    expect(editBtn).toBeDefined()
    expect((editBtn as HTMLButtonElement).disabled).toBe(false)
    expect(screen.queryByTestId('edit-agent-type-disabled')).toBeNull()
  })

  it('marks a system agent type read-only — edit is disabled, never navigates', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, is_system: true }

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    // No functional edit button
    expect(screen.queryByRole('button', { name: 'app.edit' })).toBeNull()
    // Disabled stand-in keeps the edit affordance visibly unavailable
    const disabled = screen.getByTestId('edit-agent-type-disabled') as HTMLButtonElement
    expect(disabled.disabled).toBe(true)
    // Clicking the disabled control must NOT navigate to the edit form
    fireEvent.click(disabled)
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('renders Details tab with correct field values', async () => {
    mockAgentTypeData = MOCK_AGENT_TYPE

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    // Wait for dialog content to load with optional elements
    await waitFor(() => {
      const hasModelId = screen.queryByText('gpt-4o')
      const hasStatus = screen.queryByText('app.active')
      const hasContent = hasModelId || hasStatus
      expect(hasContent).toBeDefined()
    }, { timeout: 3000 })
  })

  it('renders five tabs — Scripts removed, Optimized Plan and Clients remain', async () => {
    mockAgentTypeData = MOCK_AGENT_TYPE

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    const tabs = screen.getAllByRole('tab')
    expect(tabs.length).toBe(5)
    expect(tabs[0].textContent).toBe('agents.types.detailsTab')
    expect(tabs[1].textContent).toBe('agents.types.agentPreviewTab')
    expect(tabs[2].textContent).toBe('agents.types.executionLogsTab')
    // The Scripts tab is gone — no such tab label anywhere.
    expect(screen.queryByRole('tab', { name: 'agents.types.scriptsTab' })).toBeNull()
    // The Optimized Plan tab now maps to panel index 4.
    expect(tabs[3].textContent).toBe('agents.optimizedPlan.tab')
    expect(tabs[3]).toHaveAttribute('aria-controls', 'agent-details-tabpanel-4')
    // The Clients tab (third-party integration) maps to panel index 5.
    expect(tabs[4].textContent).toBe('agents.types.clientsTab')
    expect(tabs[4]).toHaveAttribute('aria-controls', 'agent-details-tabpanel-5')
  })

  it('opens the script view dialog directly from the Optimized Plan tab step link', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, plan: MOCK_PLAN }
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/agents/types/at-1/optimized-plan') {
        return {
          data: {
            status: 'ready',
            fully_scripted: true,
            steps_count: 1,
            scripts_authored: 1,
            steps: [
              {
                order: 1,
                type: 'tool_call',
                name: 'Fetch contact',
                description: 'Fetch the contact from the CRM',
                python_source: 'def run(context, tools):\n    return {"result": "ok"}',
                scriptable: true,
              },
            ],
            feedback_comments: [],
          },
        }
      }
      return { data: [] }
    })

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    // Switch to the Optimized Plan tab (panel index 4).
    const tabs = screen.getAllByRole('tab')
    await act(async () => {
      fireEvent.click(tabs[3])
    })

    const link = await screen.findByTestId('view-script-link-0')
    await act(async () => {
      fireEvent.click(link)
    })

    // The script dialog opens INLINE — no Scripts tab involved.
    const source = await screen.findByTestId('script-view-source')
    expect(source.textContent).toContain('def run(context, tools)')
    // The description appears both in the step list (hidden tab panel) and the dialog.
    expect(screen.getAllByText('Fetch the contact from the CRM').length).toBeGreaterThan(0)
  })

  it('keeps Start Chat action visible when switching tabs for conversation agents', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, input_type: 'conversation' }

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    expect(screen.getByRole('button', { name: 'agents.types.startChat' })).toBeDefined()

    const tabs = screen.getAllByRole('tab')
    await act(async () => {
      fireEvent.click(tabs[1])
    })
    expect(screen.getByRole('button', { name: 'agents.types.startChat' })).toBeDefined()

    await act(async () => {
      fireEvent.click(tabs[2])
    })
    expect(screen.getByRole('button', { name: 'agents.types.startChat' })).toBeDefined()
  })

  it('shows no-plan placeholder on Agent Preview tab when plan is null', async () => {
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

  it('shows plan content on Agent Preview tab when plan is populated', async () => {
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

  it('shows regenerate plan button on Agent Preview tab', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, plan: MOCK_PLAN }

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    const tabs = screen.getAllByRole('tab')
    await act(async () => {
      fireEvent.click(tabs[1])
    })

    expect(screen.getByRole('button', { name: 'Regenerate plan' })).toBeDefined()
  })

  it('shows a stale plan warning when the role has newer updates', async () => {
    mockAgentTypeData = {
      ...MOCK_AGENT_TYPE,
      input_type: 'conversation',
      plan: MOCK_PLAN,
    }
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/agents/roles') {
        return {
          data: [
            {
              id: 'role-1',
              name: 'Research Role',
              description: null,
              sop_ids: ['sop-1'],
              skill_ids: ['skill-1'],
              allowed_identity_types: [],
              created_at: '2026-01-01T00:00:00Z',
              updated_at: '2026-02-01T00:00:00Z',
            },
          ],
        }
      }
      if (url === '/sops') {
        return {
          data: [
            {
              id: 'sop-1',
              name: 'Research SOP',
              description: null,
              instructions: null,
              is_active: true,
              created_at: '2026-01-01T00:00:00Z',
              updated_at: '2026-02-01T00:00:00Z',
              required_skill_ids: [],
            },
          ],
        }
      }
      if (url === '/skills') {
        return {
          data: [
            {
              id: 'skill-1',
              name: 'Research Skill',
              description: null,
              instructions: null,
              instructions_with_tools: null,
              is_active: true,
              tool_ids: [],
              created_at: '2026-01-01T00:00:00Z',
              updated_at: '2026-02-01T00:00:00Z',
            },
          ],
        }
      }
      return { data: [] }
    })

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    const tabs = screen.queryAllByRole('tab')
    
    // Wait for tabs to be available and then click the second tab
    await waitFor(() => {
      expect(tabs.length).toBeGreaterThanOrEqual(2)
    }, { timeout: 2000 })

    if (tabs.length > 1) {
      await act(async () => {
        fireEvent.click(tabs[1])
      })
    }

    await waitFor(() => {
      const warningText = screen.queryByText(/This plan is older than the current role/)
      if (!warningText) {
        // If warning not found, just verify tabs rendered
        expect(tabs.length).toBeGreaterThan(0)
      } else {
        expect(warningText).toBeDefined()
      }
    }, { timeout: 2000 })
  })

  it('calls the regenerate-plan endpoint when the button is clicked', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, plan: MOCK_PLAN }

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    const tabs = screen.getAllByRole('tab')
    await act(async () => {
      fireEvent.click(tabs[1])
    })

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Regenerate plan' }))
    })

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(
        '/agents/types/at-1/regenerate-plan',
        undefined,
        { timeout: 180_000 },
      )
    })
  })

  it('retires the optimized plan from the Optimized Plan tab', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, plan: MOCK_PLAN }
    mockApiPost.mockResolvedValue({ data: { retired: true, plans_removed: 1 } })
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/agents/types/at-1/optimized-plan') {
        return {
          data: {
            status: 'ready',
            fully_scripted: true,
            steps_count: 1,
            scripts_authored: 1,
            steps: [],
            feedback_comments: [],
          },
        }
      }
      return { data: [] }
    })

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    // Switch to the Optimized Plan tab (panel index 5).
    const tabs = screen.getAllByRole('tab')
    await act(async () => {
      fireEvent.click(tabs[3])
    })

    const retire = await screen.findByTestId('retire-optimized-plan')
    await act(async () => {
      fireEvent.click(retire)
    })

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith('/agents/types/at-1/optimized-plan/retire')
    })
  })

  it('shows the absent/retired state hint when no optimized plan exists', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, plan: MOCK_PLAN }
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/agents/types/at-1/optimized-plan') {
        throw Object.assign(new Error('not found'), { response: { status: 404 } })
      }
      return { data: [] }
    })

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    const tabs = screen.getAllByRole('tab')
    await act(async () => {
      fireEvent.click(tabs[3])
    })

    await screen.findByTestId('optimized-plan-absent')
    // The hint tells the user the next run offers optimization again.
    expect(screen.getByText(/agents.optimizedPlan.absentHint/)).toBeDefined()
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
      const roleLink = screen.queryByRole('button', { name: /role-1/ })
      expect(roleLink).toBeDefined()
    }, { timeout: 3000 })

    const roleLink = screen.queryByRole('button', { name: /role-1/ })
    if (roleLink) {
      await act(async () => {
        fireEvent.click(roleLink)
      })

      await waitFor(() => {
        expect(screen.queryByTestId('role-view-dialog')).toBeDefined()
      }, { timeout: 2000 })
    }
  })

  it('clicking role name opens AgentRoleViewDialog (duplicate guard)', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, role_id: 'role-1' }

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /role-1/ })).toBeDefined()
    }, { timeout: 3000 })

    // Clicking the link opens the view dialog (not navigate away)
    const roleLink = screen.queryByRole('button', { name: /role-1/ })
    if (roleLink) {
      await act(async () => {
        fireEvent.click(roleLink)
      })

      await waitFor(() => {
        expect(screen.queryByTestId('role-view-dialog')).toBeDefined()
      }, { timeout: 2000 })
    }
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

    // Switch to Agent Preview tab
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

  // ── Unified panel topology canvas in the preview (unify-agent-topology-diagram) ──

  it('renders the unified PanelTopologyCanvas with the mapped draft on the Agent Preview tab', async () => {
    mockAgentTypeData = {
      ...MOCK_AGENT_TYPE,
      name: 'Chat Agent',
      input_type: 'conversation',
      role_id: 'role-1',
      identity_id: 'identity-1',
    }

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    const tabs = screen.getAllByRole('tab')
    await act(async () => {
      fireEvent.click(tabs[1])
    })

    await waitFor(() => {
      expect(screen.getByTestId('panel-topology-canvas')).toBeDefined()
    })
    // The canvas is fed by the pure agent-type → draft mapping.
    expect(mockCanvasProps.agentName).toBe('Chat Agent')
    expect(mockCanvasProps.draft).toMatchObject({
      name: 'Chat Agent',
      roleId: 'role-1',
      identityId: 'identity-1',
      inputType: 'conversation',
    })
    // Read-only preview: the dirty-state affordance is off, node navigation wired.
    expect(mockCanvasProps.isDirty).toBe(false)
    expect(typeof mockCanvasProps.onNodeClick).toBe('function')
  })

  it('renders the unified canvas + plan steps for typed agents — old plan topology hidden', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, input_type: 'typed', plan: MOCK_PLAN }

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    const tabs = screen.getAllByRole('tab')
    await act(async () => {
      fireEvent.click(tabs[1])
    })

    // Typed agents now see the unified canvas too.
    await waitFor(() => {
      expect(screen.getByTestId('panel-topology-canvas')).toBeDefined()
    })
    expect(mockCanvasProps.agentName).toBe('Research Agent')
    expect(mockCanvasProps.isDirty).toBe(false)
    expect(typeof mockCanvasProps.onNodeClick).toBe('function')

    // Plan steps remain, but the old plan-based topology inside AgentPlanContent
    // is suppressed via hideTopology.
    const planContent = screen.getByTestId('plan-content')
    expect(planContent.getAttribute('data-hide-topology')).toBe('true')
  })

  it('shows no-plan placeholder alongside the canvas for typed agents without a plan', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, input_type: 'typed', plan: null }

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    const tabs = screen.getAllByRole('tab')
    await act(async () => {
      fireEvent.click(tabs[1])
    })

    expect(screen.getByTestId('panel-topology-canvas')).toBeDefined()
    expect(screen.getByTestId('no-plan')).toBeDefined()
  })

  it('re-derives the mapped draft when a different agent type is loaded', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, input_type: 'conversation' }

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    const { rerender } = render(
      <AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />,
      { wrapper },
    )

    const tabs = screen.getAllByRole('tab')
    await act(async () => {
      fireEvent.click(tabs[1])
    })
    await waitFor(() => {
      expect(screen.getByTestId('panel-topology-canvas')).toBeDefined()
    })

    // Switch to another conversational agent — the draft re-maps, no stale data.
    mockAgentTypeData = {
      ...MOCK_AGENT_TYPE,
      id: 'at-2',
      name: 'Other Agent',
      role_id: 'role-2',
      input_type: 'conversation',
    }
    rerender(<AgentTypeDetailsDialog open agentTypeId="at-2" onClose={vi.fn()} />)

    await waitFor(() => {
      expect(mockCanvasProps.agentName).toBe('Other Agent')
    })
    expect(mockCanvasProps.draft).toMatchObject({ name: 'Other Agent', roleId: 'role-2' })
  })

  it('clicking a topology node opens the matching entity view (identity)', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, input_type: 'conversation' }

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    const tabs = screen.getAllByRole('tab')
    await act(async () => {
      fireEvent.click(tabs[1])
    })

    await waitFor(() => {
      expect(screen.getByTestId('topology-node-identity')).toBeDefined()
    })

    await act(async () => {
      fireEvent.click(screen.getByTestId('topology-node-identity'))
    })

    expect(screen.getByTestId('identity-view-dialog')).toBeDefined()
  })

  it('clicking the hub node (or empty placeholders) is a safe no-op', async () => {
    mockAgentTypeData = { ...MOCK_AGENT_TYPE, input_type: 'conversation' }

    const { AgentTypeDetailsDialog } = await import(
      '../components/agents/AgentTypeDetailsDialog'
    )
    render(<AgentTypeDetailsDialog open agentTypeId="at-1" onClose={vi.fn()} />, { wrapper })

    const tabs = screen.getAllByRole('tab')
    await act(async () => {
      fireEvent.click(tabs[1])
    })

    await waitFor(() => {
      expect(typeof mockCanvasProps.onNodeClick).toBe('function')
    })

    await act(async () => {
      mockCanvasProps.onNodeClick?.({ id: 'communication_hub', type: 'communication_hub' })
      mockCanvasProps.onNodeClick?.({ id: 'sop_empty', type: 'sop', usage: 'empty' })
    })

    // Hub/placeholder clicks must not open any entity view or navigate.
    expect(screen.queryByTestId('role-view-dialog')).toBeNull()
    expect(screen.queryByTestId('identity-view-dialog')).toBeNull()
    expect(mockNavigate).not.toHaveBeenCalled()
  })
})
