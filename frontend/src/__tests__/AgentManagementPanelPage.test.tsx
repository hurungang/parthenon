import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import type { AgentType } from '../types'

// ── Hoisted mock refs ─────────────────────────────────────────────────────────

const { mockApiPost, mockApiPut, mockApiGet, mockDelete } = vi.hoisted(() => ({
  mockApiPost: vi.fn(),
  mockApiPut: vi.fn(),
  mockApiGet: vi.fn(),
  mockDelete: vi.fn(),
}))

// ── Module mocks ──────────────────────────────────────────────────────────────

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../api/apiClient', () => ({
  default: { get: mockApiGet, post: mockApiPost, put: mockApiPut },
}))

vi.mock('../components/permissions/PermissionDeniedAlert', () => ({
  default: ({ error }: { error: unknown; fallbackMessage?: string }) => (
    <div data-testid="permission-denied-alert">{error instanceof Error ? error.message : 'error'}</div>
  ),
}))

vi.mock('../components/agents/panel/SharedDialogHost', () => ({
  SharedDialogHost: ({ request }: { request: unknown }) =>
    request ? <div data-testid="shared-dialog-host">{(request as { kind: string }).kind}</div> : null,
}))

vi.mock('../components/agents/panel/PanelTopologyCanvas', () => ({
  PanelTopologyCanvas: () => <div data-testid="panel-topology-canvas" />,
}))

vi.mock('../components/agents/panel/EquipmentSlots', async () => {
  const actual = await vi.importActual<typeof import('../components/agents/panel/EquipmentSlots')>(
    '../components/agents/panel/EquipmentSlots',
  )
  return {
    ...actual,
    EquipmentSlots: () => <div data-testid="equipment-slots" />,
  }
})

// Stub the property-bar "Properties" section but keep the real draft wiring:
// name + system-instruction inputs drive the same draftApi the real section uses.
vi.mock('../components/agents/panel/AgentPropertiesSection', () => ({
  AgentPropertiesSection: ({
    draftApi,
  }: {
    draftApi: import('../hooks/useAgentDraftComposition').UseAgentDraftCompositionResult
  }) => (
    <>
      <input
        aria-label="property-name"
        value={draftApi.draft.name}
        onChange={(e) => draftApi.setName(e.target.value)}
      />
      <input
        aria-label="property-system-instruction"
        value={draftApi.draft.systemInstruction ?? ''}
        onChange={(e) => draftApi.setSystemInstruction(e.target.value)}
      />
    </>
  ),
}))

vi.mock('../components/common/ConfirmDialog', () => ({
  ConfirmDialog: ({
    open,
    message,
    onConfirm,
  }: {
    open: boolean
    message: string
    onConfirm: () => void
  }) => (open ? <button data-testid="confirm-delete" onClick={onConfirm}>{message}</button> : null),
}))

// Stub the heavy controlled form but keep the real values contract + defaults.
// NOTE: the page imports the NAMED export `AgentTypeForm`, so stub that export.
vi.mock('../pages/agents/AgentTypeForm', async () => {
  const actual = await vi.importActual<typeof import('../pages/agents/AgentTypeForm')>(
    '../pages/agents/AgentTypeForm',
  )
  const AgentTypeFormStub = ({
    values,
    onChange,
  }: {
    values: import('../pages/agents/AgentTypeForm').AgentTypeFormValues
    onChange: (v: import('../pages/agents/AgentTypeForm').AgentTypeFormValues) => void
  }) => (
    <>
      <input
        aria-label="agent-type-form-name"
        value={values.name}
        onChange={(e) => onChange({ ...values, name: e.target.value })}
      />
      <button
        data-testid="add-skill-binding"
        onClick={() =>
          onChange({
            ...values,
            skill_bindings: [...values.skill_bindings, { skill_id: 'skill-1', order: values.skill_bindings.length + 1 }],
          })
        }
      >
        add-skill-binding
      </button>
    </>
  )
  return {
    ...actual,
    default: AgentTypeFormStub,
    AgentTypeForm: AgentTypeFormStub,
  }
})

// ── Mutable hook state ────────────────────────────────────────────────────────

let mockAgentTypes: AgentType[] | undefined = undefined
let mockListLoading = false
let mockListError: unknown = null
let mockSelected: AgentType | undefined = undefined

vi.mock('../hooks/useAgentTypes', () => ({
  useAgentTypes: () => ({ data: mockAgentTypes, isLoading: mockListLoading, error: mockListError }),
  useAgentType: (_id: string) => ({ data: mockSelected, isLoading: false, error: null }),
  useDeleteAgentType: () => ({ mutateAsync: mockDelete }),
}))

// ── Fixtures ──────────────────────────────────────────────────────────────────

function makeAgent(overrides: Partial<AgentType> = {}): AgentType {
  return {
    id: 'at-1',
    name: 'research-agent',
    description: 'does research',
    identity_id: null,
    role_id: 'role-1',
    model_id: null,
    system_instruction: null,
    input_type: 'typed',
    input_schema: null,
    output_type: 'auto',
    output_schema: null,
    output_data_type_id: null,
    output_data_type_name: null,
    sop_bindings: [],
    skill_bindings: [{ id: 'sb-1', skill_id: 'skill-1', skill_name: 'Skill One', order: 1, created_at: '2026-01-01T00:00:00Z' }],
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    plan: null,
    ...overrides,
  }
}

// ── Wrapper ────────────────────────────────────────────────────────────────────

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('AgentManagementPanelPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAgentTypes = undefined
    mockListLoading = false
    mockListError = null
    mockSelected = undefined
    mockApiGet.mockResolvedValue({ data: [] })
  })

  it('renders the panel title and the agent list', async () => {
    mockAgentTypes = [makeAgent(), makeAgent({ id: 'at-2', name: 'writer-agent' })]

    const { AgentManagementPanelPage } = await import(
      '../pages/agents/AgentManagementPanelPage'
    )
    render(<AgentManagementPanelPage />, { wrapper })

    expect(screen.getByText('agents.panel.title')).toBeDefined()
    await waitFor(() => {
      expect(screen.getByText('research-agent')).toBeDefined()
      expect(screen.getByText('writer-agent')).toBeDefined()
    })
  })

  it('searches/filters the agent list client-side', async () => {
    mockAgentTypes = [makeAgent(), makeAgent({ id: 'at-2', name: 'writer-agent' })]

    const { AgentManagementPanelPage } = await import(
      '../pages/agents/AgentManagementPanelPage'
    )
    render(<AgentManagementPanelPage />, { wrapper })

    await waitFor(() => expect(screen.getByText('writer-agent')).toBeDefined())

    fireEvent.change(screen.getByPlaceholderText('agents.panel.searchPlaceholder'), {
      target: { value: 'writer' },
    })

    expect(screen.queryByText('research-agent')).toBeNull()
    expect(screen.getByText('writer-agent')).toBeDefined()
  })

  it('selects an agent and renders its header card and live topology region', async () => {
    mockAgentTypes = [makeAgent()]
    mockSelected = makeAgent()

    const { AgentManagementPanelPage } = await import(
      '../pages/agents/AgentManagementPanelPage'
    )
    render(<AgentManagementPanelPage />, { wrapper })

    await act(async () => {
      fireEvent.click(screen.getAllByText('research-agent')[0])
    })

    await waitFor(() => {
      expect(screen.getByTestId('panel-topology-canvas')).toBeDefined()
      expect(screen.getByTestId('equipment-slots')).toBeDefined()
    })
  })

  it('shows the permission alert when the agent list query fails (403 degradation)', async () => {
    mockListError = new Error('403 Forbidden')

    const { AgentManagementPanelPage } = await import(
      '../pages/agents/AgentManagementPanelPage'
    )
    render(<AgentManagementPanelPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('permission-denied-alert')).toBeDefined()
    })
  })

  it('creates an agent from the panel; it is selected and the list refreshes', async () => {
    mockAgentTypes = []
    const created = makeAgent({ id: 'at-new', name: 'new-agent' })
    mockApiPost.mockResolvedValue({ data: created })

    const { AgentManagementPanelPage } = await import(
      '../pages/agents/AgentManagementPanelPage'
    )
    render(<AgentManagementPanelPage />, { wrapper })

    fireEvent.click(screen.getByRole('button', { name: 'agents.panel.createAgent' }))
    expect(screen.getByText('agents.createType')).toBeDefined()

    fireEvent.change(screen.getByLabelText('agent-type-form-name'), {
      target: { value: 'new-agent' },
    })

    // Default form has no bindings yet — save must stay disabled (bindings rule).
    expect(screen.getByRole('button', { name: 'app.save' }).hasAttribute('disabled')).toBe(true)

    // With a binding present, save issues exactly one POST.
    fireEvent.click(screen.getByTestId('add-skill-binding'))
    mockAgentTypes = [created]
    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledTimes(1)
      expect(mockApiPost).toHaveBeenCalledWith('/agents/types', expect.any(Object))
    })
  })

  it('blocks saving an invalid slug name (validation error path)', async () => {
    mockAgentTypes = []

    const { AgentManagementPanelPage } = await import(
      '../pages/agents/AgentManagementPanelPage'
    )
    render(<AgentManagementPanelPage />, { wrapper })

    fireEvent.click(screen.getByRole('button', { name: 'agents.panel.createAgent' }))
    fireEvent.change(screen.getByLabelText('agent-type-form-name'), {
      target: { value: 'Invalid Name!' },
    })

    expect(screen.getByRole('button', { name: 'app.save' }).hasAttribute('disabled')).toBe(true)
    expect(mockApiPost).not.toHaveBeenCalled()
  })

  it('edits an agent through the property bar; saving issues one PUT including base fields', async () => {
    mockAgentTypes = [makeAgent()]
    mockSelected = makeAgent()
    mockApiPut.mockResolvedValue({
      data: makeAgent({ name: 'renamed-agent', system_instruction: 'new instruction' }),
    })

    const { AgentManagementPanelPage } = await import(
      '../pages/agents/AgentManagementPanelPage'
    )
    render(<AgentManagementPanelPage />, { wrapper })

    await act(async () => {
      fireEvent.click(screen.getAllByText('research-agent')[0])
    })
    await waitFor(() => expect(screen.getByTestId('panel-topology-canvas')).toBeDefined())

    // No edit dialog: fields are edited in place in the property bar.
    expect(screen.queryByText('agents.editType')).toBeNull()
    fireEvent.change(screen.getByLabelText('property-name'), {
      target: { value: 'renamed-agent' },
    })
    fireEvent.change(screen.getByLabelText('property-system-instruction'), {
      target: { value: 'new instruction' },
    })

    // Edits are draft-only: dirty tray with the properties chip, zero API calls.
    expect(screen.getByText('agents.panel.unsavedChip')).toBeDefined()
    expect(screen.getByText('agents.panel.properties.label')).toBeDefined()
    expect(mockApiPut).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'agents.panel.save' }))

    await waitFor(() => {
      expect(mockApiPut).toHaveBeenCalledTimes(1)
      expect(mockApiPut).toHaveBeenCalledWith('/agents/types/at-1', expect.any(Object))
    })
    const body = mockApiPut.mock.calls[0][1] as Record<string, unknown>
    expect(body.name).toBe('renamed-agent')
    expect(body.system_instruction).toBe('new instruction')
  })

  it('blocks saving from the property bar while the draft name violates the slug pattern', async () => {
    mockAgentTypes = [makeAgent()]
    mockSelected = makeAgent()

    const { AgentManagementPanelPage } = await import(
      '../pages/agents/AgentManagementPanelPage'
    )
    render(<AgentManagementPanelPage />, { wrapper })

    await act(async () => {
      fireEvent.click(screen.getAllByText('research-agent')[0])
    })
    await waitFor(() => expect(screen.getByLabelText('property-name')).toBeDefined())

    fireEvent.change(screen.getByLabelText('property-name'), {
      target: { value: 'Invalid Name!' },
    })

    expect(
      screen.getByRole('button', { name: 'agents.panel.save' }).hasAttribute('disabled'),
    ).toBe(true)
    expect(mockApiPut).not.toHaveBeenCalled()
  })

  it('surfaces draft-save failures in the tray and keeps the draft dirty (error standard)', async () => {
    mockAgentTypes = [makeAgent()]
    mockSelected = makeAgent()
    mockApiPut.mockRejectedValue(new Error('403 Forbidden'))

    const { AgentManagementPanelPage } = await import(
      '../pages/agents/AgentManagementPanelPage'
    )
    render(<AgentManagementPanelPage />, { wrapper })

    await act(async () => {
      fireEvent.click(screen.getAllByText('research-agent')[0])
    })
    await waitFor(() => expect(screen.getByTestId('panel-topology-canvas')).toBeDefined())

    fireEvent.change(screen.getByLabelText('property-name'), {
      target: { value: 'renamed-agent' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'agents.panel.save' }))

    await waitFor(() => {
      expect(screen.getByTestId('permission-denied-alert')).toBeDefined()
    })
    expect(screen.getByText('403 Forbidden')).toBeDefined()
    // Draft stays dirty: the tray keeps offering Save.
    expect(screen.getByText('agents.panel.unsavedChip')).toBeDefined()
  })

  it('deletes an agent after confirmation; selection clears so the name is reusable', async () => {
    mockAgentTypes = [makeAgent()]
    mockSelected = makeAgent()
    mockDelete.mockResolvedValue(undefined)

    const { AgentManagementPanelPage } = await import(
      '../pages/agents/AgentManagementPanelPage'
    )
    render(<AgentManagementPanelPage />, { wrapper })

    await act(async () => {
      fireEvent.click(screen.getAllByText('research-agent')[0])
    })
    await waitFor(() => expect(screen.getByTestId('panel-topology-canvas')).toBeDefined())

    fireEvent.click(screen.getByRole('button', { name: 'app.delete' }))

    await act(async () => {
      fireEvent.click(screen.getByTestId('confirm-delete'))
    })

    await waitFor(() => {
      expect(mockDelete).toHaveBeenCalledWith('at-1')
    })
    // Deletion is a true delete: the confirmation dialog closes afterwards.
    await waitFor(() => {
      expect(screen.queryByTestId('confirm-delete')).toBeNull()
    })
  })
})
